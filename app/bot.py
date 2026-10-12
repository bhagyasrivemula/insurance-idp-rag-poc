"""
The insurance assistant: retrieval-augmented answers with citations.

    answer_stream(question, persona, history, ui_filters, previous_filters)

yields events the API forwards to the browser as NDJSON:

    {"type": "meta",       "sources": [...], "filters": {...}, "filter_source": "question", "checks": [...]}
    {"type": "token",      "text": "The entry age ..."}           (many)
    {"type": "guardrails", "checks": [...]}                        (output checks)
    {"type": "done",       "timings": {...}, "trace_url": "https://smith.langchain.com/..."}

Flow: input guardrails -> scope -> query rewrite -> search -> off-topic guardrail
      -> generate -> output guardrails. The whole run is one LangSmith trace.
Prompt wording lives in prompts.py; scope detection in scope.py.
"""
from __future__ import annotations

import time
from typing import Iterator

from langsmith import traceable

from app import config, guardrails, llm_client, prompts, retriever, scope


def _section(meta: dict) -> str:
    """Section title for display (older indexes may carry bullet remnants such as '- Claims')."""
    return meta["section"].lstrip("-:. ").strip() or "General"


def build_context(chunks: list[dict]) -> str:
    """Number each excerpt and label it with product, section and page so the model can cite it."""
    parts = []
    for i, c in enumerate(chunks, 1):
        m = c["metadata"]
        pages = f"p.{m['page_start']}" if m["page_start"] == m["page_end"] else f"pp.{m['page_start']}-{m['page_end']}"
        if m["content_type"] == "key_facts":
            pages = "summary"
        body = c["text"].split("\n", 1)[-1]          # drop the context line; the label below carries it
        parts.append(f"[{i}] {m['company']} - {m['product_name']} ({pages}, section: {_section(m)})\n{body}")
    return "\n\n".join(parts)


def source_cards(chunks: list[dict]) -> list[dict]:
    """Compact source descriptions for the UI (citations panel + 'open PDF at page' links)."""
    cards = []
    for i, c in enumerate(chunks, 1):
        m = c["metadata"]
        cards.append({
            "n": i,
            "doc_id": m["doc_id"],
            "file_name": m["file_name"],
            "company": m["company"],
            "product_name": m["product_name"],
            "product_type": m["product_type"],
            "section": _section(m),
            "page": m["page_start"],
            "page_end": m["page_end"],
            "content_type": m["content_type"],
            "topic": m["topic"],
            "excerpt": c["text"].split("\n", 1)[-1],      # full chunk; the UI clamps long excerpts
            "score": round(c["score"], 4),
            "similarity": c.get("similarity"),            # cosine similarity (semantic hits only)
            "vector_rank": c.get("vector_rank"),
            "keyword_rank": c.get("keyword_rank"),
        })
    return cards


def _history_messages(history: list[dict]) -> list[dict]:
    """Keep the last few turns (trimmed) so follow-ups make sense without overflowing the context window."""
    recent = [h for h in (history or []) if h.get("role") in ("user", "assistant")][-config.HISTORY_TURNS:]
    return [{"role": h["role"], "content": h["content"][:800]} for h in recent]


def _summarise_events(events: list[dict]) -> dict:
    """How a streamed answer appears in LangSmith: one readable output instead of hundreds of tokens."""
    text = "".join(e.get("text", "") for e in events if e.get("type") == "token")
    meta = next((e for e in events if e.get("type") == "meta"), {})
    guards = next((e["checks"] for e in events if e.get("type") == "guardrails"), [])
    return {"answer": text, "scope": meta.get("filters"), "sources": len(meta.get("sources", [])),
            "guardrails": guards}


def _trace_url() -> str | None:
    """Link to this run in LangSmith (shown under the answer when tracing is on)."""
    if not config.TRACING_ENABLED:
        return None
    try:
        from langsmith.run_helpers import get_current_run_tree
        run = get_current_run_tree()
        return run.get_url() if run else None
    except Exception:
        return None


@traceable(run_type="chain", name="InsureAssist: answer question", reduce_fn=_summarise_events,
           process_inputs=lambda i: {"question": i["question"], "persona": i.get("persona"),
                                     "filters": i.get("ui_filters")})
