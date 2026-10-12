/**
 * RAGAS scorecard in the Knowledge base tab (report written by `python -m app.ragas_eval`).
 */
import { fetchEvaluation } from "./api.js";
import { RAGAS_LABELS } from "./constants.js";
import { $, applyBarWidths, esc, pct } from "./dom.js";

const label = (metric) => RAGAS_LABELS[metric] || metric;

/** good >= 80 %, ok >= 60 %, otherwise low (drives the colour). */
function tone(value) {
  if (value === null || value === undefined) return "";
  if (value >= 0.8) return "good";
  return value >= 0.6 ? "ok" : "low";
}

function scoreTile(metric, value, info) {
  return `
    <div class="ragas-score ${tone(value)}" title="${esc(info)}">
      <div class="v">${pct(value)}</div>
      <div class="l">${esc(label(metric))}</div>
      <div class="bar-track"><div class="bar-fill" data-width="${(value || 0) * 100}"></div></div>
      <div class="hint">${esc(info)}</div>
    </div>`;
}

function resultsTable(rows, metrics) {
  const head = metrics.map((m) => `<th>${esc(label(m))}</th>`).join("");
  const body = rows.map((r) => `<tr><td>${esc(r.question)}</td>${metrics
    .map((m) => `<td class="num ${tone(r[m])}">${pct(r[m])}</td>`).join("")}</tr>`).join("");
  return `
    <details class="ragas-rows"><summary>Per-question results</summary>
      <div class="table-wrap"><table class="data"><thead><tr><th>Question</th>${head}</tr></thead><tbody>${body}</tbody></table></div>
    </details>`;
}

/** Load the latest RAGAS report into the Quality evaluation card. */
export async function loadEvaluation() {
  const box = $("#ragas");
  const data = await fetchEvaluation();
  if (!data.available) {
    box.innerHTML = '<div class="empty">No evaluation yet. Run <code>python -m app.ragas_eval</code> to score the assistant.</div>';
    return;
  }
  const metrics = Object.keys(data.scores);
  const runAt = new Date(data.run_at).toLocaleString();
  box.innerHTML = `
    <div class="ragas-meta muted small">${data.questions} questions \u00b7 answers by ${esc(data.chat_model)}
      \u00b7 judged by ${esc(data.judge_model)} \u00b7 ${esc(runAt)}</div>
    <div class="ragas-scores">${metrics.map((m) => scoreTile(m, data.scores[m], data.metric_info[m] || "")).join("")}</div>
    ${resultsTable(data.rows, metrics)}`;
  applyBarWidths(box);
}
