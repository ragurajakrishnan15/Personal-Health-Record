/** Helpers for turning API lab rows (strings) into chartable series. */

/** "13.5-17.5" -> {lo, hi}; "<200" -> {lo: null, hi: 200}; ">40" -> {lo: 40, hi: null}; else null. */
export function parseRange(ref) {
  if (!ref) return null;
  const r = String(ref).replace(/[–—]/g, "-").trim();
  let m = r.match(/^(-?\d+(?:\.\d+)?)\s*-\s*(-?\d+(?:\.\d+)?)$/);
  if (m) return { lo: parseFloat(m[1]), hi: parseFloat(m[2]) };
  m = r.match(/^[<≤]=?\s*(\d+(?:\.\d+)?)$/);
  if (m) return { lo: null, hi: parseFloat(m[1]) };
  m = r.match(/^[>≥]=?\s*(\d+(?:\.\d+)?)$/);
  if (m) return { lo: parseFloat(m[1]), hi: null };
  return null;
}

export function toNumber(v) {
  const m = String(v ?? "").replace(/,/g, "").match(/-?\d+(?:\.\d+)?/);
  return m ? parseFloat(m[0]) : null;
}

/** "H" / "L" / null relative to a parsed range. */
export function flagFor(value, range) {
  if (!range || value == null) return null;
  if (range.lo != null && value < range.lo) return "L";
  if (range.hi != null && value > range.hi) return "H";
  return null;
}

/** How far outside the reference range a value is (0 when inside or unknown). */
export function distanceFromRange(value, range) {
  if (!range || value == null) return 0;
  if (range.lo != null && value < range.lo) return range.lo - value;
  if (range.hi != null && value > range.hi) return value - range.hi;
  return 0;
}

export function formatRange(ref, range) {
  if (!range) return ref || "—";
  if (range.lo == null) return `< ${range.hi}`;
  if (range.hi == null) return `> ${range.lo}`;
  return `${range.lo} – ${range.hi}`;
}

/** Group lab rows into one series per test, oldest -> newest, with a summary for each. */
export function groupLabs(results) {
  const by = new Map();
  for (const r of results || []) {
    const value = toNumber(r.test_value);
    const t = Date.parse(r.report_date);
    if (value == null || Number.isNaN(t)) continue;
    const range = parseRange(r.reference_range);
    const flag = flagFor(value, range) ?? (r.is_abnormal ? "!" : null);
    const p = {
      t, date: r.report_date, value, raw: r.test_value, unit: r.unit, ref: r.reference_range, range,
      flag, abnormal: r.is_abnormal === true, docId: r.document_id, lab: r.lab_name, id: r.id,
      // 'ok' = checked against a range, 'unknown' = no reference range was printed on the report
      status: r.is_abnormal === true ? "bad" : (range || r.is_abnormal === false ? "ok" : "unknown"),
    };
    if (!by.has(r.test_name)) by.set(r.test_name, []);
    by.get(r.test_name).push(p);
  }
  return [...by.entries()].map(([name, points]) => {
    points.sort((a, b) => a.t - b.t);
    const latest = points[points.length - 1];
    const previous = points.length > 1 ? points[points.length - 2] : null;
    const range = [...points].reverse().find((p) => p.range)?.range ?? null;
    let trend = "stable";
    if (previous) {
      const d1 = distanceFromRange(latest.value, range);
      const d0 = distanceFromRange(previous.value, range);
      if (d1 > d0) trend = "worsening";
      else if (d1 < d0) trend = "improving";
    }
    return {
      name, unit: latest.unit, points, latest, previous, range, trend,
      nAbnormal: points.filter((p) => p.abnormal).length,
    };
  });
}

export const RANGES = [
  { key: "3m", label: "3 months", days: 92 },
  { key: "6m", label: "6 months", days: 183 },
  { key: "1y", label: "1 year", days: 365 },
  { key: "all", label: "All", days: null },
];

export function filterByRange(points, days, now = Date.now()) {
  if (!days) return points;
  const cutoff = now - days * 86400000;
  return points.filter((p) => p.t >= cutoff);
}

export const fmtDate = (t) => new Date(t).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
export const fmtMonth = (t) => new Date(t).toLocaleDateString(undefined, { month: "short", year: "2-digit" });
