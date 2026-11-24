import { useMemo, useState } from "react";
import { AlertTriangle, ArrowDown, ArrowUp, CheckCircle, ExternalLink, Minus, TrendingDown, TrendingUp } from "lucide-react";
import { getLabResults } from "../services/api";
import useApi from "../hooks/useApi";
import NeedPatient from "../components/NeedPatient";
import TrendChart, { Sparkline } from "../components/TrendChart";
import { RANGES, filterByRange, fmtDate, formatRange, groupLabs } from "../lib/labs";

const FLAG_WORD = { H: "High", L: "Low", "!": "Abnormal" };

function StatusBadge({ point }) {
  if (point.status === "unknown") {
    return <span className="status status-unknown"><Minus size={14} /> No reference range</span>;
  }
  if (point.abnormal) {
    return <span className="status status-bad"><AlertTriangle size={14} /> {FLAG_WORD[point.flag] || "Abnormal"}</span>;
  }
  return <span className="status status-ok"><CheckCircle size={14} /> In range</span>;
}

function TrendWord({ trend }) {
  if (trend === "worsening") return <span className="trend trend-bad"><TrendingUp size={14} /> moving further out of range</span>;
  if (trend === "improving") return <span className="trend"><TrendingDown size={14} /> moving toward range</span>;
  return <span className="trend text-muted"><Minus size={14} /> stable</span>;
}

function Delta({ latest, previous, unit }) {
  if (!previous) return <span className="text-muted">first reading</span>;
  const d = latest.value - previous.value;
  const pct = previous.value ? (d / previous.value) * 100 : 0;
  const Icon = d > 0 ? ArrowUp : d < 0 ? ArrowDown : Minus;
  return (
    <span className="delta">
      <Icon size={14} /> {d > 0 ? "+" : ""}{Number(d.toFixed(2))} {unit} ({pct > 0 ? "+" : ""}{pct.toFixed(1)}%)
      <span className="text-muted"> since {fmtDate(previous.t)}</span>
    </span>
  );
}

