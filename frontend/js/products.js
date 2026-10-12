/**
 * Products tab: catalog cards and the key-facts modal (data from the IDP pipeline).
 */
import { pdfUrl } from "./api.js";
import { NOT_FOUND } from "./constants.js";
import { $, el, esc } from "./dom.js";
import { state } from "./state.js";

const MAX_FACT_CHARS = 70;

/** Shorten a key fact for the small card tiles. */
function shortFact(value) {
  if (!value || value === NOT_FOUND) return "\u2014";
  return value.length > MAX_FACT_CHARS ? `${value.slice(0, MAX_FACT_CHARS - 2)}\u2026` : value;
}

const typeBadge = (p) => `<span class="badge" data-type="${esc(p.product_type)}">${esc(p.product_type_label)}</span>`;

function productCard(product) {
  const facts = product.key_facts || {};
  const summary = facts.plan_summary && facts.plan_summary !== NOT_FOUND
    ? facts.plan_summary : "Key facts not extracted yet - run the IDP pipeline with the LLM step.";
  const card = el("article", "product");
  card.style.setProperty("--type-color", `var(--t-${product.product_type})`);
  card.innerHTML = `
    <div>${typeBadge(product)}</div>
    <div>
      <h3>${esc(product.product_name)}</h3>
      <div class="company">${esc(product.company)}${product.uin ? ` \u00b7 UIN ${esc(product.uin)}` : ""}</div>
    </div>
    <div class="summary">${esc(summary)}</div>
    <dl class="facts-mini">
      <div><dt>Entry age</dt><dd>${esc(shortFact(facts.entry_age))}</dd></div>
      <div><dt>Cover / sum insured</dt><dd>${esc(shortFact(facts.sum_assured_or_insured))}</dd></div>
    </dl>
    <div class="product-actions">
      <button class="btn" data-ask="${esc(product.doc_id)}">Ask about it</button>
      <button class="btn ghost" data-details="${esc(product.doc_id)}">Key facts</button>
    </div>`;
  return card;
}

/** Render the type filter chips and the product grid ("all" or one product type). */
export function renderProducts(type = "all") {
  const types = ["all", ...new Set(state.products.map((p) => p.product_type))];
  $("#type-chips").innerHTML = types.map((t) =>
    `<button class="chip ${t === type ? "active" : ""}" data-type="${esc(t)}">${t === "all" ? "All" : esc(state.typeLabels[t] || t)}</button>`).join("");
  const visible = state.products.filter((p) => type === "all" || p.product_type === type);
  $("#product-grid").replaceChildren(...visible.map(productCard));
}

/** One row of the key-facts table, with its grounding badge. */
function factRow(product, key, label) {
  const value = product.key_facts?.[key];
  if (!value || value === NOT_FOUND || (Array.isArray(value) && !value.length)) return "";
  const shown = Array.isArray(value) ? `<ul>${value.map((v) => `<li>${esc(v)}</li>`).join("")}</ul>` : esc(value);
  const grounded = product.grounded?.[key];
  const badge = grounded === true ? '<span class="check ok">\u2713 verified</span>'
    : grounded === false ? '<span class="check warn" title="A number in this value was not found in the PDF">\u26a0 check</span>' : "";
  return `<tr><th>${esc(label)}${badge}</th><td>${shown}</td></tr>`;
}

/** Open the key-facts modal for a product. */
export function openProductModal(docId) {
  const p = state.productById[docId];
  if (!p) return;
  const rows = Object.entries(state.fieldLabels).map(([key, label]) => factRow(p, key, label)).join("");
  $("#modal-body").innerHTML = `
    ${typeBadge(p)}
    <h2 class="modal-title">${esc(p.product_name)}</h2>
    <div class="muted">${esc(p.company)}</div>
    <div class="meta-line">
      ${p.uin ? `<span class="tag">UIN ${esc(p.uin)}</span>` : ""}
      <span class="tag">${esc(p.doc_type)}</span>
      <span class="tag">${p.page_count} pages</span>
      ${p.pages_used?.length ? `<span class="tag">LLM read pages ${p.pages_used.join(", ")}</span>` : ""}
    </div>
    ${rows ? `<table class="facts-table">${rows}</table>` : '<div class="empty modal-empty">No key facts extracted for this product yet.</div>'}
    <div class="product-actions modal-actions">
      <button class="btn" data-ask="${esc(p.doc_id)}">Ask about this product</button>
      <a class="btn ghost" href="${pdfUrl(p.file_name)}" target="_blank" rel="noopener">Open brochure \u2197</a>
      ${p.source_url ? `<a class="btn ghost" href="${esc(p.source_url)}" target="_blank" rel="noopener">Original source \u2197</a>` : ""}
    </div>`;
  $("#modal").hidden = false;
}

export const closeModal = () => { $("#modal").hidden = true; };
