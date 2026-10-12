"""
IDP Stage 4 - Semantic chunking + metadata enrichment.

Why not split every N characters? Because a chunk that cuts an eligibility
table in half, or mixes "Exclusions" with "Claims", retrieves badly and makes
the bot answer wrongly. The splitting rules (section boundaries, semantic
breakpoints, table rows) live in splitting.py; this module turns the pieces
into chunks:

    * Each chunk starts with a context line ("HDFC Life | Sanchay Plus | Savings
      | Section: ELIGIBILITY") so both the embedding and the LLM know which
      product the text belongs to - brochures rarely repeat the product name.
    * Each chunk gets metadata that ChromaDB can filter on: company, product_name,
      product_type, doc_type, page_start/page_end, section, content_type
      (text | table | key_facts), topic and topic_<name> boolean flags.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.idp.document_loader import DocumentInfo
from app.idp.layout_extractor import Element
from app.idp.splitting import split_document

MIN_CHUNK_CHARS = 40          # smaller pieces (stray labels) are dropped
HEADING_WEIGHT = 3            # a topic word in the section heading counts this many times

# --------------------------------------------------------------------------- #
# Topic taxonomy. Keyword hits decide which topics a chunk is about.
# These power metadata filters ("show me only claims info") and let the bot
# favour servicing topics for existing customers and buying topics for prospects.
# --------------------------------------------------------------------------- #
TOPIC_KEYWORDS: dict[str, list[str]] = {
    "eligibility": ["eligibility", "age at entry", "entry age", "minimum age", "maximum age", "age at maturity",
                    "policy term", "premium payment term", "minimum sum", "maximum sum", "sum assured", "sum insured"],
    "benefits": ["benefit", "coverage", "covered", "payout", "maturity", "death benefit", "cover ", "bonus",
                 "guaranteed", "reimburse", "compensation"],
    "premiums": ["premium", "discount", "loading", "payment mode", "frequency", "monthly", "annualized",
                 "instalment", "charges", "fund management"],
    "exclusions": ["exclusion", "not covered", "excluded", "shall not be liable", "suicide", "not payable",
                   "we will not pay"],
    "waiting_period": ["waiting period", "pre-existing", "initial waiting", "specific waiting", "cooling"],
    "claims": ["claim", "cashless", "intimation", "documents required", "settlement", "network hospital",
               "tpa", "reimbursement"],
    "policy_servicing": ["free look", "free-look", "grace period", "revival", "lapse", "surrender", "loan",
                         "nomination", "assignment", "renewal", "cancellation", "portability", "migration",
                         "paid-up", "discontinu"],
    "riders": ["rider", "add-on", "add on", "optional cover", "top-up"],
    "tax": ["tax", "80c", "80d", "10(10d)", "income tax"],
    "contact": ["toll free", "toll-free", "customer care", "grievance", "ombudsman", "email", "www.", "call us",
                "branch"],
}
TOPICS = list(TOPIC_KEYWORDS)


@dataclass
class Chunk:
    chunk_id: str
    text: str                                   # what the LLM reads (context line + content)
    metadata: dict = field(default_factory=dict)


def tag_topics(text: str, section: str) -> tuple[str, dict[str, bool]]:
    """
    Score topics by keyword hits; the section heading counts extra because
    "EXCLUSIONS" as a heading is a much stronger signal than one mention.
    Returns (primary_topic, {topic_x: bool}).
    """
    body, head = text.lower(), section.lower()
    scores = {t: sum(body.count(k) for k in kws) + HEADING_WEIGHT * sum(head.count(k) for k in kws)
              for t, kws in TOPIC_KEYWORDS.items()}
    primary = max(scores, key=scores.get)
    flags = {f"topic_{t}": scores[t] > 0 for t in TOPICS}
    return (primary if scores[primary] else "general"), flags


def _doc_metadata(doc: DocumentInfo) -> dict:
    """Metadata shared by every chunk of a document."""
    return {"doc_id": doc.doc_id, "file_name": doc.file_name, "company": doc.company,
            "product_name": doc.product_name, "product_type": doc.product_type, "doc_type": doc.doc_type,
            "uin": doc.uin, "source_url": doc.source_url}


def _context_line(doc: DocumentInfo, section: str) -> str:
    return f"{doc.company} | {doc.product_name} | {doc.product_type_label} | Section: {section}"


def build_chunks(doc: DocumentInfo, elements: list[Element]) -> tuple[list[Chunk], dict]:
    """Turn ordered layout elements into retrieval-ready chunks with metadata (+ chunking stats)."""
    pieces, stats = split_document(elements)
    chunks: list[Chunk] = []
    for i, piece in enumerate(pieces):
        if len(piece["content"]) < MIN_CHUNK_CHARS:
            continue
        primary, flags = tag_topics(piece["content"], piece["section"])
        meta = {
            **_doc_metadata(doc),
            "section": piece["section"][:200],
            "page_start": min(piece["pages"]),
            "page_end": max(piece["pages"]),
            "content_type": piece["type"],
            "char_count": len(piece["content"]),
            "topic": primary,
            **flags,
        }
        text = f"{_context_line(doc, piece['section'])}\n{piece['content']}"
        chunks.append(Chunk(f"{doc.doc_id}::{i:04d}", text, meta))
    return chunks, stats


def key_facts_chunk(doc: DocumentInfo, facts_text: str) -> Chunk:
    """
    A synthetic chunk holding the LLM-extracted product summary. It is the best
    hit for broad questions ("tell me about Sanchay Plus", "compare term plans").
    """
    meta = {
        **_doc_metadata(doc), "section": "Product summary (extracted key facts)",
        "page_start": 1, "page_end": doc.page_count, "content_type": "key_facts",
        "char_count": len(facts_text), "topic": "benefits",
        **{f"topic_{t}": t in ("eligibility", "benefits", "premiums") for t in TOPICS},
    }
    return Chunk(f"{doc.doc_id}::summary", f"{_context_line(doc, 'Product summary')}\n{facts_text}", meta)
