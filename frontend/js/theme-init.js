/**
 * Applies the saved theme before the page is painted (prevents a light -> dark flash).
 * Loaded as a classic, render-blocking script in <head>; everything else is an ES module.
 */
(function applySavedTheme() {
  let mode = "system";
  let accent = "teal";
  try {
    mode = localStorage.getItem("ia-mode") || mode;
    accent = localStorage.getItem("ia-accent") || accent;
  } catch (e) {
    /* storage blocked (private mode): fall back to defaults */
  }
  const dark = mode === "dark" || (mode === "system" && window.matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.dataset.theme = dark ? "dark" : "light";
  document.documentElement.dataset.accent = accent;
})();
