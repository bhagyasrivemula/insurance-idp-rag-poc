/**
 * InsureAssist - entry point.
 * Loads the catalog, wires user interactions and starts the app.
 */
import { fetchProducts } from "./api.js";
import { ask, stopAnswer } from "./chat.js";
import { HEALTH_POLL_MS } from "./constants.js";
import { $, $$ } from "./dom.js";
import { buildFilterControls, renderContextBar, renderSuggestions, resetFilters, scopeToProduct,
  setFilter, setPersona } from "./filters.js";
import { loadKnowledgeBase, runExplorer } from "./knowledge.js";
import { closeModal, openProductModal, renderProducts } from "./products.js";
import { focusCitation } from "./sources.js";
import { state } from "./state.js";
import { checkHealth } from "./status.js";
import { initTheme } from "./theme.js";
import { currentHashView, onFirstEnter, switchView } from "./views.js";

/** Fetch the product catalog and build everything that depends on it. */
async function loadProducts() {
  const data = await fetchProducts();
  state.products = data.products;
  state.typeLabels = data.type_labels;
  state.fieldLabels = data.field_labels;
  state.productById = Object.fromEntries(data.products.map((p) => [p.doc_id, p]));
  buildFilterControls();
  renderProducts();
}

/** "Ask about it" on a product: scope the chat to that product and pre-fill a question. */
function askAboutProduct(docId) {
  closeModal();
  scopeToProduct(docId);
  switchView("assistant");
  const input = $("#input");
  input.value = `Tell me about ${state.productById[docId]?.product_name ?? "this product"}`;
  input.focus();
}

/** Composer: Enter sends, Shift+Enter adds a line, the textarea grows with its content. */
function wireComposer() {
  const input = $("#input");
  const autosize = () => { input.style.height = "auto"; input.style.height = `${input.scrollHeight}px`; };
  input.addEventListener("input", autosize);
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      $("#composer").requestSubmit();
    }
  });
  $("#composer").addEventListener("submit", (e) => {
    e.preventDefault();
    const question = input.value;
    input.value = "";
    autosize();
    ask(question);
  });
  $("#stop").addEventListener("click", stopAnswer);
}

/** Sidebar persona buttons and filter dropdowns. */
function wireSidebar() {
  $$(".seg").forEach((b) => b.addEventListener("click", () => setPersona(b.dataset.persona)));
  const selects = { "#f-company": "company", "#f-type": "product_type", "#f-product": "doc_id", "#f-topic": "topic" };
  Object.entries(selects).forEach(([selector, key]) =>
    $(selector).addEventListener("change", (e) => setFilter(key, e.target.value)));
  $("#reset-filters").addEventListener("click", resetFilters);
}

/** One delegated click handler for content that is created dynamically. */
function onDocumentClick(e) {
  const target = e.target.closest("button, .modal");
  if (!target) return;
  const { dataset } = target;

  if (dataset.q) ask(dataset.q);                                          // suggestion / welcome card
  else if (target.classList.contains("cite")) focusCitation(Number(target.closest(".answer").dataset.answer), dataset.n);
  else if (dataset.clear === "__previous") { state.previousFilters = null; renderContextBar(); }
  else if (dataset.clear) { setFilter(dataset.clear, ""); buildFilterControls(); }
  else if (dataset.ask) askAboutProduct(dataset.ask);
  else if (dataset.details) openProductModal(dataset.details);
  else if (dataset.type && target.classList.contains("chip")) renderProducts(dataset.type);
  else if (target.id === "modal-close" || (target.id === "modal" && e.target === target)) closeModal();
}

/** Tabs, logo, browser back/forward. */
function wireNavigation() {
  $$(".tab").forEach((t) => t.addEventListener("click", () => switchView(t.dataset.view)));
  $(".brand").addEventListener("click", (e) => {
    e.preventDefault();
    switchView("assistant");
    $("#input").focus();
  });
  window.addEventListener("hashchange", () => switchView(currentHashView()));
  onFirstEnter("knowledge", () => loadKnowledgeBase().catch(console.error));
}

function init() {
  $("#copyright-year").textContent = String(new Date().getFullYear());
  initTheme();
  wireNavigation();
  wireSidebar();
  wireComposer();
  document.addEventListener("click", onDocumentClick);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeModal(); });
  $("#explore-form").addEventListener("submit", runExplorer);

  renderSuggestions();
  switchView(currentHashView());
  checkHealth();
  setInterval(checkHealth, HEALTH_POLL_MS);
  loadProducts().catch((err) => console.error("Could not load products", err));
}

init();
