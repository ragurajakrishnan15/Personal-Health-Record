import { useEffect, useRef, useState } from "react";
import { Upload as UploadIcon, FileUp, Loader, CheckCircle, XCircle, AlertTriangle } from "lucide-react";
import { uploadDocument, getDocument, reprocessDocument, validateDocument } from "../services/api";
import { usePatient } from "../context/PatientContext";
import NeedPatient from "../components/NeedPatient";
import GenericTag, { InferredBanner } from "../components/GenericTag";

/**
 * Upload -> background AI extraction (polled) -> review summary -> verify / reject.
 * TODO: drag-and-drop, multi-file, camera capture, side-by-side original + editable fields,
 *       and the shared selected-patient context (for now the page has its own patient picker).
 */

const POLL_MS = 2000;

function UploadForm({ patient }) {
  const patientId = patient.id;
  const [file, setFile] = useState(null);
  const [doc, setDoc] = useState(null);
  const [error, setError] = useState("");
  const fileRef = useRef();

  // Poll while the backend is still extracting
  useEffect(() => {
    if (!doc || doc.processing_status !== "processing") return;
    const t = setInterval(async () => {
      try {
        const r = await getDocument(doc.id);
        setDoc(r.data);
      } catch {
        setError("Lost connection while waiting for extraction.");
      }
    }, POLL_MS);
    return () => clearInterval(t);
  }, [doc]);

  const handleUpload = async () => {
    if (!file || !patientId) return;
    setError("");
    setDoc(null);
    try {
      const r = await uploadDocument(patientId, file);
      setDoc(r.data);
    } catch (err) {
      setError(err.response?.data?.detail || "Upload failed.");
    }
  };

  const decide = async (status) => {
    await validateDocument(doc.id, { validation_status: status });
    setDoc((d) => ({ ...d, validation_status: status }));
  };

  const processing = doc?.processing_status === "processing";
  const x = doc?.extracted_data;

  return (
    <div className="page">
      <h2>Upload Medical Document</h2>

      <p className="text-muted">Uploading for <strong>{patient.name}</strong> (change patient in the top bar).</p>

      <div className="upload-zone" onClick={() => fileRef.current?.click()}>
        <UploadIcon size={48} />
        <p>{file ? file.name : "Click to choose a file"}</p>
        <span>PDF, JPG, PNG up to 15 MB — Prescriptions, Lab Reports, Discharge Summaries</span>
        <input ref={fileRef} type="file" accept=".pdf,.jpg,.jpeg,.png" hidden
               onChange={(e) => setFile(e.target.files[0])} />
      </div>

      <button className="btn btn-primary" onClick={handleUpload} disabled={!file || processing}>
        {processing ? <><Loader size={18} className="spin" /> Extracting...</> : <><FileUp size={18} /> Upload & Extract</>}
      </button>

      {error && <p className="text-danger">{error}</p>}

      {doc?.processing_status === "failed" && (
        <div className="card">
          <h3><XCircle size={18} /> Extraction failed</h3>
          <p>{doc.processing_error}</p>
          <p>The file was saved. You can retry once the problem (for example the API key or rate limit) is fixed.</p>
          <button className="btn" onClick={async () => setDoc((await reprocessDocument(doc.id)).data)}>Retry</button>
        </div>
      )}

      {doc?.processing_status === "done" && x && (
        <div className="extraction-result">
          <div className="card">
            <h3>Extracted Information</h3>
            <p><strong>Category:</strong> {x.category} &nbsp; <strong>Confidence:</strong> {Math.round((x.confidence || 0) * 100)}%</p>
            <p><strong>Doctor:</strong> {x.doctor || "—"} &nbsp; <strong>Facility:</strong> {x.hospital || "—"}</p>
            <p><strong>Date:</strong> {x.document_date || "—"} &nbsp; <strong>Follow-up:</strong> {x.follow_up_date || x.follow_up_text || "—"}</p>
            <InferredBanner list={x.inferred_generics} />
            {x.diagnoses?.length > 0 && <p><strong>Diagnoses:</strong> {x.diagnoses.join("; ")}</p>}

            {x.validation_issues?.length > 0 && (
              <p className="text-warning"><AlertTriangle size={16} /> Needs review: {x.validation_issues.join("; ")}</p>
            )}

            {x.medications?.length > 0 && (
              <table className="table">
                <thead><tr><th>Medication</th><th>Generic</th><th>Strength</th><th>Frequency</th><th>Timing</th><th>Duration</th></tr></thead>
                <tbody>
                  {x.medications.map((m, i) => (
                    <tr key={i}><td>{m.name}</td><td>{m.generic_name ? <GenericTag name={m.generic_name} brand="" inferred={m.generic_inferred} /> : "—"}</td><td>{m.strength || m.dosage || "—"}</td>
                      <td>{m.frequency || "—"}</td><td>{m.timing || "—"}</td><td>{m.duration || "—"}</td></tr>
                  ))}
                </tbody>
              </table>
            )}

            {x.lab_results?.length > 0 && (
              <table className="table">
                <thead><tr><th>Test</th><th>Result</th><th>Unit</th><th>Reference</th></tr></thead>
                <tbody>
                  {x.lab_results.map((l, i) => (
                    <tr key={i} className={l.is_abnormal ? "text-danger" : ""}>
                      <td>{l.test_name}</td><td><strong>{l.test_value}</strong> {l.flag || ""}</td>
                      <td>{l.unit || "—"}</td><td>{l.reference_range || "—"}</td></tr>
                  ))}
                </tbody>
              </table>
            )}

            <p><strong>Status:</strong> {doc.validation_status}</p>
            {doc.validation_status === "pending_review" && (
              <>
                <button className="btn btn-primary" onClick={() => decide("verified")}><CheckCircle size={16} /> Looks correct</button>{" "}
                <button className="btn" onClick={() => decide("rejected")}><XCircle size={16} /> Reject</button>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function UploadGate({ patient }) {
  const { canEdit } = usePatient();
  if (!canEdit) {
    return <p className="placeholder">You have view-only access to {patient.name}. Ask an owner for edit access to upload documents.</p>;
  }
  return <UploadForm patient={patient} />;
}

export default function UploadPage() {
  return <NeedPatient>{(p) => <UploadGate key={p.id} patient={p} />}</NeedPatient>;
}
