/**
 * Fixed values shared across the UI.
 */

/** Topic tags produced by the IDP chunker, with display labels. */
export const TOPICS = Object.freeze({
  eligibility: "Eligibility",
  benefits: "Benefits",
  premiums: "Premiums & charges",
  exclusions: "Exclusions",
  waiting_period: "Waiting periods",
  claims: "Claims",
  policy_servicing: "Policy servicing",
  riders: "Riders & add-ons",
  tax: "Tax benefits",
  contact: "Contact & grievance",
});

/** Example questions per persona (sidebar + welcome screen). */
export const SUGGESTIONS = Object.freeze({
  buyer: [
    "What is the entry age and maximum cover age for Click 2 Protect Supreme Plus?",
    "Compare the Travel Ace and Travel Prime Individual plans.",
    "Does Health Guard cover maternity expenses?",
    "What guaranteed income options does Sanchay Plus offer?",
    "What charges apply in the Click 2 Invest ULIP?",
    "What does the Private Car Package Policy cover?",
  ],
  policyholder: [
    "How do I make a cashless claim under Family Health Optima?",
    "What is the free-look period and how do I cancel my policy?",
    "What is the grace period if I miss a premium on Sanchay Plus?",
    "What is the waiting period for pre-existing diseases in Health Guard?",
    "What should I do if my passport is lost under Travel Prime Individual?",
    "Can I surrender my Smart Secure Plus policy?",
  ],
});

/** Why the server chose a search scope (filter_source -> explanation). */
export const SCOPE_REASONS = Object.freeze({
  question: "detected in your question",
  question_override: "detected in your question",
  conversation: "from the conversation",
  ui: "your filters",
  relaxed: "widened search",
  none: "all brochures",
});

/** RAGAS metric keys -> display labels. */
export const RAGAS_LABELS = Object.freeze({
  faithfulness: "Faithfulness",
  answer_relevancy: "Answer relevancy",
  llm_context_precision_with_reference: "Context precision",
  context_recall: "Context recall",
  "factual_correctness(mode=f1)": "Factual correctness",
});

/** Value used by the IDP pipeline when a key fact is absent from a brochure. */
export const NOT_FOUND = "Not mentioned";

/** Health check interval for the status pill. */
export const HEALTH_POLL_MS = 30000;

/** Shield icon used as the assistant's avatar. */
export const BOT_ICON =
  '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 2 4 5v6c0 5 3.4 9.7 8 11 4.6-1.3 8-6 8-11V5l-8-3z"/></svg>';
