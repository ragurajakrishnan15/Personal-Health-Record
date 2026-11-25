import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { AlertTriangle, Camera, CheckCircle, FileUp, FolderOpen, Loader, ScanLine, XCircle } from "lucide-react";
import { uploadDocument, getDocument, reprocessDocument, validateDocument } from "../services/api";
import { usePatient } from "../context/PatientContext";
import NeedPatient from "../components/NeedPatient";
import GenericTag, { InferredBanner } from "../components/GenericTag";
import { useToast } from "../components/ui";
import { money } from "../lib/money";
import { errMsg } from "../lib/dates";

/** Choose or photograph a file -> background AI extraction (polled) -> check what was read -> accept or reject. */
const POLL_MS = 2000;
const MAX_BYTES = 15 * 1024 * 1024;
const ALLOWED = /\.(pdf|jpe?g|png)$/i;
const STEPS = ["Choose", "Reading", "Check"];

function Steps({ at }) {
  return (
    <ol className="steps" aria-label="Progress">
      {STEPS.map((label, i) => (
        <li key={label} className={i < at ? "done" : i === at ? "current" : ""} aria-current={i === at ? "step" : undefined}>{label}</li>
      ))}
    </ol>
  );
}

function UploadForm({ patient }) {
  const toast = useToast();
  const [file, setFile] = useState(null);
  const [preview, setPreview] = useState("");
  const [doc, setDoc] = useState(null);
  const [error, setError] = useState("");
  const [sending, setSending] = useState(false);
  const [dragging, setDragging] = useState(false);
  const fileRef = useRef();
  const cameraRef = useRef();

  useEffect(() => {
    if (!file || !file.type.startsWith("image/")) { setPreview(""); return; }
    const url = URL.createObjectURL(file);
    setPreview(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);

  // keep asking while the backend is still reading the document
  useEffect(() => {
    if (!doc || doc.processing_status !== "processing") return;
    const t = setInterval(async () => {
      try {
        const r = await getDocument(doc.id);
        setDoc(r.data);
        setError("");
      } catch {
        setError("Lost connection while the document was being read.");
      }
    }, POLL_MS);
    return () => clearInterval(t);
  }, [doc]);

  const pick = (f) => {
    if (!f) return;
    if (!ALLOWED.test(f.name)) return setError("Choose a PDF, JPG or PNG file.");
    if (f.size > MAX_BYTES) return setError("That file is larger than 15 MB. Choose a smaller one.");
    setError("");
    setDoc(null);
    setFile(f);
  };

  const processing = sending || doc?.processing_status === "processing";

  const handleUpload = async () => {
    if (!file) return;
    setError("");
    setDoc(null);
    setSending(true);
    try {
      setDoc((await uploadDocument(patient.id, file)).data);
    } catch (e) {
      setError(errMsg(e));
    } finally {
      setSending(false);
    }
  };

  const decide = async (status) => {
    try {
      await validateDocument(doc.id, { validation_status: status });
      setDoc((d) => ({ ...d, validation_status: status }));
      toast(status === "verified" ? "Marked as correct" : "Document rejected");
    } catch (e) {
      setError(errMsg(e));
    }
  };

  const retry = async () => {
    try { setDoc((await reprocessDocument(doc.id)).data); } catch (e) { setError(errMsg(e)); }
  };

  const reset = () => { setFile(null); setDoc(null); setError(""); };
  const x = doc?.extracted_data;
  const step = doc?.processing_status === "done" ? 2 : processing ? 1 : 0;
  const onInput = (e) => { pick(e.target.files[0]); e.target.value = ""; };

  return (
    <>
      <p className="text-muted">Adding to <strong>{patient.name}</strong>'s records. To add for someone else, switch person at the top.</p>
      <Steps at={step} />

      <button type="button" className={`upload-zone ${dragging ? "dragging" : ""}`} disabled={processing}
              onClick={() => fileRef.current.click()}
              onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
              onDragLeave={() => setDragging(false)}
              onDrop={(e) => { e.preventDefault(); setDragging(false); if (!processing) pick(e.dataTransfer.files[0]); }}>
        {preview ? <img src={preview} alt="Preview of the chosen file" className="upload-preview" /> : <ScanLine size={44} />}
        <strong>{file ? file.name : "Choose a record or bill"}</strong>
        <small>{file ? "Tap to choose a different file" : "PDF, JPG or PNG, up to 15 MB"}</small>
      </button>
      <input ref={fileRef} type="file" accept=".pdf,.jpg,.jpeg,.png" hidden onChange={onInput} />
      <input ref={cameraRef} type="file" accept="image/jpeg,image/png" capture="environment" hidden onChange={onInput} />

      <div className="upload-buttons">
        <button type="button" className="btn btn-outline" disabled={processing} onClick={() => cameraRef.current.click()}>
          <Camera size={18} /> Take photo
        </button>
        <button type="button" className="btn btn-outline" disabled={processing} onClick={() => fileRef.current.click()}>
          <FolderOpen size={18} /> Browse files
        </button>
        <button type="button" className="btn btn-primary" onClick={handleUpload} disabled={!file || processing || !!doc}>
          {processing ? <><Loader size={18} className="spin" /> Reading…</> : <><FileUp size={18} /> Upload and read</>}
        </button>
      </div>
      <p className="text-muted">The file is sent to an outside AI service to be read.</p>

      {error && <p className="text-danger" role="alert">{error}</p>}

      {doc?.processing_status === "failed" && (
        <div className="card">
          <h3><XCircle size={18} /> Could not read this document</h3>
          <p>{doc.processing_error}</p>
          <p>The file was saved, so you can try reading it again.</p>
          <div className="row-actions"><button className="btn btn-primary" onClick={retry}>Try again</button></div>
        </div>
      )}

      {doc?.processing_status === "done" && x && (
        <div className="card detail-card">
          <h3>What was read</h3>
          <p><strong>Type:</strong> {String(x.category).replace(/_/g, " ")}, <strong>confidence:</strong> {Math.round((x.confidence || 0) * 100)}%</p>
          <p><strong>Doctor:</strong> {x.doctor || "—"}</p>
          <p><strong>Facility:</strong> {x.hospital || "—"}</p>
          <p><strong>Date:</strong> {x.document_date || "—"}</p>
          <p><strong>Follow-up:</strong> {x.follow_up_date || x.follow_up_text || "—"}</p>
          {x.bill_total && <p><strong>Bill total:</strong> {money(x.bill_total, x.bill_currency)}</p>}
          <InferredBanner list={x.inferred_generics} />
          {x.diagnoses?.length > 0 && <p><strong>Diagnoses:</strong> {x.diagnoses.join("; ")}</p>}
          {x.validation_issues?.length > 0 && (
            <p className="text-warning"><AlertTriangle size={16} /> Please check: {x.validation_issues.join("; ")}</p>
          )}

          {x.medications?.length > 0 && (
            <div className="table-wrap">
              <table className="table">
                <thead><tr><th>Medication</th><th>Generic</th><th>Strength</th><th>Frequency</th><th>Timing</th><th>Duration</th></tr></thead>
                <tbody>
                  {x.medications.map((m, i) => (
                    <tr key={i}><td>{m.name}</td><td>{m.generic_name ? <GenericTag name={m.generic_name} brand="" inferred={m.generic_inferred} /> : "—"}</td><td>{m.strength || m.dosage || "—"}</td>
                      <td>{m.frequency || "—"}</td><td>{m.timing || "—"}</td><td>{m.duration || "—"}</td></tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {x.lab_results?.length > 0 && (
            <div className="table-wrap">
              <table className="table">
                <thead><tr><th>Test</th><th>Result</th><th>Unit</th><th>Reference</th></tr></thead>
                <tbody>
                  {x.lab_results.map((l, i) => (
                    <tr key={i} className={l.is_abnormal ? "row-abnormal" : ""}>
                      <td>{l.test_name}</td><td><strong>{l.test_value}</strong> {l.flag || ""}</td>
                      <td>{l.unit || "—"}</td><td>{l.reference_range || "—"}</td></tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <div className="row-actions">
            <a className="btn btn-outline" href={`/api/documents/${doc.id}/file`} target="_blank" rel="noreferrer">View original</a>
            {doc.validation_status === "pending_review" ? (
              <>
                <button className="btn btn-primary" onClick={() => decide("verified")}><CheckCircle size={16} /> Looks correct</button>
                <button className="btn btn-outline btn-danger-outline" onClick={() => decide("rejected")}><XCircle size={16} /> Reject</button>
              </>
            ) : (
              <>
                <button className="btn btn-primary" onClick={reset}>Add another</button>
                <Link className="btn btn-outline" to="/records">See all records</Link>
              </>
            )}
          </div>
        </div>
      )}
    </>
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
  return (
    <div className="page">
      <h2>Add a record</h2>
      <NeedPatient>{(p) => <UploadGate key={p.id} patient={p} />}</NeedPatient>
    </div>
  );
}