function ReadingsTable({ points, unit }) {
  return (
    <table className="table">
      <thead><tr><th>Date</th><th>Result</th><th>Reference</th><th>Status</th><th>Source</th></tr></thead>
      <tbody>
        {[...points].reverse().map((p) => (
          <tr key={p.id} className={p.abnormal ? "row-abnormal" : ""}>
            <td>{fmtDate(p.t)}</td>
            <td><strong>{p.raw}</strong> {unit}</td>
            <td>{formatRange(p.ref, p.range)}</td>
            <td><StatusBadge point={p} /></td>
            <td>
              {p.docId ? (
                <a href={`/api/documents/${p.docId}/file`} target="_blank" rel="noreferrer">
                  {p.lab || "Report"} <ExternalLink size={12} />
                </a>
              ) : (p.lab || "—")}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function Detail({ group }) {
  const [rangeKey, setRangeKey] = useState("all");
  const [view, setView] = useState("chart");
  const days = RANGES.find((r) => r.key === rangeKey).days;
  const pts = useMemo(() => filterByRange(group.points, days), [group, days]);

  return (
    <section className="card viz-root">
      <div className="viz-head">
        <div>
          <h3>{group.name}</h3>
          <p className="text-muted">
            {group.unit} · reference {formatRange(group.points.at(-1).ref, group.range)} · {group.points.length} reading
            {group.points.length === 1 ? "" : "s"} in total
          </p>
        </div>
        <div className="viz-controls">
          <div className="tab-bar" role="group" aria-label="Date range">
            {RANGES.map((r) => (
              <button key={r.key} className={`tab ${rangeKey === r.key ? "active" : ""}`} onClick={() => setRangeKey(r.key)}>
                {r.label}
              </button>
            ))}
          </div>
          <div className="tab-bar" role="group" aria-label="View">
            {["chart", "table"].map((v) => (
              <button key={v} className={`tab ${view === v ? "active" : ""}`} onClick={() => setView(v)}>
                {v === "chart" ? "Chart" : "Table"}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="kpi-row">
        <div>
          <span className="kpi-label">Latest ({fmtDate(group.latest.t)})</span>
          <span className="kpi-value">{group.latest.raw} <small>{group.unit}</small></span>
        </div>
        <div><span className="kpi-label">Status</span><StatusBadge point={group.latest} /></div>
        <div><span className="kpi-label">Change</span><Delta latest={group.latest} previous={group.previous} unit={group.unit} /></div>
        <div><span className="kpi-label">Direction</span><TrendWord trend={group.trend} /></div>
      </div>

      {pts.length === 0 ? (
        <p className="placeholder">
          No readings in this period. <button className="btn btn-outline" onClick={() => setRangeKey("all")}>Show all</button>
        </p>
      ) : view === "chart" ? (
        <>
          <TrendChart name={group.name} unit={group.unit} points={pts} range={group.range} />
          <p className="viz-note text-muted">
            Shaded band = reference range. <span className="dot-key dot-key-ok" /> in range &nbsp;
            <span className="dot-key dot-key-bad" /> out of range (marked H / L).
          </p>
        </>
      ) : (
        <ReadingsTable points={pts} unit={group.unit} />
      )}
    </section>
  );
}

function Overview({ groups, selected, onSelect }) {
  return (
    <section className="card">
      <h3>All parameters</h3>
      <p className="text-muted">Sorted with out-of-range results first. Click a card to see its trend.</p>
      <div className="spark-grid">
        {groups.map((g) => (
          <button key={g.name} className={`spark-card ${g.name === selected ? "selected" : ""}`} onClick={() => onSelect(g.name)}
                  aria-pressed={g.name === selected}>
            <div className="spark-top">
              <span className="spark-name">{g.name}</span>
              {g.latest.abnormal && <span className="status status-bad"><AlertTriangle size={12} /> {FLAG_WORD[g.latest.flag] || "Abnormal"}</span>}
              {g.latest.status === "unknown" && <span className="status status-unknown">no range</span>}
            </div>
            <div className="spark-value">{g.latest.raw} <small>{g.unit}</small></div>
            <Sparkline points={g.points} range={g.range} />
          </button>
        ))}
      </div>
    </section>
  );
}

function Attention({ groups, onSelect }) {
  const items = groups.filter((g) => g.latest.abnormal)
    .sort((a, b) => (b.trend === "worsening") - (a.trend === "worsening") || b.latest.t - a.latest.t).slice(0, 6);
  return (
    <section className="card">
      <h3>Needs attention</h3>
      <p className="text-muted">Automatic highlights from the latest result of each test (rule-based, not medical advice).</p>
      {items.length === 0 && <p className="placeholder"><CheckCircle size={16} /> Every parameter's latest result is within its reference range.</p>}
      <ul className="attention-list">
        {items.map((g) => (
          <li key={g.name}>
            <button className="link-btn" onClick={() => onSelect(g.name)}>
              <strong>{g.name}</strong>: {g.latest.raw} {g.unit} ({FLAG_WORD[g.latest.flag] || "abnormal"})
            </button>
            <TrendWord trend={g.trend} />
          </li>
        ))}
      </ul>
    </section>
  );
}

function Dashboard({ patient }) {
  const labs = useApi(() => getLabResults(patient.id), [patient.id]);
  const groups = useMemo(() => {
    const g = groupLabs(labs.data);
    return g.sort((a, b) => b.latest.abnormal - a.latest.abnormal || b.points.length - a.points.length || a.name.localeCompare(b.name));
  }, [labs.data]);

  const [selected, setSelected] = useState(null);
  const current = groups.find((g) => g.name === selected) || [...groups].sort((a, b) => b.points.length - a.points.length)[0];

  if (labs.loading) return <p className="placeholder">Loading lab results…</p>;
  if (labs.error) return <p className="text-danger">{labs.error}</p>;
  if (groups.length === 0) {
    return <p className="placeholder">No lab results yet. Upload a lab report to see trends here.</p>;
  }

  return (
    <>
      <Attention groups={groups} onSelect={setSelected} />
      <Detail key={current.name} group={current} />
      <Overview groups={groups} selected={current.name} onSelect={setSelected} />
    </>
  );
}

export default function Analytics() {
  return (
    <div className="page">
      <h2>Health Analytics</h2>
      <NeedPatient>{(p) => <Dashboard key={p.id} patient={p} />}</NeedPatient>
    </div>
  );
}
