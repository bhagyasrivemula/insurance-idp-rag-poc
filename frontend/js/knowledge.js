/**
 * Knowledge base tab: IDP statistics, documents table, topic distribution
 * and the retrieval explorer (semantic / keyword / hybrid search with filters).
 */
import { fetchPipeline, searchChunks } from "./api.js";
import { TOPICS } from "./constants.js";
import { $, applyBarWidths, el, esc } from "./dom.js";
import { loadEvaluation } from "./evaluation.js";
import { state } from "./state.js";

const topicLabel = (t) => TOPICS[t] || t.charAt(0).toUpperCase() + t.slice(1);

function renderStats(totals) {
  const stats = [
    [totals.documents, "Brochures processed"], [totals.companies, "Insurers"], [totals.pages, "Pages read"],
    [totals.tables, "Tables extracted"], [totals.chunks, "Chunks indexed"],
    [totals.furniture_removed, "Header/footer lines removed"],
  ];
  $("#stat-row").innerHTML = stats.map(([value, label]) =>
    `<div class="stat"><div class="v">${value.toLocaleString()}</div><div class="l">${esc(label)}</div></div>`).join("");
}

function renderDocuments(documents) {
  const rows = documents.map((d) => `
    <tr>
      <td><strong>${esc(d.product_name)}</strong><div class="muted small">${esc(d.company)}</div></td>
      <td>${esc(d.product_type_label)}</td><td>${esc(d.doc_type)}</td><td class="small">${esc(d.uin)}</td>
      <td class="num">${d.pages}</td><td class="num">${d.tables}</td>
      <td class="num">${d.chunks}<div class="muted small">${d.table_chunks} table</div></td>
      <td>${d.key_facts ? `<span class="check ok">\u2713 ${d.verified_fields}/${d.checked_fields} verified</span>` : '<span class="muted">\u2014</span>'}</td>
    </tr>`).join("");
  $("#doc-table").innerHTML = `
    <thead><tr><th>Product</th><th>Type</th><th>Doc</th><th>UIN</th><th>Pages</th><th>Tables</th><th>Chunks</th><th>Key facts</th></tr></thead>
    <tbody>${rows}</tbody>`;
}

function renderTopics(topics) {
  const box = $("#topic-bars");
  const max = Math.max(...Object.values(topics), 1);
  box.innerHTML = Object.entries(topics).map(([topic, n]) => `
    <div class="bar-row"><span>${esc(topicLabel(topic))}</span>
      <div class="bar-track"><div class="bar-fill" data-width="${(n / max) * 100}"></div></div><span class="n">${n}</span></div>`).join("");
  applyBarWidths(box);
}

/** Load everything shown in the Knowledge base tab. */
export async function loadKnowledgeBase() {
  const data = await fetchPipeline();
  renderStats(data.totals);
  renderDocuments(data.documents);
  renderTopics(data.topics);
  await loadEvaluation();
}

function hitCard(r) {
  const dash = "\u2014";
  return el("div", "x-hit", `
    <div class="x-hit-head">
      <strong>#${r.n}</strong>
      <span class="badge" data-type="${esc(r.product_type)}">${esc(state.typeLabels[r.product_type] || r.product_type)}</span>
      <span>${esc(r.product_name)}</span><span class="muted">p.${r.page} \u00b7 ${esc(r.section)}</span>
      <span class="tag">${esc(r.content_type)}</span><span class="tag">topic: ${esc(r.topic)}</span>
      <span class="score">similarity ${r.similarity ?? dash} \u00b7 semantic #${r.vector_rank ?? dash} \u00b7 keyword #${r.keyword_rank ?? dash} \u00b7 fused ${r.score}</span>
    </div>
    <div class="x-hit-text">${esc(r.excerpt)}</div>`);
}

/** Retrieval explorer: run a search with the chosen mode and filters, show what comes back. */
export async function runExplorer(event) {
  event.preventDefault();
  const filters = {
    company: $("#x-company").value || undefined,
    product_type: $("#x-type").value || undefined,
    topic: $("#x-topic").value || undefined,
  };
  const results = $("#x-results");
  results.innerHTML = '<div class="empty">Searching&hellip;</div>';
  try {
    const data = await searchChunks({ query: $("#x-query").value, filters, mode: $("#x-mode").value, top_k: 8 });
    const where = $("#x-where");
    where.hidden = false;
    where.textContent = `mode = ${data.info.mode}   |   Chroma where = ${JSON.stringify(data.where)}   |   ` +
      `best semantic similarity = ${data.info.best_similarity ?? "n/a"}`;
    if (data.results.length) results.replaceChildren(...data.results.map(hitCard));
    else results.innerHTML = '<div class="empty">No chunks match these filters.</div>';
  } catch (err) {
    results.innerHTML = `<div class="error-box">${esc(err.message)}</div>`;
  }
}
