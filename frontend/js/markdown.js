/**
 * Minimal, safe Markdown renderer for answers and source excerpts.
 *
 * Supports paragraphs, headings, bullet/numbered lists, pipe tables and
 * citation markers ([2], [1, 3]) - enough for the model's output, without a library.
 * All text is HTML-escaped first, so untrusted content cannot inject markup.
 *
 * Each block parser consumes lines from a shared cursor and ALWAYS advances it,
 * so rendering can never loop forever, even on incomplete streamed text.
 */
import { esc } from "./dom.js";

const TABLE_ROW = /^\s*\|/;               // a row only needs to start with "|" (may be streaming)
const TABLE_SEPARATOR = /^\s*\|?\s*:?-{2,}/;
const BULLET = /^\s*[-*\u2022]\s+/;
const NUMBERED = /^\s*\d+[.)]\s+/;
const HEADING = /^\s*#{1,4}\s+(.*)/;
const BLOCK_START = /^\s*(\||#{1,4}\s|[-*\u2022]\s|\d+[.)]\s)/;
const CITATION = /\[(\d+(?:\s*,\s*\d+)*)\]/g;

/** Inline formatting: code, bold, italics and clickable citation markers. */
export function renderInline(text) {
  return esc(text)
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/(^|[\s(])\*([^*\s][^*]*)\*/g, "$1<em>$2</em>")
    .replace(CITATION, (_, nums) => nums.split(",")
      .map((n) => `<button class="cite" data-n="${n.trim()}">${n.trim()}</button>`).join(""));
}

/** Citation numbers used in a text: "... [2] ... [1, 4]" -> Set {1, 2, 4}. */
export function citedNumbers(text) {
  const nums = new Set();
  for (const match of text.matchAll(CITATION)) {
    match[1].split(",").forEach((n) => nums.add(Number(n)));
  }
  return nums;
}

/** Split "| a | b |" into trimmed cells (a missing closing pipe is fine). */
const cells = (row) => row.trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim());

function renderTable(cursor) {
  const rows = [];
  while (cursor.hasMore() && TABLE_ROW.test(cursor.peek())) rows.push(cursor.next());
  const body = rows.filter((r) => !TABLE_SEPARATOR.test(r)).map(cells);
  // Drop columns that are empty in every row (PDF tables often contain spacer columns).
  const width = Math.max(0, ...body.map((r) => r.length));
  const keep = [...Array(width).keys()].filter((i) => body.some((r) => (r[i] || "").trim()));
  if (!body.length || !keep.length) return "";
  const [head, ...rest] = body.map((r) => keep.map((i) => r[i] || ""));
  const th = head.map((c) => `<th>${renderInline(c)}</th>`).join("");
  const trs = rest.map((r) => `<tr>${r.map((c) => `<td>${renderInline(c)}</td>`).join("")}</tr>`).join("");
  return `<table><thead><tr>${th}</tr></thead><tbody>${trs}</tbody></table>`;
}

function renderList(cursor) {
  const ordered = NUMBERED.test(cursor.peek());
  const item = ordered ? NUMBERED : BULLET;    // a numbered list after bullets starts a new list
  const items = [];
  while (cursor.hasMore() && item.test(cursor.peek())) {
    items.push(cursor.next().replace(item, ""));
    // allow blank lines between items of the same list
    while (cursor.hasMore() && !cursor.peek().trim() && item.test(cursor.peek(1))) cursor.next();
  }
  const tag = ordered ? "ol" : "ul";
  return `<${tag}>${items.map((t) => `<li>${renderInline(t)}</li>`).join("")}</${tag}>`;
}

function renderParagraph(cursor) {
  const lines = [cursor.next()];                 // always consume at least one line
  while (cursor.hasMore() && cursor.peek().trim() && !BLOCK_START.test(cursor.peek())) lines.push(cursor.next());
  return `<p>${renderInline(lines.join(" "))}</p>`;
}

/** Iterator over lines with one-line lookahead. */
function lineCursor(text) {
  const lines = text.replace(/\r/g, "").split("\n");
  let i = 0;
  return {
    hasMore: () => i < lines.length,
    peek: (offset = 0) => lines[i + offset] ?? "",
    next: () => lines[i++],
  };
}

/** Render Markdown text to safe HTML. */
export function renderMarkdown(text) {
  const cursor = lineCursor(String(text ?? ""));
  const out = [];
  while (cursor.hasMore()) {
    const line = cursor.peek();
    if (!line.trim()) { cursor.next(); continue; }
    if (TABLE_ROW.test(line)) { out.push(renderTable(cursor)); continue; }
    if (BULLET.test(line) || NUMBERED.test(line)) { out.push(renderList(cursor)); continue; }
    const heading = line.match(HEADING);
    if (heading) { cursor.next(); out.push(`<h4>${renderInline(heading[1])}</h4>`); continue; }
    out.push(renderParagraph(cursor));
  }
  return out.join("");
}
