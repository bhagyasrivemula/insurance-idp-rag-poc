"""
Retrieval: from a question (and its scope) to the chunks the LLM will read.

    1. Query rewriting - a follow-up is rewritten by the LLM into a standalone search
                         query ("what about its claims?" -> "How do I make a claim
                         under Health Guard?"). Used for searching only.
    2. Search          - semantic search (embeddings, meaning) and keyword search
                         (BM25, exact words) inside the metadata filters. Mode:
                         "hybrid" (default), "semantic" or "keyword". Semantic hits
                         below MIN_SIMILARITY are dropped as irrelevant.
    3. Fusion          - Reciprocal Rank Fusion, a small boost for topics that matter
                         to the persona, and a per-product cap so comparisons see
                         several products.

Scope detection (which products a question is about) lives in scope.py.
"""
from __future__ import annotations

import re

from langsmith import traceable

from app import config, llm_client, vector_store

SEARCH_MODES = ("hybrid", "semantic", "keyword")
RRF_K = 60                  # standard Reciprocal Rank Fusion constant
MAX_PER_DOC = 3             # keeps comparisons balanced across products
PERSONA_BOOST = 0.002       # small nudge towards topics the persona cares about
SUMMARY_BOOST = 0.02        # product summaries suit overview / comparison questions

# Topics each persona usually cares about (a soft ranking boost, never a hard filter).
PERSONA_TOPICS = {
    "buyer": {"eligibility", "benefits", "premiums", "riders", "tax"},
    "policyholder": {"claims", "policy_servicing", "waiting_period", "exclusions", "contact"},
}

BROAD_QUESTION = re.compile(r"\b(tell me about|overview|summar|key features|what is .* plan|compare|"
                            r"difference|which (plan|policy|one)|best|recommend|suitable|options?)\b", re.I)

REWRITE_PROMPT = (
    "Rewrite the user's latest message as one standalone search query for an insurance brochure "
    "database. Resolve pronouns like 'it', 'its', 'that plan' using the conversation, and keep product "
    "names exactly as written. Reply with the query only."
)

_bm25: vector_store.BM25Index | None = None


def bm25() -> vector_store.BM25Index:
    """Build the keyword index once, on first use (restart the server after re-ingesting)."""
    global _bm25
    if _bm25 is None:
        _bm25 = vector_store.BM25Index().build()
    return _bm25


@traceable(run_type="llm", name="Rewrite follow-up query")
def rewrite_query(question: str, history: list[dict]) -> str:
    """Turn a follow-up into a standalone query (used only for searching, not for answering)."""
    recent = [h for h in history if h.get("role") in ("user", "assistant")][-4:]
    convo = "\n".join(f"{h['role']}: {h['content'][:400]}" for h in recent)
    try:
        rewritten = llm_client.complete([
            {"role": "system", "content": REWRITE_PROMPT},
            {"role": "user", "content": f"Conversation:\n{convo}\n\nLatest message: {question}"},
        ], max_tokens=80)
        return rewritten.strip().strip('"') or question
    except Exception:
        return question             # never fail a question because rewriting failed


def _fuse(vec_hits: list[dict], kw_hits: list[dict]) -> dict[str, dict]:
    """Reciprocal Rank Fusion: score = sum over retrievers of 1 / (RRF_K + rank)."""
    fused: dict[str, dict] = {}
    for source, hits in (("vector", vec_hits), ("keyword", kw_hits)):
        for rank, hit in enumerate(hits, 1):
            entry = fused.setdefault(hit["id"], {**hit, "score": 0.0, "similarity": None,
                                                 "vector_rank": None, "keyword_rank": None})
            entry["score"] += 1 / (RRF_K + rank)
            entry[f"{source}_rank"] = rank
            if source == "vector":
                entry["similarity"] = round(hit["score"], 4)
    return fused


def _boost(entries, question: str, persona: str) -> None:
    """Soft boosts: persona topics, and product summaries for broad questions."""
    wanted = PERSONA_TOPICS.get(persona, set())
    broad = bool(BROAD_QUESTION.search(question))
    for entry in entries:
        meta = entry["metadata"]
        if any(meta.get(f"topic_{t}") for t in wanted):
            entry["score"] += PERSONA_BOOST
        if broad and meta.get("content_type") == "key_facts":
            entry["score"] += SUMMARY_BOOST


def _diversify(ranked: list[dict], top_k: int) -> list[dict]:
    """Take the top results, at most MAX_PER_DOC per product (no cap when only one product is in scope)."""
    single_doc = len({e["metadata"]["doc_id"] for e in ranked}) == 1
    cap = top_k if single_doc else MAX_PER_DOC
    results, per_doc = [], {}
    for entry in ranked:
        doc = entry["metadata"]["doc_id"]
        if per_doc.get(doc, 0) < cap:
            per_doc[doc] = per_doc.get(doc, 0) + 1
            results.append(entry)
        if len(results) == top_k:
            break
    return results


def _trace_docs(output) -> dict:
    """Show retrieved chunks as documents in LangSmith's retriever view."""
    results, info = output
    docs = [{"page_content": r["text"], "type": "Document",
             "metadata": {k: r["metadata"].get(k) for k in ("product_name", "section", "page_start")}
                         | {"score": r["score"], "similarity": r.get("similarity")}} for r in results]
    return {"documents": docs, **info}


@traceable(run_type="retriever", name="Hybrid search", process_outputs=_trace_docs)
def search(question: str, filters: dict, persona: str = "buyer", top_k: int | None = None,
           search_text: str | None = None, mode: str = "hybrid") -> tuple[list[dict], dict]:
    """
    Retrieve chunks inside the given metadata filters.
      mode        - "hybrid" (semantic + keyword), "semantic" or "keyword"
      search_text - the query actually searched (e.g. a rewritten follow-up)
    Returns (results, info). Each result has id, text, metadata, score, similarity
    (cosine, semantic hits only) and its rank in each retriever. `info` holds the best
    semantic similarity (used by the off-topic guardrail) and what was searched.
    """
    top_k = top_k or config.TOP_K
    mode = mode if mode in SEARCH_MODES else "hybrid"
    text = search_text or question

    # Semantic search always runs: its best similarity tells the guardrail whether the question is on-topic.
    query_vec = llm_client.embed([text])[0]
    vec_all = vector_store.vector_search(query_vec, vector_store.build_where(filters), config.CANDIDATE_K)
    best = max((h["score"] for h in vec_all), default=None)
    vec_hits = [h for h in vec_all if h["score"] >= config.MIN_SIMILARITY] if mode != "keyword" else []
    kw_hits = bm25().search(text, filters, config.CANDIDATE_K) if mode != "semantic" else []

    fused = _fuse(vec_hits, kw_hits)
    _boost(fused.values(), question, persona)
    results = _diversify(sorted(fused.values(), key=lambda e: e["score"], reverse=True), top_k)
    info = {"mode": mode, "query": text, "best_similarity": round(best, 4) if best is not None else None}
    return results, info