def answer_stream(question: str, persona: str = "buyer", history: list[dict] | None = None,
                  ui_filters: dict | None = None, previous_filters: dict | None = None) -> Iterator[dict]:
    """
    Answer one question, yielding events for the UI:
        meta        - sources, scope and input-guardrail results (sent before the answer)
        token       - answer text, streamed
        guardrails  - output-guardrail results (after the answer)
        done        - timings (+ LangSmith trace link when tracing is on)
    """
    persona = persona if persona in prompts.PERSONA_PROMPTS else "buyer"
    history = history or []
    t_start = time.perf_counter()

    def finish(timings: dict):
        return {"type": "done", "timings": timings, "trace_url": _trace_url()}

    # ---- Small talk: no retrieval needed ----
    if prompts.GREETING.match(question):
        yield {"type": "meta", "sources": [], "filters": previous_filters or {}, "filter_source": "none", "checks": []}
        yield {"type": "token", "text": prompts.GREETING_REPLY}
        yield finish({"total_ms": 0})
        return

    # ---- 1. Input guardrails: PII masking, prompt injection, content safety ----
    guard = guardrails.check_input(question)
    question = guard["question"]                     # from here on, personal data is masked
    if guard["blocked"]:
        yield {"type": "meta", "sources": [], "filters": {}, "filter_source": "none", "checks": guard["checks"]}
        yield {"type": "token", "text": guard["message"]}
        yield finish({"total_ms": round((time.perf_counter() - t_start) * 1000)})
        return

    # ---- 2. Decide filters; rewrite follow-ups into standalone search queries ----
    filters, filter_source = scope.resolve_filters(question, ui_filters or {}, previous_filters, scope.load_catalog())
    search_text = question
    if history and (filter_source == "conversation" or scope.FOLLOW_UP.search(question)):
        search_text = retriever.rewrite_query(question, history)

    # ---- 3. Search (semantic + keyword) ----
    chunks, info = retriever.search(question, filters, persona, search_text=search_text)
    if not chunks and filters:
        # Filters were too narrow (e.g. "HDFC health plan" when HDFC has none) - widen the search.
        chunks, info = retriever.search(question, {}, persona, search_text=search_text)
        filter_source, filters = "relaxed", {}
    t_retrieved = time.perf_counter()

    # ---- 4. Off-topic guardrail (uses the best semantic similarity) ----
    topic = guardrails.check_topic(question, info["best_similarity"])
    checks = guard["checks"] + [topic]
    if topic["status"] == "block":
        chunks = []
    meta = {"type": "meta", "sources": source_cards(chunks), "filters": filters, "filter_source": filter_source,
            "checks": checks, "search_query": search_text if search_text != question else None}
    yield meta

    if not chunks:
        text = guardrails.OFF_TOPIC_MESSAGE if topic["status"] == "block" else prompts.NOT_FOUND_REPLY
        yield {"type": "token", "text": text}
        yield finish({"retrieval_ms": round((t_retrieved - t_start) * 1000)})
        return

    # ---- 5. Generate ----
    products = sorted({f"{c['metadata']['company']} {c['metadata']['product_name']}" for c in chunks})
    messages = [
        {"role": "system", "content": prompts.system_prompt(persona)},
        *_history_messages(history),
        {"role": "user", "content": prompts.user_prompt(question, products, build_context(chunks))},
    ]
    answer_text, first_token_at = "", None
    for token in llm_client.stream_chat(messages):
        if first_token_at is None:
            first_token_at = time.perf_counter()
        answer_text += token
        yield {"type": "token", "text": token}

    # ---- 6. Output guardrails: grounded figures, citations, no promises ----
    yield {"type": "guardrails", "checks": guardrails.check_output(answer_text, [c["text"] for c in chunks])}

    t_end = time.perf_counter()
    yield finish({
        "retrieval_ms": round((t_retrieved - t_start) * 1000),
        "first_token_ms": round(((first_token_at or t_end) - t_start) * 1000),
        "total_ms": round((t_end - t_start) * 1000),
    })


def answer(question: str, persona: str = "buyer", history: list[dict] | None = None,
           ui_filters: dict | None = None) -> dict:
    """
    Non-streaming answer, used by the RAGAS evaluation.
    Returns {"answer", "contexts" (texts the LLM read), "sources", "checks"}.
    """
    out = {"answer": "", "contexts": [], "sources": [], "checks": []}
    for event in answer_stream(question, persona, history, ui_filters):
        if event["type"] == "meta":
            out["sources"] = event["sources"]
            out["contexts"] = [s["excerpt"] for s in event["sources"]]
            out["checks"] += event.get("checks", [])
        elif event["type"] == "token":
            out["answer"] += event["text"]
        elif event["type"] == "guardrails":
            out["checks"] += event["checks"]
    return out
