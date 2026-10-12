"""
Search scope: which products / insurers / product types a question is about.

    "Is maternity covered in Health Guard?"  -> {"doc_id": ["bajaj_general_health_guard_brochure"]}
    "Which HDFC plans have a free look?"     -> {"company": ["HDFC Life"]}
    "what is its waiting period?"            -> previous answer's scope (follow-up)

Precedence: a product named in the question > a product chosen in the sidebar
> insurer/type named in the question (+ sidebar refinements) > conversation > none.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

from app import config

# Words that signal a product category.
TYPE_HINTS = {
    "term_life": [r"\bterm\b", r"life cover", r"pure (risk|protection)"],
    "health": [r"\bhealth\b", r"\bmedical\b", r"hospital", r"mediclaim", r"maternity", r"cashless"],
    "motor": [r"\bcar\b", r"\bmotor\b", r"vehicle", r"\bbike\b", r"own damage", r"third[- ]party"],
    "travel": [r"\btravel", r"\btrip\b", r"abroad", r"overseas", r"baggage", r"passport", r"\bvisa\b"],
    "ulip": [r"\bulip", r"unit[- ]linked", r"market[- ]linked", r"\bfunds?\b", r"\bnav\b"],
    "savings": [r"savings?\b", r"guaranteed (income|return|maturity)", r"endowment"],
}

COMPANY_HINTS = {
    "HDFC Life": [r"\bhdfc\b"],
    "Bajaj General": [r"\bbajaj\b"],
    "Star Health": [r"\bstar\b"],
    "Axis Max Life": [r"\baxis\b", r"max life"],
}

# First words too generic to identify a product on their own ("travel", "health", ...).
GENERIC_WORDS = {"travel", "health", "family", "private", "click", "smart", "secure", "premium"}

# Pronouns / references that mark a follow-up question.
FOLLOW_UP = re.compile(r"\b(it|its|it's|this|that|these|those|the plan|the policy|same|above|there)\b", re.I)

# Follow-ups are usually short; longer questions without references start a new topic.
SHORT_FOLLOW_UP_WORDS = 8


@dataclass
class Product:
    doc_id: str
    aliases: list[str]       # lower-case names a customer might use for this product


def _aliases(name: str) -> list[str]:
    """
    Ways a customer may refer to a product: full name, name without filler words,
    digit/word variants ('Click 2 Protect' -> 'click to protect', 'click2protect').
    """
    base = re.sub(r"\(.*?\)", "", name.lower()).strip()
    variants = {base, re.sub(r"\b(plan|policy|insurance|individual|package)\b", "", base).strip()}
    words = base.split()
    if len(words) >= 4:                                         # "click 2 protect supreme plus" -> "click 2 protect"
        variants.add(" ".join(words[:3]))
    if len(words[0]) >= 6 and words[0] not in GENERIC_WORDS:    # "sanchay plus" -> "sanchay"
        variants.add(words[0])
    for v in list(variants):
        variants.add(v.replace(" 2 ", " to "))
        variants.add(v.replace(" ", ""))
    return sorted({re.sub(r"\s+", " ", v) for v in variants if len(v) >= 4}, key=len, reverse=True)


def load_catalog() -> list[Product]:
    """Products known to the system, read from the IDP output."""
    products = []
    for path in sorted(config.PROCESSED_DIR.glob("*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))["document"]
        products.append(Product(doc["doc_id"], _aliases(doc["product_name"])))
    return products


def infer_filters(question: str, catalog: list[Product]) -> dict:
    """Detect product / insurer / product-type mentions in the question."""
    q = question.lower()
    q_compact = q.replace(" ", "")
    doc_ids = [p.doc_id for p in catalog if any(a in q or a.replace(" ", "") in q_compact for a in p.aliases)]
    if doc_ids:
        return {"doc_id": doc_ids}            # a named product is the most specific signal

    found = {}
    companies = [c for c, patterns in COMPANY_HINTS.items() if any(re.search(p, q) for p in patterns)]
    types = [t for t, patterns in TYPE_HINTS.items() if any(re.search(p, q) for p in patterns)]
    if companies:
        found["company"] = companies
    if types:
        found["product_type"] = types
    return found


def resolve_filters(question: str, ui_filters: dict, previous_filters: dict | None,
                    catalog: list[Product]) -> tuple[dict, str]:
    """
    Decide the final metadata filters and explain where they came from.
    Returns (filters, source); source is 'question', 'question_override' (the question named
    products outside the sidebar selection), 'ui', 'conversation' or 'none'.
    """
    ui = {k: v for k, v in (ui_filters or {}).items() if v not in (None, "", "all", [])}
    inferred = infer_filters(question, catalog)

    if inferred.get("doc_id"):
        # Naming a product is the clearest intent, so it wins over sidebar selections
        # (which may exclude that product); the UI tells the user this happened.
        return inferred, "question_override" if ui else "question"
    if ui.get("doc_id"):
        return ui, "ui"
    if inferred:
        return {**inferred, **ui}, "question"       # sidebar choices (e.g. a topic) refine the question
    is_follow_up = FOLLOW_UP.search(question) or len(question.split()) <= SHORT_FOLLOW_UP_WORDS
    if previous_filters and is_follow_up:
        return {**previous_filters, **ui}, "conversation"
    return ui, "ui" if ui else "none"
