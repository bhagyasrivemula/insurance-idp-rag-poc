"""
Retrieval quality check (no LLM needed, runs in seconds).

For each test question we know which brochure holds the answer and a phrase
that must appear in the retrieved text. We measure:

    product hit  - the right brochure is among the top-K excerpts
    answer hit   - the expected phrase is inside the top-K excerpts
    scope        - which filters were inferred from the question

Run:  python -m app.evaluate
"""
from __future__ import annotations

import time

from app import config, retriever, scope

# (question, persona, expected doc_id fragment, phrase expected in retrieved text (lower-case))
TEST_SET = [
    ("What is the grace period for Sanchay Plus premiums?", "policyholder", "sanchay", "grace period"),
    ("What is the minimum entry age for Sanchay Plus?", "buyer", "sanchay", "301 days"),
    ("Does Health Guard cover maternity expenses?", "buyer", "health_guard", "maternity"),
    ("Waiting period for pre-existing diseases in Health Guard", "policyholder", "health_guard", "pre-existing"),
    ("What is the free look period for Click 2 Protect Supreme Plus?", "policyholder", "click2protect", "free look"),
    ("Which riders can I add to Click 2 Protect Supreme Plus?", "buyer", "click2protect", "rider"),
    ("What charges apply in Click 2 Invest?", "buyer", "click2invest", "charge"),
    ("What funds can I invest in with the Click 2 Invest ULIP?", "buyer", "click2invest", "fund"),
    ("Is there an accident cover in Smart Secure Plus?", "buyer", "smart_secure", "accident"),
    ("How do I get cashless treatment under Family Health Optima?", "policyholder", "family_health_optima", "cashless"),
    ("What is the sum insured available in Family Health Optima?", "buyer", "family_health_optima", "sum insured"),
    ("What does the private car package policy cover?", "buyer", "private_car", "damage"),
    ("Is loss of passport covered in Travel Prime Individual?", "policyholder", "travel_prime", "passport"),
    ("Does Travel Ace cover trip cancellation?", "buyer", "travel_ace", "cancel"),
    ("What is the maximum age for Travel Ace Super Age plan?", "buyer", "travel_ace", "super age"),
    ("Which car insurance covers third party liability?", "buyer", "private_car", "third part"),  # matches "third party" and "Third Parties"
    ("I want a term plan, what is the death benefit?", "buyer", "", "death benefit"),
    ("Which health plans have a no claim bonus?", "buyer", "", "bonus"),
]


def run() -> None:
    catalog = scope.load_catalog()
    retriever.bm25()  # build the keyword index before timing
    product_hits = answer_hits = 0
    started = time.perf_counter()

    print(f"{'#':>2}  {'product':7} {'answer':6}  question  ->  scope")
    for i, (question, persona, doc_fragment, phrase) in enumerate(TEST_SET, 1):
        filters, source = scope.resolve_filters(question, {}, None, catalog)
        hits, _ = retriever.search(question, filters, persona, top_k=config.TOP_K)
        product_ok = not doc_fragment or any(doc_fragment in h["metadata"]["doc_id"] for h in hits)
        answer_ok = any(phrase in h["text"].lower() for h in hits)
        product_hits += product_ok
        answer_hits += answer_ok
        scope = ", ".join(f"{k}={v}" for k, v in filters.items()) or "all"
        print(f"{i:>2}  {'OK' if product_ok else 'MISS':7} {'OK' if answer_ok else 'MISS':6}  {question}  ->  {scope}")

    n = len(TEST_SET)
    elapsed = (time.perf_counter() - started) / n * 1000
    print(f"\nProduct hit rate @ top-{config.TOP_K}: {product_hits}/{n} ({product_hits / n:.0%})")
    print(f"Answer  hit rate @ top-{config.TOP_K}: {answer_hits}/{n} ({answer_hits / n:.0%})")
    print(f"Average retrieval time: {elapsed:.0f} ms per question")


if __name__ == "__main__":
    run()
