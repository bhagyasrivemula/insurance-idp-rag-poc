/**
 * The single, shared application state.
 * Modules read and update it directly; there is no other global data.
 */
export const state = {
  /** "buyer" | "policyholder" - changes the assistant's prompt and suggestions. */
  persona: "buyer",
  /** Explicit filters chosen in the sidebar: {company, product_type, doc_id, topic}. */
  filters: {},
  /** Scope the server used for the previous answer (lets follow-ups keep context). */
  previousFilters: null,
  /** Recent conversation [{role, content}] sent back for follow-up questions. */
  history: [],
  /** Product catalog from /api/products, plus lookup tables. */
  products: [],
  productById: {},
  typeLabels: {},
  fieldLabels: {},
  /** Source cards per answer index, so old citations stay clickable. */
  answers: [],
  /** Citation numbers used in each answer: answer index -> Set<number>. */
  cited: {},
  /** AbortController of the request in flight (null when idle). */
  controller: null,
};

/** Maximum messages kept in `history` (user + assistant turns). */
export const MAX_HISTORY = 8;
