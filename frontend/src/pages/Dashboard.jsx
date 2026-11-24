import { Link } from "react-router-dom";
import { FileText, Pill, AlertTriangle, Calendar, Upload } from "lucide-react";
import { getHealthSummary, getTimeline } from "../services/api";
import useApi from "../hooks/useApi";
import NeedPatient from "../components/NeedPatient";
import { usePatient } from "../context/PatientContext";

function Overview({ patient }) {
  const { canEdit } = usePatient();
  const summary = useApi(() => getHealthSummary(patient.id), [patient.id]);
  const timeline = useApi(() => getTimeline(patient.id), [patient.id]);
  const s = summary.data;
  const val = (v) => (summary.loading ? "…" : v ?? "—");

  return (
    <>
      <p className="text-muted">
        {patient.name}
        {patient.age ? `, ${patient.age}` : ""}
        {patient.gender ? ` · ${patient.gender}` : ""}
        {patient.blood_group ? ` · ${patient.blood_group}` : ""}
      </p>

      <div className="stats-grid">
        <Link to="/records" className="stat-card stat-link">
          <FileText size={24} />
          <div><span className="stat-value">{val(s?.total_documents)}</span><span className="stat-label">Documents</span></div>
        </Link>
        <Link to="/medications" className="stat-card stat-link">
          <Pill size={24} />
          <div><span className="stat-value">{val(s?.active_medications)}</span><span className="stat-label">Active Medications</span></div>
        </Link>
        <Link to="/records?status=pending_review" className="stat-card stat-link">
          <AlertTriangle size={24} />
          <div><span className="stat-value">{val(s?.pending_reviews)}</span><span className="stat-label">Pending Reviews</span></div>
        </Link>
        <div className="stat-card">
          <Calendar size={24} />
          <div><span className="stat-value">{val(s?.upcoming_followups)}</span><span className="stat-label">Upcoming Follow-ups</span></div>
        </div>
      </div>

      <section className="card">
        <div className="page-header">
          <h3>Recent Lab Results</h3>
          {canEdit && <Link to="/upload" className="btn btn-outline"><Upload size={16} /> Upload report</Link>}
        </div>
        {summary.error && <p className="text-danger">{summary.error}</p>}
        {s && s.recent_labs.length === 0 && <p className="placeholder">No lab results yet. Upload a report to get started.</p>}
        {s && s.recent_labs.length > 0 && (
          <table className="table">
            <thead><tr><th>Test</th><th>Result</th><th>Date</th></tr></thead>
            <tbody>
              {s.recent_labs.map((l, i) => (
                <tr key={i} className={l.abnormal ? "row-abnormal" : ""}>
                  <td>{l.test}</td>
                  <td><strong>{l.value}</strong> {l.unit}{l.abnormal && " ⚠"}</td>
                  <td>{l.date}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {s?.abnormal_labs > 0 && <p className="text-warning">{s.abnormal_labs} abnormal result(s) on record.</p>}
      </section>

      <section className="card">
        <h3>Medical Timeline</h3>
        {timeline.data?.length === 0 && <p className="placeholder">Timeline will appear here as records are added.</p>}
        <ol className="timeline">
          {(timeline.data || []).map((e) => (
            <li key={e.id} className={`tl-${e.event_type}`}>
              <span className="tl-date">{e.event_date}</span>
              <div>
                <strong>{e.title}</strong>
                {e.description && <p className="text-muted">{e.description}</p>}
              </div>
            </li>
          ))}
        </ol>
      </section>
    </>
  );
}

export default function Dashboard() {
  return (
    <div className="page">
      <h2>Health Overview</h2>
      <NeedPatient>{(p) => <Overview key={p.id} patient={p} />}</NeedPatient>
    </div>
  );
}
