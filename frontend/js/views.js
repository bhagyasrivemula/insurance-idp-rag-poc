/**
 * Tab navigation (Assistant / Products / Knowledge base).
 *
 * Other modules register an "on first enter" hook instead of importing each
 * other, which keeps the dependency graph one-directional.
 */
import { $$ } from "./dom.js";

const enterHooks = new Map();     // view name -> callback, run once on first visit
const visited = new Set();

/** Run `callback` the first time the given view is shown (e.g. lazy data loading). */
export function onFirstEnter(view, callback) {
  enterHooks.set(view, callback);
}

/** Show a view; the URL hash (#products etc.) keeps views deep-linkable. */
export function switchView(name) {
  if (!document.getElementById(`view-${name}`)) name = "assistant";
  if (location.hash !== `#${name}`) history.replaceState(null, "", `#${name}`);
  $$(".tab").forEach((t) => t.classList.toggle("active", t.dataset.view === name));
  $$(".view").forEach((v) => v.classList.toggle("active", v.id === `view-${name}`));
  if (!visited.has(name)) {
    visited.add(name);
    enterHooks.get(name)?.();
  }
}

/** View named in the current URL hash. */
export const currentHashView = () => location.hash.slice(1) || "assistant";
