/** Light / dark / follow-the-device. The choice is a display preference only, kept in this browser. */
const KEY = "phr.theme";
const dark = () => window.matchMedia("(prefers-color-scheme: dark)");

export const getTheme = () => {
  try { return localStorage.getItem(KEY) || "system"; } catch { return "system"; }
};

export function applyTheme(choice = getTheme()) {
  const mode = choice === "system" ? (dark().matches ? "dark" : "light") : choice;
  document.documentElement.dataset.theme = mode;
  document.querySelector('meta[name="theme-color"]')?.setAttribute("content", mode === "dark" ? "#0b1020" : "#eef2f7");
}

export function setTheme(choice) {
  try { localStorage.setItem(KEY, choice); } catch { /* storage unavailable */ }
  applyTheme(choice);
}

export function initTheme() {
  applyTheme();
  dark().addEventListener("change", () => applyTheme());
}
