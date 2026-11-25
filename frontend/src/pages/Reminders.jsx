import { useState } from "react";
import { Bell, BellPlus, Check, Repeat, Trash2 } from "lucide-react";
import { completeReminder, createReminder, deleteReminder, getMedications, getReminders } from "../services/api";
import useApi from "../hooks/useApi";
import useAddParam from "../hooks/useAddParam";
import { useToast } from "../components/ui";
import NeedPatient from "../components/NeedPatient";
import { usePatient } from "../context/PatientContext";
import { errMsg, prettyDate, todayLocal } from "../lib/dates";

const REPEAT = { none: "Does not repeat", daily: "Every day", weekly: "Every week", monthly: "Every month" };
const EMPTY = { title: "", due_date: todayLocal(), due_time: "", repeat: "none", notes: "", medication_id: "" };

function AddForm({ patientId, onDone, onCancel }) {
  const [f, setF] = useState(EMPTY);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const meds = useApi(() => getMedications(patientId, "active"), [patientId]);
  const set = (k) => (e) => setF((s) => ({ ...s, [k]: e.target.value }));

  // Picking a medicine pre-fills the title (and a daily repeat) as a convenience; both stay editable.
  const pickMed = (e) => {
    const id = e.target.value;
    const m = (meds.data || []).find((x) => String(x.id) === id);
    setF((s) => ({
      ...s, medication_id: id,
      title: m && !s.title ? `Take ${m.name}${m.strength ? ` ${m.strength}` : ""}` : s.title,
      repeat: m && s.repeat === "none" ? "daily" : s.repeat,
    }));
  };

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    setErr("");
    const body = Object.fromEntries(Object.entries(f).map(([k, v]) => [k, v === "" ? null : v]));
    if (body.medication_id) body.medication_id = Number(body.medication_id);
    try {
      await createReminder(patientId, body);
      onDone();
    } catch (ex) {
      setErr(errMsg(ex));
      setBusy(false);
    }
  };

  return (
    <form className="card" onSubmit={submit}>
      <div className="form-grid">
        <label className="form-span"><span>Medicine (optional)</span>
          <select className="select" value={f.medication_id} onChange={pickMed}>
            <option value="">Not about a medicine</option>
            {(meds.data || []).map((m) => <option key={m.id} value={m.id}>{m.name}{m.strength ? ` — ${m.strength}` : ""}</option>)}
          </select>
        </label>
        <label className="form-span"><span>Reminder</span>
          <input className="input" value={f.title} onChange={set("title")} maxLength={120} required placeholder="e.g. Take Metformin with breakfast" />
        </label>
        <label><span>Date</span><input className="input" type="date" value={f.due_date} onChange={set("due_date")} required /></label>
        <label><span>Time (optional)</span><input className="input" type="time" value={f.due_time} onChange={set("due_time")} /></label>
        <label className="form-span"><span>Repeat</span>
          <select className="select" value={f.repeat} onChange={set("repeat")}>
            {Object.entries(REPEAT).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </label>
      </div>
      {err && <p className="text-danger">{err}</p>}
      <div className="row-actions">
        <button className="btn btn-primary" disabled={busy}>Save reminder</button>
        <button type="button" className="btn btn-outline" onClick={onCancel}>Cancel</button>
      </div>
    </form>
  );
}

function List({ patient }) {
  const { canEdit } = usePatient();
  const [tab, setTab] = useState("active");
  const [adding, setAdding] = useState(false);
  const [confirmId, setConfirmId] = useState(null);
  const [err, setErr] = useState("");
  const rems = useApi(() => getReminders(patient.id, tab), [patient.id, tab]);
  const today = todayLocal();
  const toast = useToast();
  useAddParam(() => setAdding(true));

  const act = async (fn, ok) => {
    setErr("");
    try { await fn(); toast(ok); rems.reload(); } catch (ex) { setErr(errMsg(ex)); }
  };

  return (
    <>
      <p className="text-muted">
        Reminders appear here when you open the app. They are not sent to your phone or email.
      </p>
      {canEdit && !adding && (
        <p><button className="btn btn-primary" onClick={() => setAdding(true)}><BellPlus size={16} /> Add reminder</button></p>
      )}
      {adding && <AddForm patientId={patient.id} onCancel={() => setAdding(false)} onDone={() => { setAdding(false); rems.reload(); toast("Reminder saved"); }} />}

      <div className="tab-bar">
        {[["active", "Active"], ["done", "Done"]].map(([k, label]) => (
          <button key={k} className={`tab ${tab === k ? "active" : ""}`} onClick={() => setTab(k)}>{label}</button>
        ))}
      </div>
      {(rems.error || err) && <p className="text-danger">{rems.error || err}</p>}
      {rems.data?.length === 0 && <p className="placeholder">{tab === "active" ? "No active reminders." : "Nothing completed yet."}</p>}
      {(rems.data || []).map((r) => {
        const overdue = r.status === "active" && r.due_date < today;
        return (
          <div key={r.id} className={`card item-row ${overdue ? "item-overdue" : ""}`}>
            <Bell size={20} />
            <div className="item-main">
              <strong>{r.title}</strong>
              {overdue && <span className="badge badge-discontinued">overdue</span>}
              {r.status === "active" && r.due_date === today && <span className="badge badge-lapsed">today</span>}
              <p>{prettyDate(r.due_date)}{r.due_time && ` · ${r.due_time}`}</p>
              <p className="text-muted">
                {r.repeat !== "none" && <><Repeat size={12} /> {REPEAT[r.repeat]}</>}
                {r.medication_name && ` ${r.repeat !== "none" ? "· " : ""}${r.medication_name}`}
              </p>
            </div>
            {canEdit && (
              <div className="med-actions">
                {r.status === "active" && (
                  <button className="btn btn-outline" onClick={() => act(() => completeReminder(r.id), r.repeat === "none" ? "Reminder done" : "Done. Moved to the next date")}>
                    <Check size={14} /> {r.repeat === "none" ? "Done" : "Done, next"}
                  </button>
                )}
                {confirmId === r.id ? (
                  <button className="btn btn-danger" onClick={() => act(() => deleteReminder(r.id), "Reminder deleted")}>Confirm delete</button>
                ) : (
                  <button className="btn btn-outline btn-danger-outline" onClick={() => setConfirmId(r.id)}><Trash2 size={14} /> Delete</button>
                )}
              </div>
            )}
          </div>
        );
      })}
    </>
  );
}

export default function Reminders() {
  return (
    <div className="page">
      <h2>Reminders</h2>
      <NeedPatient>{(p) => <List key={p.id} patient={p} />}</NeedPatient>
    </div>
  );
}
