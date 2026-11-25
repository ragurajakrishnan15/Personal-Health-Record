import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { FileText, CheckCircle, Clock, XCircle, Loader, ExternalLink } from "lucide-react";
import { getDocuments, validateDocument, reprocessDocument } from "../services/api";
import useApi from "../hooks/useApi";
import NeedPatient from "../components/NeedPatient";
import { usePatient } from "../context/PatientContext";
import GenericTag, { InferredBanner } from "../components/GenericTag";
import { money } from "../lib/money";

const STATUS = {
  pending_review: { icon: <Clock size={16} className="text-warning" />, label: "Needs review" },
  verified: { icon: <CheckCircle size={16} className="text-success" />, label: "Verified" },
  corrected: { icon: <CheckCircle size={16} className="text-success" />, label: "Corrected" },
  rejected: { icon: <XCircle size={16} className="text-danger" />, label: "Rejected" },
};
const CATS = ["prescription", "lab_report", "discharge_summary", "consultation_note", "insurance_or_bill", "other"];
const pretty = (s) => s.replace(/_/g, " ");

function Detail({ doc, onChanged }) {
  const { canEdit } = usePatient();
  const x = doc.extracted_data || {};
  const decide = async (status) => {
    await validateDocument(doc.id, { validation_status: status });
    onChanged();
  };
  return (
    <div className="detail-panel">
      <div className="detail-head">
        <span>
          <strong>{x.doctor || "Unknown provider"}</strong> · {x.hospital || "—"} · {doc.document_date || "no date"}
        </span>
        <a className="btn btn-outline" href={`/api/documents/${doc.id}/file`} target="_blank" rel="noreferrer">
          <ExternalLink size={14} /> View original
        </a>
      </div>
      {doc.processing_status === "failed" && (
        <p className="text-danger">
          Extraction failed: {doc.processing_error}{" "}
          <button className="btn btn-outline" onClick={async () => { await reprocessDocument(doc.id); onChanged(); }}>Retry</button>
        </p>
      )}
      {x.validation_issues?.length > 0 && <p className="text-warning">Check: {x.validation_issues.join("; ")}</p>}
      {x.bill_total && <p><strong>Bill total:</strong> {money(x.bill_total, x.bill_currency)}</p>}
      <InferredBanner list={x.inferred_generics} />
      {x.diagnoses?.length > 0 && <p><strong>Diagnoses:</strong> {x.diagnoses.join("; ")}</p>}
      {x.medications?.length > 0 && (
        <table className="table">
          <thead><tr><th>Medication</th><th>Strength</th><th>Frequency</th><th>Timing</th><th>Duration</th></tr></thead>
          <tbody>
            {x.medications.map((m, i) => (
              <tr key={i}>
                <td>{m.name}<GenericTag name={m.generic_name} brand={m.name} inferred={m.generic_inferred} /></td>
                <td>{m.strength || m.dosage || "—"}</td><td>{m.frequency || "—"}</td>
                <td>{m.timing || "—"}</td><td>{m.duration || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {x.lab_results?.length > 0 && (
        <table className="table">
          <thead><tr><th>Test</th><th>Result</th><th>Unit</th><th>Reference</th></tr></thead>
          <tbody>
            {x.lab_results.map((l, i) => (
              <tr key={i} className={l.is_abnormal ? "row-abnormal" : ""}>
                <td>{l.test_name}</td><td><strong>{l.test_value}</strong> {l.flag || ""}</td>
                <td>{l.unit || "—"}</td><td>{l.reference_range || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {canEdit && doc.validation_status === "pending_review" && doc.processing_status === "done" && (
        <div>
          <button className="btn btn-primary" onClick={() => decide("verified")}><CheckCircle size={16} /> Looks correct</button>{" "}
          <button className="btn btn-outline" onClick={() => decide("rejected")}><XCircle size={16} /> Reject</button>
        </div>
      )}
    </div>
  );
}

function RecordList({ patient }) {
  const [params, setParams] = useSearchParams();
  const [category, setCategory] = useState("");
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(null);
  const status = params.get("status") || "";
  const docs = useApi(() => getDocuments(patient.id), [patient.id]);

  // keep polling while anything is still being extracted
  const busy = docs.data?.some((d) => d.processing_status === "processing");
  useEffect(() => {
    if (!busy) return;
    const t = setTimeout(docs.reload, 3000);
    return () => clearTimeout(t);
  }, [busy, docs.data]); // eslint-disable-line react-hooks/exhaustive-deps

  const shown = useMemo(
    () => (docs.data || []).filter((d) =>
      (!category || d.category === category) &&
      (!status || d.validation_status === status) &&
      (!query || `${d.filename} ${d.doctor || ""} ${d.hospital || ""}`.toLowerCase().includes(query.toLowerCase()))),
    [docs.data, category, status, query],
  );

  return (
    <>
      <div className="filter-bar">
        <select className="select" value={category} onChange={(e) => setCategory(e.target.value)}>
          <option value="">All categories</option>
          {CATS.map((c) => <option key={c} value={c}>{pretty(c)}</option>)}
        </select>
        <select className="select" value={status} onChange={(e) => setParams(e.target.value ? { status: e.target.value } : {})}>
          <option value="">All statuses</option>
          {Object.entries(STATUS).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
        </select>
        <input className="input" placeholder="Search doctor, facility, file…" value={query} onChange={(e) => setQuery(e.target.value)} />
      </div>
      {docs.error && <p className="text-danger">{docs.error}</p>}
      <div className="records-list">
        {docs.data && shown.length === 0 && (
          <p className="placeholder">
            {docs.data.length ? "No records match these filters." : "No records yet. Upload a medical document to get started."}
          </p>
        )}
        {shown.map((doc) => (
          <div key={doc.id} className="card">
            <div className="record-card" onClick={() => setOpen(open === doc.id ? null : doc.id)} style={{ cursor: "pointer" }}>
              <FileText size={20} />
              <div>
                <strong>{doc.filename}</strong> <span className="badge">{pretty(doc.category)}</span>{" "}
                {doc.processing_status === "processing" ? (
                  <span className="badge"><Loader size={12} className="spin" /> extracting</span>
                ) : doc.processing_status === "failed" ? (
                  <span className="badge badge-discontinued">failed</span>
                ) : (
                  <span title={STATUS[doc.validation_status]?.label}>{STATUS[doc.validation_status]?.icon}</span>
                )}
                <p className="text-muted">{[doc.doctor, doc.hospital].filter(Boolean).join(" · ")}</p>
              </div>
              <span className="date">{doc.document_date || String(doc.upload_date).slice(0, 10)}</span>
            </div>
            {open === doc.id && <Detail doc={doc} onChanged={docs.reload} />}
          </div>
        ))}
      </div>
    </>
  );
}

export default function Records() {
  return (
    <div className="page">
      <h2>Medical Records</h2>
      <NeedPatient>{(p) => <RecordList key={p.id} patient={p} />}</NeedPatient>
    </div>
  );
}
