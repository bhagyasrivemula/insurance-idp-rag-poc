/**
 * What appears under a finished answer: the scope/timing footer and the guardrail panel.
 */
import { SCOPE_REASONS } from "./constants.js";
import { el, esc } from "./dom.js";
import { describeFilters } from "./filters.js";

const STATUS_ICON = { pass: "\u2713", warn: "!", block: "\u2715" };

const seconds = (ms) => (ms / 1000).toFixed(1);

/**
 * Footer: which scope was searched (and why), the rewritten search query,
 * number of sources, LangSmith trace link and response time.
 */
export function answerFooter(meta, timings, traceUrl) {
  const scope = describeFilters(meta.filters || {});
  const why = SCOPE_REASONS[meta.filter_source] || "";
  const parts = [
    `<span class="tag scope">Scope: ${esc(scope.length ? scope.join(", ") : "All brochures")}</span>`,
    why && scope.length ? `<span>${esc(why)}</span>` : "",
    meta.filter_source === "question_override"
      ? '<span class="tag note">Products named in your question \u2014 sidebar filters ignored</span>' : "",
    meta.search_query
      ? `<span class="tag" title="Follow-up rewritten into a standalone search query">Searched: \u201c${esc(meta.search_query)}\u201d</span>` : "",
    meta.sources.length ? `<span class="tag">${meta.sources.length} sources</span>` : "",
    traceUrl ? `<a class="tag trace" href="${esc(traceUrl)}" target="_blank" rel="noopener">LangSmith trace \u2197</a>` : "",
    timings?.total_ms
      ? `<span>\u00b7 ${seconds(timings.total_ms)}s${timings.first_token_ms ? ` (first words in ${seconds(timings.first_token_ms)}s)` : ""}</span>` : "",
  ];
  return el("div", "answer-meta", parts.join(""));
}

/**
 * Guardrail results: a one-line summary that expands into the individual checks
 * (PII masking, injection, content safety, topic, grounded figures, citations, promises).
 * Warnings and blocks open automatically so problems are never hidden.
 */
export function guardrailPanel(checks) {
  const panel = el("details", "guards");
  if (!checks.length) {
    panel.hidden = true;
    return panel;
  }
  const count = (status) => checks.filter((c) => c.status === status).length;
  const warn = count("warn");
  const block = count("block");
  const overall = block ? "block" : warn ? "warn" : "pass";
  const summary = [`${checks.length - warn - block} passed`,
    warn ? `${warn} warning${warn > 1 ? "s" : ""}` : "", block ? `${block} blocked` : ""].filter(Boolean).join(" \u00b7 ");

  const items = checks.map((c) => `
    <li class="${esc(c.status)}"><span class="guards-icon">${STATUS_ICON[c.status] || "?"}</span>
      <b>${esc(c.check)}</b><span>${esc(c.detail)}</span></li>`).join("");
  panel.innerHTML = `
    <summary class="guards-sum ${overall}"><span class="guards-icon">${STATUS_ICON[overall]}</span>Guardrails: ${summary}</summary>
    <ul class="guards-list">${items}</ul>`;
  panel.open = overall !== "pass";
  return panel;
}
