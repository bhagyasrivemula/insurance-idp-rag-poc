/**
 * Sidebar: persona, search-scope filters, context chips and suggested questions.
 */
import { SUGGESTIONS, TOPICS } from "./constants.js";
import { $, $$, esc } from "./dom.js";
import { state } from "./state.js";

const asList = (v) => (Array.isArray(v) ? v : [v]);

/** Turn a filter object into human-readable names, e.g. {doc_id: [...]} -> ["Sanchay Plus"]. */
export function describeFilters(filters) {
  const parts = [];
  if (filters.doc_id) parts.push(...asList(filters.doc_id).map((id) => state.productById[id]?.product_name || id));
  if (filters.company) parts.push(...asList(filters.company));
  if (filters.product_type) parts.push(...asList(filters.product_type).map((t) => state.typeLabels[t] || t));
  if (filters.topic) parts.push(TOPICS[filters.topic] || filters.topic);
  return parts;
}

/** Fill a <select> with an "All" option plus [value, label] pairs. */
function fillSelect(select, allLabel, options, selected) {
  const items = options.map(([value, label]) =>
    `<option value="${esc(value)}" ${value === selected ? "selected" : ""}>${esc(label)}</option>`);
  select.innerHTML = `<option value="">${esc(allLabel)}</option>${items.join("")}`;
}

/** Product dropdown only lists products matching the chosen insurer / type. */
function refreshProductSelect() {
  const { company, product_type: type, doc_id: docId } = state.filters;
  const visible = state.products.filter((p) => (!company || p.company === company) && (!type || p.product_type === type));
  fillSelect($("#f-product"), "All products", visible.map((p) => [p.doc_id, `${p.product_name} (${p.company})`]), docId);
}

/** (Re)build every filter dropdown - sidebar and retrieval explorer - from the catalog. */
export function buildFilterControls() {
  const companies = [...new Set(state.products.map((p) => p.company))].sort().map((c) => [c, c]);
  const types = [...new Set(state.products.map((p) => p.product_type))].map((t) => [t, state.typeLabels[t] || t]);
  const topics = Object.entries(TOPICS);

  fillSelect($("#f-company"), "All insurers", companies, state.filters.company);
  fillSelect($("#f-type"), "All product types", types, state.filters.product_type);
  fillSelect($("#f-topic"), "All topics", topics, state.filters.topic);
  refreshProductSelect();

  fillSelect($("#x-company"), "All insurers", companies);
  fillSelect($("#x-type"), "All types", types);
  fillSelect($("#x-topic"), "All topics", topics);
}

/** Set or clear one sidebar filter. */
export function setFilter(key, value) {
  if (value) state.filters[key] = value;
  else delete state.filters[key];

  if (key === "company" || key === "product_type") {
    // A different insurer/type may rule out the chosen product.
    const product = state.productById[state.filters.doc_id];
    const conflicts = product && ((state.filters.company && product.company !== state.filters.company) ||
      (state.filters.product_type && product.product_type !== state.filters.product_type));
    if (conflicts) delete state.filters.doc_id;
    refreshProductSelect();
  }
  renderContextBar();
}

/** Clear all filters and the conversation scope. */
export function resetFilters() {
  state.filters = {};
  state.previousFilters = null;
  buildFilterControls();
  renderContextBar();
}

/** Scope one product (used by "Ask about it" on product cards). */
export function scopeToProduct(docId) {
  state.filters = { doc_id: docId };
  buildFilterControls();
  renderContextBar();
}

/** Chips above the input showing what scope the next question will use. */
export function renderContextBar() {
  const bar = $("#context-bar");
  const chip = (label, clearKey, cls) =>
    `<span class="tag ${cls}">${esc(label)}<button type="button" data-clear="${clearKey}" title="Remove">&times;</button></span>`;

  const filterChips = Object.entries(state.filters).map(([key, value]) => chip(describeFilters({ [key]: value })[0], key, "scope"));
  if (filterChips.length) {
    bar.innerHTML = `<span>Searching only in</span>${filterChips.join("")}`;
  } else if (state.previousFilters && Object.keys(state.previousFilters).length) {
    bar.innerHTML = `<span>Follow-ups continue with</span>${chip(describeFilters(state.previousFilters).join(", "), "__previous", "")}`;
  } else {
    bar.innerHTML = "";
  }
  bar.hidden = !bar.innerHTML;
}

/** Switch persona and refresh the suggested questions. */
export function setPersona(persona) {
  state.persona = persona;
  $$(".seg").forEach((b) => b.classList.toggle("active", b.dataset.persona === persona));
  renderSuggestions();
}

/** Suggested questions: sidebar list for the persona + four mixed cards on the welcome screen. */
export function renderSuggestions() {
  $("#suggestions").innerHTML = SUGGESTIONS[state.persona]
    .map((q) => `<button class="suggestion" data-q="${esc(q)}">${esc(q)}</button>`).join("");

  const welcome = $("#welcome-cards");
  if (!welcome) return;                         // welcome screen is gone once the chat starts
  const cards = [["Buying", SUGGESTIONS.buyer[0]], ["Comparing", SUGGESTIONS.buyer[1]],
    ["Claims", SUGGESTIONS.policyholder[0]], ["Coverage", SUGGESTIONS.buyer[2]]];
  welcome.innerHTML = cards.map(([tag, q]) =>
    `<button class="welcome-card" data-q="${esc(q)}"><div class="wc-tag">${esc(tag)}</div><div class="wc-q">${esc(q)}</div></button>`).join("");
}
