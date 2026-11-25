import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { UserPlus, Check, Share2, X, Download, Trash2 } from "lucide-react";
import { changeAccess, createPatient, deletePatient, exportPatient, getAccess, grantAccess, revokeAccess } from "../services/api";
import { usePatient } from "../context/PatientContext";
import { Avatar } from "../components/ui";

const BLOOD = ["", "A+", "A-", "B+", "B-", "O+", "O-", "AB+", "AB-"];
const EMPTY = { name: "", age: "", gender: "", blood_group: "", phone: "", email: "" };

function AddForm({ onDone, onCancel }) {
  const [f, setF] = useState(EMPTY);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });

  const submit = async (e) => {
    e.preventDefault();
    if (!f.name.trim()) return setErr("Name is required.");
    const age = f.age === "" ? null : Number(f.age);
    if (age !== null && (!Number.isInteger(age) || age < 0 || age > 120)) return setErr("Enter a valid age (0-120).");
    setBusy(true);
    try {
      const { data } = await createPatient({
        name: f.name.trim(), age, gender: f.gender || null, blood_group: f.blood_group || null,
        phone: f.phone || null, email: f.email || null,
      });
      onDone(data);
    } catch (e2) {
      setErr(e2.response?.data?.detail?.[0]?.msg || "Could not save. Check the details and try again.");
      setBusy(false);
    }
  };

  return (
    <form className="card form-grid" onSubmit={submit}>
      <label>Full name *<input className="input" value={f.name} onChange={set("name")} autoFocus /></label>
      <label>Age<input className="input" type="number" min="0" max="120" value={f.age} onChange={set("age")} /></label>
      <label>Gender
        <select className="select" value={f.gender} onChange={set("gender")}>
          <option value="">—</option><option>Male</option><option>Female</option><option>Other</option>
        </select>
      </label>
      <label>Blood group
        <select className="select" value={f.blood_group} onChange={set("blood_group")}>
          {BLOOD.map((b) => <option key={b} value={b}>{b || "—"}</option>)}
        </select>
      </label>
      <label>Phone<input className="input" value={f.phone} onChange={set("phone")} /></label>
      <label>Email<input className="input" type="email" value={f.email} onChange={set("email")} /></label>
      {err && <p className="text-danger form-span">{err}</p>}
      <div className="form-span">
        <button className="btn btn-primary" disabled={busy}>{busy ? "Saving…" : "Save member"}</button>{" "}
        <button type="button" className="btn btn-outline" onClick={onCancel}>Cancel</button>
      </div>
    </form>
  );
}


const ROLES = [["viewer", "View only"], ["editor", "Can edit"], ["owner", "Owner"]];
const ROLE_LABEL = Object.fromEntries(ROLES);
const apiError = (e) => (typeof e.response?.data?.detail === "string" ? e.response.data.detail : "Something went wrong.");

