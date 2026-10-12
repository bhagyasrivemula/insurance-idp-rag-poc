/**
 * Appearance menu: light / dark / system mode and accent colour.
 * The choice is saved per browser; theme-init.js applies it before first paint.
 */
import { $, $$ } from "./dom.js";

const MODE_KEY = "ia-mode";
const ACCENT_KEY = "ia-accent";
const darkQuery = window.matchMedia("(prefers-color-scheme: dark)");

/** localStorage that never throws (it can be blocked in private windows). */
const store = {
  get(key, fallback) {
    try { return localStorage.getItem(key) || fallback; } catch { return fallback; }
  },
  set(key, value) {
    try { localStorage.setItem(key, value); } catch { /* keep for this session only */ }
  },
};

/** Apply the saved mode/accent and mark the active choices in the menu. */
function applyTheme() {
  const mode = store.get(MODE_KEY, "system");
  const accent = store.get(ACCENT_KEY, "teal");
  const dark = mode === "dark" || (mode === "system" && darkQuery.matches);
  document.documentElement.dataset.theme = dark ? "dark" : "light";
  document.documentElement.dataset.accent = accent;
  $$("#mode-group button").forEach((b) => b.classList.toggle("active", b.dataset.mode === mode));
  $$("#swatches button").forEach((b) => b.classList.toggle("active", b.dataset.accent === accent));
}

/** Wire the appearance button and menu. */
export function initTheme() {
  const button = $("#theme-btn");
  const menu = $("#theme-menu");
  const setOpen = (open) => {
    menu.hidden = !open;
    button.setAttribute("aria-expanded", String(open));
  };

  button.addEventListener("click", (e) => {
    e.stopPropagation();
    setOpen(menu.hidden);
  });
  menu.addEventListener("click", (e) => {
    e.stopPropagation();
    const choice = e.target.closest("button");
    if (choice?.dataset.mode) store.set(MODE_KEY, choice.dataset.mode);
    if (choice?.dataset.accent) store.set(ACCENT_KEY, choice.dataset.accent);
    applyTheme();
  });
  document.addEventListener("click", () => setOpen(false));
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") setOpen(false); });
  darkQuery.addEventListener("change", applyTheme);    // follow the OS in "System" mode
  applyTheme();
}
