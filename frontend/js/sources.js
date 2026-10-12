/**
 * Sources panel: one card per retrieved brochure excerpt.
 * After an answer finishes, the excerpts it cited are listed first; the rest are dimmed.
 */
import { pdfUrl } from "./api.js";
import { $, el, esc } from "./dom.js";
import { renderMarkdown } from "./markdown.js";
import { state } from "./state.js";

const KIND_LABELS = { table: "Table", key_facts: "Key facts", text: "Text" };

function pageLabel(source) {
  if (source.content_type === "key_facts") return "Extracted summary";
  return source.page === source.page_end ? `Page ${source.page}` : `Pages ${source.page}\u2013${source.page_end}`;
}

/**
 * Build one source card.
 * @param {object} source - card data from the server
 * @param {number} answerIndex
 * @param {boolean|undefined} cited - true/false once the answer is complete, undefined while streaming
 */
function sourceCard(source, answerIndex, cited) {
  const stateClass = cited === true ? " cited" : cited === false ? " uncited" : "";
  const card = el("article", `source${stateClass}`);
  card.id = `src-${answerIndex}-${source.n}`;
  card.innerHTML = `
    <div class="source-head">
      <div class="source-n">${source.n}</div>
      <div>
        <div class="source-title">${esc(source.product_name)}</div>
        <div class="source-meta">${esc(source.company)} \u00b7 ${esc(pageLabel(source))}</div>
      </div>
    </div>
    <div class="source-chips">
      <span class="badge" data-type="${esc(source.product_type)}">${esc(state.typeLabels[source.product_type] || source.product_type)}</span>
      <span class="badge soft">${esc(KIND_LABELS[source.content_type] || source.content_type)}</span>
      ${cited === true ? '<span class="badge cited-badge">\u2713 Cited</span>' : ""}
    </div>
    ${source.section ? `<div class="source-section">${esc(source.section)}</div>` : ""}
    <div class="source-body md">${renderMarkdown(source.excerpt)}</div>
    <div class="source-foot">
      <button type="button" class="toggle">Expand</button>
      <a href="${pdfUrl(source.file_name, source.page)}" target="_blank" rel="noopener">Open page ${source.page} \u2197</a>
    </div>`;

  const toggle = card.querySelector(".toggle");
  toggle.addEventListener("click", () => {
    card.classList.toggle("open");
    toggle.textContent = card.classList.contains("open") ? "Collapse" : "Expand";
  });
  return card;
}

/** Hide "Expand" on cards whose excerpt is short enough to show in full. */
function revealShortExcerpts(list) {
  list.querySelectorAll(".source").forEach((card) => {
    const body = card.querySelector(".source-body");
    if (body.scrollHeight <= body.clientHeight + 4) {
      card.classList.add("open");
      card.querySelector(".toggle").hidden = true;
    }
  });
}

/** Render the cards for one answer in the right-hand panel. */
export function showSources(sources, answerIndex) {
  const list = $("#source-list");
  const cited = state.cited[answerIndex];
  const citedCount = cited ? sources.filter((s) => cited.has(s.n)).length : 0;

  $("#sources-sub").textContent = sources.length
    ? `Answer ${answerIndex + 1} \u00b7 ${sources.length} excerpts${cited ? ` \u00b7 ${citedCount} cited` : ""}`
    : "No sources for this answer.";
  if (!sources.length) {
    list.innerHTML = '<div class="empty">No brochure excerpts were used.</div>';
    return;
  }

  const groups = cited && citedCount
    ? [["Cited in the answer", sources.filter((s) => cited.has(s.n)), true],
      ["Also retrieved", sources.filter((s) => !cited.has(s.n)), false]]
    : [["", sources, undefined]];

  list.replaceChildren();
  for (const [label, items, isCited] of groups) {
    if (!items.length) continue;
    if (label) list.append(el("div", "source-group", esc(label)));
    items.forEach((s) => list.append(sourceCard(s, answerIndex, isCited)));
  }
  revealShortExcerpts(list);
}

/** Clicking [n] in an answer shows that answer's sources and highlights card n. */
export function focusCitation(answerIndex, n) {
  const sources = state.answers[answerIndex] || [];
  showSources(sources, answerIndex);

  if (getComputedStyle($("#sources")).display === "none") {
    // Narrow screens hide the sources column - open the PDF page directly instead.
    const source = sources.find((s) => String(s.n) === String(n));
    if (source) window.open(pdfUrl(source.file_name, source.page), "_blank", "noopener");
    return;
  }
  const card = document.getElementById(`src-${answerIndex}-${n}`);
  if (!card) return;
  card.scrollIntoView({ behavior: "smooth", block: "center" });
  card.classList.add("flash", "open");
  card.querySelector(".toggle").textContent = "Collapse";
  setTimeout(() => card.classList.remove("flash"), 1600);
}
