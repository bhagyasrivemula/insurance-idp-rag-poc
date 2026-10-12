"""
Guardrails: checks that run before and after the language model.

INPUT (before anything reaches the model)
    1. PII masking       - Aadhaar, PAN, phone, e-mail and card numbers are replaced
                           with placeholders such as [PHONE]; the model never sees them.
    2. Prompt injection  - attempts to override the assistant's instructions are blocked.
    3. Moderation        - OpenAI's free moderation model blocks harmful content.
    4. Off-topic         - decided after retrieval: if nothing in the brochures is even
                           remotely similar and the question has no insurance words,
                           the assistant declines politely without calling the LLM.

OUTPUT (after the answer has been generated)
    5. Number grounding  - every figure in the answer must appear in the retrieved excerpts.
    6. Citations         - a substantive answer must cite at least one excerpt.
    7. No promises       - phrases that promise claim approval or give buy/sell advice
                           are flagged, and a disclaimer is shown.

Each check returns a small dict ({"check", "status": pass|warn|block, "detail"})
that the API sends to the UI and LangSmith records in the trace.
"""
from __future__ import annotations

import re

from langsmith import traceable

from app import config, llm_client

# --------------------------------------------------------------------------- #
# 1. PII
# --------------------------------------------------------------------------- #
PII_PATTERNS = [
    # (label, pattern) - order matters: card numbers before generic long digit runs
    ("CARD", re.compile(r"\b(?:\d[ -]?){13,19}\b")),
    ("AADHAAR", re.compile(r"\b[2-9]\d{3}[ -]?\d{4}[ -]?\d{4}\b")),
    ("PAN", re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b")),
    ("EMAIL", re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")),
    ("PHONE", re.compile(r"(?<!\d)(?:\+?91[ -]?)?[6-9]\d{9}(?!\d)")),
]


def _luhn_ok(digits: str) -> bool:
    """Card numbers pass the Luhn checksum; random long numbers usually do not."""
    total, double = 0, False
    for d in reversed(digits):
        n = int(d) * (2 if double else 1)
        total += n - 9 if n > 9 else n
        double = not double
    return total % 10 == 0


def mask_pii(text: str) -> tuple[str, list[str]]:
    """Replace personal data with placeholders. Returns (masked_text, labels_found)."""
    found = []
    for label, pattern in PII_PATTERNS:
        def repl(m, label=label):
            if label == "CARD" and not _luhn_ok(re.sub(r"\D", "", m.group())):
                return m.group()
            found.append(label)
            return f"[{label}]"
        text = pattern.sub(repl, text)
    return text, sorted(set(found))


# --------------------------------------------------------------------------- #
# 2. Prompt injection
# --------------------------------------------------------------------------- #
INJECTION_PATTERNS = re.compile(
    r"ignore (all |any |the )?(previous|prior|above|earlier) (instructions|rules|prompts?)"
    r"|disregard (your|the|all) (instructions|rules|guidelines)"
    r"|(reveal|show|print|repeat) (your|the) (system )?(prompt|instructions)"
    r"|system prompt|developer mode|jailbreak|\bDAN\b"
    r"|you are now (a|an|no longer)|pretend (to be|you are)|act as (a|an) (?!policyholder|buyer)",
    re.I,
)

# --------------------------------------------------------------------------- #
# 4. Off-topic
# --------------------------------------------------------------------------- #
INSURANCE_WORDS = re.compile(
    r"insur|policy|policies|premium|claim|cover|plan|benefit|rider|sum (assured|insured)|maturity|"
    r"nominee|hospital|health|life|term|travel|motor|car|ulip|fund|tax|exclusion|waiting|grace|"
    r"free.?look|surrender|renew|cashless|deductible|co-?pay|death|accident|maternity|premium",
    re.I,
)

# --------------------------------------------------------------------------- #
# 7. Promises / advice
# --------------------------------------------------------------------------- #
PROMISE_PATTERNS = re.compile(
    r"(claim|it) (will|would) (definitely|certainly|surely) be (approved|paid|accepted)"
    r"|guarantee(d|s)? (that )?(your )?claim"
    r"|you (should|must) (definitely )?(buy|purchase|invest in)"
    r"|i (would )?recommend (buying|purchasing|that you buy)",
    re.I,
)

ADVICE_DISCLAIMER = ("This is general information from the brochures, not personal advice. Claim decisions "
                     "are made by the insurer under the policy wording.")


def _result(check: str, status: str, detail: str) -> dict:
    return {"check": check, "status": status, "detail": detail}


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #
@traceable(run_type="tool", name="Guardrails: input")
def check_input(question: str) -> dict:
    """
    Run input guardrails. Returns
        {"question": masked question to use from now on,
         "blocked": bool, "message": reply to show if blocked,
         "checks": [ {check, status, detail}, ... ]}
    """
    checks = []
    masked, pii = mask_pii(question)
    checks.append(_result("PII masking", "warn" if pii else "pass",
                          f"Removed before processing: {', '.join(pii)}" if pii else "No personal data found"))

    if INJECTION_PATTERNS.search(masked):
        checks.append(_result("Prompt injection", "block", "Attempt to override the assistant's instructions"))
        return {"question": masked, "blocked": True, "checks": checks,
                "message": "I can only help with questions about the insurance products in my library. "
                           "I can't change how I work or reveal my instructions."}
    checks.append(_result("Prompt injection", "pass", "No override attempt detected"))

    if config.USE_MODERATION:
        mod = llm_client.moderate(masked)
        if mod["flagged"]:
            checks.append(_result("Content safety", "block", "Flagged: " + ", ".join(mod["categories"])))
            return {"question": masked, "blocked": True, "checks": checks,
                    "message": "I can't help with that. I'm here to answer questions about insurance products."}
        checks.append(_result("Content safety", "pass",
                              "Moderation unavailable - skipped" if mod.get("error") else "OpenAI moderation passed"))

    return {"question": masked, "blocked": False, "checks": checks, "message": ""}


def check_topic(question: str, best_similarity: float | None) -> dict:
    """Off-topic check, using the best semantic-search similarity from retrieval."""
    on_topic_words = bool(INSURANCE_WORDS.search(question))
    if best_similarity is not None and best_similarity < config.OFF_TOPIC_SIMILARITY and not on_topic_words:
        return _result("Topic", "block", f"Unrelated to the brochures (best match {best_similarity:.2f})")
    detail = f"Best brochure match {best_similarity:.2f}" if best_similarity is not None else "Insurance question"
    return _result("Topic", "pass", detail)


OFF_TOPIC_MESSAGE = ("That doesn't seem to be about the insurance products I know. I can answer questions about "
                     "eligibility, benefits, premiums, exclusions, waiting periods, claims and servicing for the "
                     "plans in my library.")


def _numbers(text: str) -> set[str]:
    """Figures in a text, normalised: '1,00,000' -> '100000', '30.0' -> '30'."""
    out = set()
    for n in re.findall(r"\d[\d,]*(?:\.\d+)?", text):
        n = n.replace(",", "")
        out.add(n[:-2] if n.endswith(".0") else n)
    return out


@traceable(run_type="tool", name="Guardrails: output")
def check_output(answer: str, contexts: list[str]) -> list[dict]:
    """Run output guardrails on the finished answer."""
    checks = []
    body = re.sub(r"\[\d+(?:\s*,\s*\d+)*\]", "", answer)            # citation markers are not facts

    # 5. Every figure in the answer must exist in the excerpts
    answer_numbers = _numbers(body)
    source_numbers = _numbers(" ".join(contexts))
    missing = sorted(answer_numbers - source_numbers, key=len, reverse=True)
    if not answer_numbers:
        checks.append(_result("Grounded figures", "pass", "No figures to verify"))
    elif missing:
        checks.append(_result("Grounded figures", "warn",
                              f"{len(missing)} of {len(answer_numbers)} figures not found in sources: {', '.join(missing[:5])}"))
    else:
        checks.append(_result("Grounded figures", "pass", f"All {len(answer_numbers)} figures found in sources"))

    # 6. Citations
    substantive = len(body.split()) > 25
    cited = bool(re.search(r"\[\d+", answer))
    if substantive and not cited:
        checks.append(_result("Citations", "warn", "Answer does not cite any brochure excerpt"))
    else:
        checks.append(_result("Citations", "pass", "Cites its sources" if cited else "Short answer"))

    # 7. Promises / advice
    if PROMISE_PATTERNS.search(body):
        checks.append(_result("No promises or advice", "warn", ADVICE_DISCLAIMER))
    else:
        checks.append(_result("No promises or advice", "pass", "No claim promises or buy recommendations"))
    return checks
