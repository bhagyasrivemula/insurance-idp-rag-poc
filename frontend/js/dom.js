/**
 * Small DOM helpers.
 */

/** First element matching a CSS selector. */
export const $ = (selector, root = document) => root.querySelector(selector);

/** All elements matching a CSS selector, as an array. */
export const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

/**
 * Create an element.
 * @param {string} tag
 * @param {string} [className]
 * @param {string} [html] - trusted or already-escaped HTML only
 */
export function el(tag, className, html) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (html !== undefined) node.innerHTML = html;
  return node;
}

const HTML_ESCAPES = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };

/**
 * Escape text before inserting it as HTML.
 * Model output, PDF text and user input are all untrusted.
 */
export function esc(text) {
  return String(text ?? "").replace(/[&<>"']/g, (c) => HTML_ESCAPES[c]);
}

/**
 * Size progress bars rendered as `<div class="bar-fill" data-width="42">`.
 * Widths are set from JS rather than inline style attributes (CSP-friendly).
 */
export function applyBarWidths(root) {
  root.querySelectorAll(".bar-fill[data-width]").forEach((bar) => {
    bar.style.width = `${Math.max(0, Math.min(100, Number(bar.dataset.width)))}%`;
  });
}

/** Format a 0-1 score as a percentage ("-" when missing). */
export const pct = (v) => (v === null || v === undefined ? "\u2014" : `${Math.round(v * 100)}%`);
