"""
What the IDP key-fact stage extracts, and how it asks for it.

FIELD_GROUPS - one LLM call per group, each with its own page selection:
    fields  : name -> (kind "str" | "list", guidance shown to the model)
    signals : keywords that make a page relevant for this group
    budget  : max characters of brochure text sent (~4 characters per token)
FIELD_LABELS - every field in display order, with its UI label.
SYSTEM_PROMPT - instructions for the extraction model.
"""
from __future__ import annotations

NOT_FOUND = "Not mentioned"

# --------------------------------------------------------------------------- #
# Field groups. Each group = one LLM call with its own page selection.
#   fields  : name -> (kind, guidance shown to the model)
#   signals : keywords that make a page relevant for this group
#   budget  : max characters of brochure text sent (~4 chars per token)
# --------------------------------------------------------------------------- #
FIELD_GROUPS = {
    "overview": {
        "fields": {
            "plan_summary": ("str", "2 sentences: what kind of plan this is and its main purpose. Do not just repeat the name."),
            "target_customer": ("str", "Who the plan is designed for (e.g. families, salaried individuals, frequent travellers)."),
            "key_benefits": ("list", "Up to 6 main benefits or features, each a short phrase."),
            "optional_riders_or_addons": ("list", "Names of optional riders / add-on covers explicitly listed. Empty list if none."),
            "premium_payment_modes": ("str", "Allowed premium payment frequencies or options (e.g. single, annual, monthly)."),
        },
        "signals": ["key features", "highlights", "benefit", "why choose", "rider", "add-on", "optional cover",
                    "plan option", "variant", "about the plan", "single pay", "frequency"],
        "budget": 32000,
    },
    "eligibility": {
        "fields": {
            "entry_age": ("str", "Minimum and maximum age at entry exactly as written (keep units like 'days'). "
                                 "If ages differ by plan option/variant, give each option briefly, e.g. "
                                 "'Option A: 301 days - 65 years; Option B: 50 - 65 years'. Read every row of the table."),
            "maturity_age": ("str", "Maximum age at maturity / age until which cover lasts (per option if different)."),
            "policy_term": ("str", "Policy term range or options in years (per option if different)."),
            "premium_payment_term": ("str", "Premium payment term options (e.g. single pay, 5-12 years)."),
            "sum_assured_or_insured": ("str", "Minimum and maximum sum assured / sum insured / cover amount, or the plan "
                                              "options with their amounts."),
        },
        "signals": ["eligibility", "age at entry", "entry age", "minimum", "maximum", "policy term",
                    "premium payment term", "sum assured", "sum insured", "maturity age", "age at maturity"],
        "budget": 28000,
    },
    "terms": {
        "fields": {
            "waiting_periods": ("str", "Waiting periods explicitly stated (initial, pre-existing disease, specific illness). "
                                       f"'{NOT_FOUND}' if the brochure has none."),
            "free_look_period": ("str", "Free-look / cancellation period after receiving the policy."),
            "grace_period": ("str", "Grace period for paying premiums or renewal."),
            "claim_process": ("str", "1-2 sentences on how to make a claim (cashless / reimbursement / contact). "
                                     f"'{NOT_FOUND}' if the steps are not described."),
            "tax_benefits": ("str", "Tax benefits mentioned (sections of Income Tax Act)."),
            "major_exclusions": ("list", "Up to 6 important exclusions explicitly stated in the text."),
        },
        "signals": ["exclusion", "not covered", "waiting period", "free look", "free-look", "grace period", "claim",
                    "tax", "suicide", "cancellation", "pre-existing", "cashless"],
        "budget": 32000,
    },
}

# Flat list of every field (in display order) and their labels for the UI.
FIELD_LABELS = {
    "plan_summary": "Plan summary",
    "target_customer": "Who it is for",
    "entry_age": "Entry age",
    "maturity_age": "Maturity / cover-till age",
    "policy_term": "Policy term",
    "premium_payment_term": "Premium payment term",
    "sum_assured_or_insured": "Sum assured / sum insured",
    "premium_payment_modes": "Premium payment modes",
    "waiting_periods": "Waiting periods",
    "free_look_period": "Free-look period",
    "grace_period": "Grace period",
    "claim_process": "Claim process",
    "tax_benefits": "Tax benefits",
    "key_benefits": "Key benefits",
    "optional_riders_or_addons": "Optional riders / add-ons",
    "major_exclusions": "Major exclusions",
}

SYSTEM_PROMPT = (
    "You are a meticulous insurance document analyst. Extract facts ONLY from the brochure text provided. "
    "Copy numbers, ages, amounts and periods exactly as written - including units such as days, months or years. "
    "Read tables carefully: 'Minimum' and 'Maximum' columns give ranges. "
    f"If a field is not stated in the text, answer exactly '{NOT_FOUND}' (or an empty list). Never guess or "
    "use general knowledge about insurance."
)
