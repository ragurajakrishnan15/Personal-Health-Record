/** Today as YYYY-MM-DD in the user's own timezone (toISOString() would give the UTC date). */
export const todayLocal = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
};

/** "Mon 15 Jan 2099" from a YYYY-MM-DD string (parsed as a local date, never shifted by timezone). */
export const prettyDate = (iso) => {
  if (!iso) return "";
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y, m - 1, d).toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short", year: "numeric" });
};

/** Readable message from an axios error (FastAPI validation errors arrive as a list). */
export const errMsg = (e) => {
  const d = e?.response?.data?.detail;
  if (Array.isArray(d)) return d.map((x) => `${(x.loc || []).slice(-1)[0] || "value"} ${x.msg}`.replace("Value error, ", "")).join("; ");
  return d || "Something went wrong";
};