/** Owner-only: who can see this patient, and what they may do. Changes take effect immediately. */
function SharePanel({ patient, onClose }) {
  const [people, setPeople] = useState([]);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState("viewer");
  const [msg, setMsg] = useState({ text: "", bad: false });
  const reload = () => getAccess(patient.id).then((r) => setPeople(r.data)).catch((e) => setMsg({ text: apiError(e), bad: true }));
  useEffect(() => { reload(); }, [patient.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const run = async (fn, ok) => {
    try { await fn(); setMsg({ text: ok, bad: false }); await reload(); } catch (e) { setMsg({ text: apiError(e), bad: true }); }
  };

  return (
    <div className="card share-panel">
      <div className="page-header">
        <h3>Who can access {patient.name}</h3>
        <button className="icon-btn" onClick={onClose} aria-label="Close"><X size={16} /></button>
      </div>
      <table className="table">
        <thead><tr><th>Person</th><th>Access</th><th /></tr></thead>
        <tbody>
          {people.map((a) => (
            <tr key={a.user_id}>
              <td>{a.name}<div className="text-muted">{a.email}</div></td>
              <td>
                <select className="select" value={a.role} aria-label={`Access for ${a.name}`}
                        onChange={(e) => run(() => changeAccess(patient.id, a.user_id, e.target.value), "Access updated.")}>
                  {ROLES.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
                </select>
              </td>
              <td><button className="btn btn-outline" onClick={() => run(() => revokeAccess(patient.id, a.user_id), "Access removed.")}>Remove</button></td>
            </tr>
          ))}
        </tbody>
      </table>
      <form className="share-add" onSubmit={(e) => { e.preventDefault(); run(() => grantAccess(patient.id, email, role).then(() => setEmail("")), "Shared."); }}>
        <input className="input" type="email" required placeholder="Email of a registered user" aria-label="Email to share with"
               value={email} onChange={(e) => setEmail(e.target.value)} />
        <select className="select" value={role} onChange={(e) => setRole(e.target.value)} aria-label="Role">
          {ROLES.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
        </select>
        <button className="btn btn-primary"><Share2 size={14} /> Share</button>
      </form>
      <p className="text-muted share-hint">
        View only can read records and ask the assistant. Can edit also uploads and reviews documents. Owners also manage
        sharing. The person needs an account first.
      </p>
      {msg.text && <p className={msg.bad ? "text-danger" : "text-success"} role="status">{msg.text}</p>}
    </div>
  );
}

/** Download everything about a person as one ZIP (data + original files). Owner only. */
async function downloadExport(patient, setMsg) {
  try {
    const { data, headers } = await exportPatient(patient.id);
    const name = /filename="?([^";]+)"?/.exec(headers["content-disposition"] || "")?.[1] || `healthvault-export-${patient.id}.zip`;
    const url = URL.createObjectURL(data);
    const a = document.createElement("a");
    a.href = url;
    a.download = name;
    a.click();
    URL.revokeObjectURL(url);
    setMsg({ text: "Export downloaded. It contains sensitive health information - keep it safe.", bad: false });
  } catch (e) {
    setMsg({ text: e.response?.status === 429 ? "Too many exports. Try again later." : "Export failed. Try again.", bad: true });
  }
}

/** Permanent erasure. Requires the exact name and the owner's password. */
function DeletePanel({ patient, onClose, onDeleted, onExport }) {
  const [name, setName] = useState("");
  const [pw, setPw] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const ready = name.trim() === patient.name.trim() && pw.length > 0;

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    setErr("");
    try {
      await deletePatient(patient.id, name, pw);
      onDeleted();
    } catch (e2) {
      setErr(apiError(e2));
      setBusy(false);
    }
  };

  return (
    <form className="card delete-panel" onSubmit={submit}>
      <div className="page-header">
        <h3>Delete {patient.name} permanently</h3>
        <button type="button" className="icon-btn" onClick={onClose} aria-label="Close"><X size={16} /></button>
      </div>
      <p>
        This erases every document, medication, lab result, visit, allergy and chat for {patient.name}, for everyone it is
        shared with. It cannot be undone. Text already sent to the AI provider for answers cannot be recalled from here.
      </p>
      <p><button type="button" className="btn btn-outline" onClick={onExport}><Download size={14} /> Download a copy first</button></p>
      <label>
        <span>Type <strong>{patient.name}</strong> to confirm</span>
        <input className="input" value={name} onChange={(e) => setName(e.target.value)} autoComplete="off" />
      </label>
      <label>Your password
        <input className="input" type="password" value={pw} onChange={(e) => setPw(e.target.value)} autoComplete="current-password" />
      </label>
      {err && <p className="text-danger" role="alert">{err}</p>}
      <div>
        <button className="btn btn-danger" disabled={!ready || busy}><Trash2 size={14} /> {busy ? "Deleting…" : "Delete forever"}</button>{" "}
        <button type="button" className="btn btn-outline" onClick={onClose}>Cancel</button>
      </div>
    </form>
  );
}

export default function Patients() {
  const { patients, patient, select, refresh, error } = usePatient();
  const [showForm, setShowForm] = useState(false);
  const [sharing, setSharing] = useState(null);
  const [deleting, setDeleting] = useState(null);
  const [note, setNote] = useState({ text: "", bad: false });
  const nav = useNavigate();

  const added = async (p) => {
    await refresh();
    select(p.id);
    setShowForm(false);
  };

  return (
    <div className="page">
      <div className="page-header">
        <h2>Family Members</h2>
        <button className="btn btn-primary" onClick={() => setShowForm(true)}><UserPlus size={18} /> Add Member</button>
      </div>
      {error && <p className="text-danger">{error}</p>}
      {note.text && <p className={note.bad ? "text-danger" : "text-success"} role="status">{note.text}</p>}
      {showForm && <AddForm onDone={added} onCancel={() => setShowForm(false)} />}
      {sharing && patients.find((p) => p.id === sharing) && (
        <SharePanel patient={patients.find((p) => p.id === sharing)} onClose={() => setSharing(null)} />
      )}

      {deleting && patients.find((p) => p.id === deleting) && (
        <DeletePanel patient={patients.find((p) => p.id === deleting)} onClose={() => setDeleting(null)}
                     onExport={() => downloadExport(patients.find((p) => p.id === deleting), setNote)}
                     onDeleted={async () => { setDeleting(null); setNote({ text: "Deleted permanently.", bad: false }); await refresh(); }} />
      )}

      <div className="patient-grid">
        {patients.length === 0 && !showForm && <p className="placeholder">No family members yet. Add one to get started.</p>}
        {patients.map((p) => (
          <div key={p.id} className={`card patient-card ${p.id === patient?.id ? "selected" : ""}`}>
            <div className="patient-head">
              <Avatar person={p} />
              <div>
                <h3>{p.name}</h3>
                <span className={`badge role-${p.role}`} style={{ marginLeft: 0 }}>{ROLE_LABEL[p.role]}</span>
              </div>
            </div>
            <p>{p.age ? `${p.age} yrs` : "Age not set"} {p.gender ? `· ${p.gender}` : ""}</p>
            <p>{p.blood_group || "Blood group not set"}</p>
            {p.phone && <p className="text-muted">{p.phone}</p>}
            <button className="btn btn-outline" onClick={() => { select(p.id); nav("/"); }}>
              {p.id === patient?.id ? <><Check size={14} /> Selected · open overview</> : "View records"}
            </button>
            {p.role === "owner" && (
              <button className="btn btn-outline" onClick={() => setSharing(sharing === p.id ? null : p.id)}>
                <Share2 size={14} /> Share
              </button>
            )}
            {p.role === "owner" && (
              <>
                <button className="btn btn-outline" onClick={() => downloadExport(p, setNote)}><Download size={14} /> Export</button>
                <button className="btn btn-outline btn-danger-outline" onClick={() => { setDeleting(p.id); setSharing(null); }}>
                  <Trash2 size={14} /> Delete
                </button>
              </>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
