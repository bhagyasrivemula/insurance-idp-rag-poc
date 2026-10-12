"""
IDP Stage 3 - Key data extraction with an LLM + grounding check.

Goal: turn a 30-page brochure into a structured product card
(entry age, policy term, sum assured range, key benefits, exclusions, ...).

How it works:
    1. Three focused passes. Extraction is split into field groups
       (overview / eligibility / terms & conditions); each group gets the
       pages most likely to contain its answers (keyword scoring), which keeps
       the model focused and the cost low.
    2. Structured output. OpenAI structured outputs force the reply to match
       a JSON schema, so there is no fragile free-text parsing.
    3. Grounding check. Every value is compared with the brochure text:
       its numbers must appear in the source and most of its words must too.
       Values that fail are flagged "check" in the UI instead of being trusted.
"""
from __future__ import annotations

import re

from app import config, llm_client
from app.idp.document_loader import DocumentInfo

from app.idp.key_fact_fields import FIELD_GROUPS, FIELD_LABELS, NOT_FOUND, SYSTEM_PROMPT


# --------------------------------------------------------------------------- #
# Page selection
# --------------------------------------------------------------------------- #
def select_pages(pages: list[str], signals: list[str], budget: int, always_first: bool) -> list[int]:
    """Rank pages by keyword density and pack the best ones into the character budget."""
    def score(text: str) -> float:
        lowered = text.lower()
        return sum(lowered.count(k) for k in signals) / (1 + len(text) / 3000)

    chosen, used = [], 0
    if always_first and pages:
        chosen, used = [0], min(len(pages[0]), budget // 3)
    for idx in sorted(range(len(pages)), key=lambda i: score(pages[i]), reverse=True):
        if idx in chosen or score(pages[idx]) == 0:
            continue
        if used + len(pages[idx]) > budget:
            continue
        chosen.append(idx)
        used += len(pages[idx])
    return sorted(chosen)


def _context(pages: list[str], chosen: list[int], budget: int) -> str:
    return "\n\n".join(f"[Page {i + 1}]\n{pages[i]}" for i in chosen)[:budget]


# --------------------------------------------------------------------------- #
# Grounding
# --------------------------------------------------------------------------- #
_WORD = re.compile(r"[a-z]{4,}")
_GENERIC = {"years", "year", "months", "days", "maximum", "minimum", "with", "from", "that", "this", "plan",
            "policy", "option", "options", "available", "cover", "benefit", "benefits", "mentioned"}


def _numbers(text: str) -> set[str]:
    """Numbers inside a value, normalised: '1,00,000' -> '100000', '25.0' -> '25'."""
    out = set()
    for n in re.findall(r"\d[\d,]*(?:\.\d+)?", text):
        n = n.replace(",", "")
        out.add(n[:-2] if n.endswith(".0") else n)
    return out


def grounding_check(facts: dict, full_text: str) -> dict[str, bool]:
    """
    A value is 'grounded' when
        * every number in it appears in the brochure, and
        * at least 60% of its meaningful words appear in the brochure.
    Fields with no value are not checked.
    """
    source_numbers = _numbers(full_text)
    source_words = set(_WORD.findall(full_text.lower()))
    result = {}
    for name, value in facts.items():
        text = " ".join(value) if isinstance(value, list) else str(value)
        if not text or text == NOT_FOUND:
            continue
        numbers_ok = _numbers(text) <= source_numbers
        words = [w for w in _WORD.findall(text.lower()) if w not in _GENERIC]
        words_ok = not words or sum(w in source_words for w in words) / len(words) >= 0.6
        result[name] = numbers_ok and words_ok
    return result


# --------------------------------------------------------------------------- #
# Extraction
# --------------------------------------------------------------------------- #
_EMPTY = {"", "n/a", "na", "none", "not mentioned", "not stated", "unknown", "not specified", "not available"}


def _dedupe(items: list[str]) -> list[str]:
    """Drop repeated list items, including near-duplicates where one item contains the other."""
    kept: list[str] = []
    for item in items:
        low = item.lower()
        if any(low in k.lower() or k.lower() in low for k in kept):
            continue
        kept.append(item)
    return kept


def _clean(raw: dict, fields: dict) -> dict:
    """Normalise model output: trim strings, drop empty list items, unify 'not found' values."""
    def tidy(v) -> str:
        return str(v or "").replace("\u20b9", "Rs. ").replace("Rs.  ", "Rs. ").strip()

    cleaned = {}
    for name, (kind, _) in fields.items():
        value = raw.get(name)
        if kind == "list":
            items = [tidy(i) for i in (value if isinstance(value, list) else []) if tidy(i).lower() not in _EMPTY]
            cleaned[name] = _dedupe(items)[:6]
        else:
            text = tidy(value)
            cleaned[name] = NOT_FOUND if text.lower().rstrip(".") in _EMPTY else text
    return cleaned


def _extract_group(doc: DocumentInfo, pages: list[str], group_name: str) -> tuple[dict, list[int]]:
    group = FIELD_GROUPS[group_name]
    fields = group["fields"]
    chosen = select_pages(pages, group["signals"], group["budget"], always_first=(group_name == "overview"))
    schema = {
        "type": "object",
        "properties": {name: ({"type": "array", "items": {"type": "string"}} if kind == "list" else {"type": "string"})
                       for name, (kind, _) in fields.items()},
        "required": list(fields),
    }
    guide = "\n".join(f"- {name}: {hint}" for name, (_, hint) in fields.items())
    prompt = (
        f"Insurer: {doc.company}\nProduct: {doc.product_name} ({doc.product_type_label})\n\n"
        f"Brochure text:\n\"\"\"\n{_context(pages, chosen, group['budget'])}\n\"\"\"\n\n"
        f"Extract these fields as JSON:\n{guide}"
    )
    raw = llm_client.generate_json(prompt, schema, system=SYSTEM_PROMPT)
    return _clean(raw, fields), chosen


def extract_key_facts(doc: DocumentInfo, pages: list[str]) -> dict:
    """Run all field groups, merge them, and verify the result against the brochure text."""
    facts: dict = {}
    pages_used: set[int] = set()
    for group_name in FIELD_GROUPS:
        group_facts, chosen = _extract_group(doc, pages, group_name)
        facts.update(group_facts)
        pages_used.update(chosen)
    ordered = {name: facts.get(name, NOT_FOUND) for name in FIELD_LABELS}
    return {
        "facts": ordered,
        "grounded": grounding_check(ordered, " ".join(pages)),
        "pages_used": sorted(i + 1 for i in pages_used),
        "model": config.EXTRACT_MODEL,   # lets the pipeline re-extract when the model changes
    }


def facts_to_text(doc: DocumentInfo, key_facts: dict) -> str:
    """
    Render extracted facts as readable text (indexed as the product-summary chunk).
    Values that failed the grounding check are left out, so the chatbot never
    reads an unverified number - it falls back to the original brochure chunks.
    """
    facts, grounded = key_facts["facts"], key_facts.get("grounded", {})
    lines = [f"{doc.product_name} by {doc.company} ({doc.product_type_label})."]
    if doc.uin:
        lines.append(f"UIN: {doc.uin}")
    for name, label in FIELD_LABELS.items():
        value = facts.get(name)
        if not value or value == NOT_FOUND or grounded.get(name) is False:
            continue
        lines.append(f"{label}: " + ("; ".join(value) if isinstance(value, list) else value))
    return "\n".join(lines)
