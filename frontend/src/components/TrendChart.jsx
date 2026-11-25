import {
  CartesianGrid, Line, LineChart, ReferenceArea, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { fmtDate, fmtMonth, formatRange } from "../lib/labs";

/* Chart colours (match the --viz-* tokens in App.css). One series -> one hue; red is reserved for out-of-range. */
export const VIZ = {
  surface: "var(--viz-surface)", text: "var(--viz-text)", text2: "var(--viz-text2)", grid: "var(--viz-grid)",
  series: "var(--viz-series)", critical: "var(--viz-critical)", band: "var(--viz-band)",
};

/** Round axis bounds and ticks (1/2/5 x 10^n steps) so labels read as clean numbers. */
function niceScale(min, max, count = 5) {
  const span = max - min || 1;
  const rough = span / (count - 1);
  const mag = 10 ** Math.floor(Math.log10(rough));
  const norm = rough / mag;
  const step = (norm < 1.5 ? 1 : norm < 3 ? 2 : norm < 7 ? 5 : 10) * mag;
  const lo = Math.max(0, Math.floor(min / step) * step);
  const hi = Math.ceil(max / step) * step;
  const ticks = [];
  for (let v = lo; v <= hi + step / 2; v += step) ticks.push(Number(v.toFixed(10)));
  return { lo, hi, ticks };
}

const FLAG_WORD = { H: "High", L: "Low", "!": "Abnormal" };

function Dot({ cx, cy, payload }) {
  if (cx == null || cy == null) return null;
  const abn = payload.abnormal;
  return (
    <g>
      <circle cx={cx} cy={cy} r={abn ? 6 : 4.5} fill={abn ? VIZ.critical : VIZ.series} stroke={VIZ.surface} strokeWidth={2} />
      {abn && (
        <text x={cx} y={cy - 12} textAnchor="middle" fontSize="11" fontWeight="700" fill={VIZ.text2}>{payload.flag}</text>
      )}
    </g>
  );
}

function TooltipBox({ active, payload, unit }) {
  if (!active || !payload?.length) return null;
  const p = payload[0].payload;
  return (
    <div className="viz-tooltip">
      <div className="viz-tt-date">{fmtDate(p.t)}</div>
      <div className="viz-tt-value">{p.raw} <span>{unit}</span></div>
      <div className="viz-tt-row">
        {p.status === "unknown" ? "No reference range on report" : p.abnormal ? `${FLAG_WORD[p.flag] || "Abnormal"} (outside range)` : "Within range"}
      </div>
      <div className="viz-tt-row">Reference: {formatRange(p.ref, p.range)}</div>
      {p.lab && <div className="viz-tt-row">{p.lab}</div>}
    </div>
  );
}

/** One test over time: line + markers, shaded reference range, abnormal points marked and labelled H/L. */
export default function TrendChart({ name, unit, points, range }) {
  const vals = points.map((p) => p.value);
  const lo = range?.lo ?? null;
  const hi = range?.hi ?? null;
  let yMin = Math.min(...vals, lo ?? Infinity);
  let yMax = Math.max(...vals, hi ?? -Infinity);
  if (yMin === yMax) { yMin -= 1; yMax += 1; }
  const pad = (yMax - yMin) * 0.14;
  const scale = niceScale(Math.max(0, yMin - pad), yMax + pad);
  yMin = scale.lo;
  yMax = scale.hi;
  const band = range ? { y1: lo ?? yMin, y2: hi ?? yMax } : null;
  const last = points[points.length - 1];
  const summary = `${name}: ${points.length} reading${points.length === 1 ? "" : "s"}, latest ${last.raw} ${unit || ""}` +
    (last.status === "unknown" ? " (no reference range)" : last.abnormal ? ` (${FLAG_WORD[last.flag] || "abnormal"})` : " (within range)");

  return (
    <div role="img" aria-label={summary} className="trend-chart">
      <ResponsiveContainer width="100%" height={280}>
        <LineChart data={points} margin={{ top: 22, right: 20, bottom: 4, left: 4 }}>
          <CartesianGrid stroke={VIZ.grid} strokeWidth={1} vertical={false} />
          {band && (
            <ReferenceArea y1={band.y1} y2={band.y2} fill={VIZ.band} stroke="none" ifOverflow="hidden"
              label={{ value: `Reference range ${formatRange(null, range)}`, position: "insideTopLeft", fontSize: 11, fill: VIZ.text2 }} />
          )}
          <XAxis dataKey="t" type="number" scale="time" domain={["dataMin", "dataMax"]} tickFormatter={fmtMonth}
            tick={{ fontSize: 12, fill: VIZ.text2 }} axisLine={{ stroke: VIZ.grid }} tickLine={false}
            padding={{ left: 18, right: 18 }} tickCount={6} />
          <YAxis domain={[yMin, yMax]} ticks={scale.ticks} tick={{ fontSize: 12, fill: VIZ.text2 }} axisLine={false} tickLine={false}
            width={48} tickFormatter={(v) => (Math.abs(v) >= 100 ? Math.round(v) : Number(v.toFixed(2)))} />
          <Tooltip content={<TooltipBox unit={unit} />} cursor={{ stroke: VIZ.text2, strokeWidth: 1, strokeDasharray: "3 3" }} />
          <Line type="linear" dataKey="value" stroke={VIZ.series} strokeWidth={2} dot={<Dot />}
            activeDot={({ cx, cy, payload }) => (
              <circle cx={cx} cy={cy} r={7} fill={payload.abnormal ? VIZ.critical : VIZ.series} stroke={VIZ.surface} strokeWidth={2} />
            )} isAnimationActive={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

/** Tiny trend line for the overview grid; the latest point is marked, in red when abnormal. */
export function Sparkline({ points, range }) {
  if (points.length < 2) return <div className="spark-single">single reading</div>;
  const vals = points.map((p) => p.value);
  const yMin = Math.min(...vals, range?.lo ?? Infinity);
  const yMax = Math.max(...vals, range?.hi ?? -Infinity);
  const pad = (yMax - yMin || 1) * 0.15;
  const last = points.length - 1;
  return (
    <ResponsiveContainer width="100%" height={46}>
      <LineChart data={points} margin={{ top: 6, right: 6, bottom: 4, left: 6 }}>
        <XAxis dataKey="t" type="number" scale="time" domain={["dataMin", "dataMax"]} hide />
        <YAxis domain={[yMin - pad, yMax + pad]} hide />
        {range && <ReferenceArea y1={range.lo ?? yMin - pad} y2={range.hi ?? yMax + pad} fill={VIZ.band} stroke="none" ifOverflow="hidden" />}
        <Line type="linear" dataKey="value" stroke={VIZ.series} strokeWidth={2} isAnimationActive={false}
          dot={({ cx, cy, index, payload }) => index === last ? (
            <circle key="last" cx={cx} cy={cy} r={4} fill={payload.abnormal ? VIZ.critical : VIZ.series} stroke={VIZ.surface} strokeWidth={2} />
          ) : <g key={index} />} />
      </LineChart>
    </ResponsiveContainer>
  );
}
