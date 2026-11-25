import { useState } from "react";
import { CalendarCheck, CalendarPlus, Check, Trash2 } from "lucide-react";
import {
  createAppointment, deleteAppointment, getAppointments, getAppointmentSuggestions, updateAppointment,
} from "../services/api";
import useApi from "../hooks/useApi";
import useAddParam from "../hooks/useAddParam";
import { useToast } from "../components/ui";
import NeedPatient from "../components/NeedPatient";
import { usePatient } from "../context/PatientContext";
import { errMsg, prettyDate, todayLocal } from "../lib/dates";

const EMPTY = { title: "", appt_date: "", appt_time: "", doctor: "", location: "", notes: "" };

function AddForm({ patientId, initial, consultationId, onDone, onCancel }) {
  const [f, setF] = useState({ ...EMPTY, ...initial });
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const set = (k) => (e) => setF((s) => ({ ...s, [k]: e.target.value }));

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    setErr("");
    const body = Object.fromEntries(Object.entries(f).map(([k, v]) => [k, v === "" ? null : v]));
    if (consultationId) body.consultation_id = consultationId;
    try {
      await createAppointment(patientId, body);
      onDone();
    } catch (ex) {
      setErr(errMsg(ex));
      setBusy(false);
    }
  };

  return (
    <form className="card" onSubmit={submit}>
      <div className="form-grid">
        <label className="form-span"><span>Title</span>
          <input className="input" value={f.title} onChange={set("title")} maxLength={120} required placeholder="e.g. Diabetes follow-up" />
        </label>
        <label><span>Date</span><input className="input" type="date" value={f.appt_date} onChange={set("appt_date")} required /></label>
        <label><span>Time (optional)</span><input className="input" type="time" value={f.appt_time} onChange={set("appt_time")} /></label>
        <label><span>Doctor</span><input className="input" value={f.doctor} onChange={set("doctor")} maxLength={120} /></label>
        <label><span>Location</span><input className="input" value={f.location} onChange={set("location")} maxLength={200} /></label>
        <label className="form-span"><span>Notes</span>
          <input className="input" value={f.notes} onChange={set("notes")} maxLength={1000} />
        </label>
      </div>
      {err && <p className="text-danger">{err}</p>}
      <div className="row-actions">
        <button className="btn btn-primary" disabled={busy}>Save appointment</button>
        <button type="button" className="btn btn-outline" onClick={onCancel}>Cancel</button>
      </div>
    </form>
  );
}

function List({ patient }) {
  const { canEdit } = usePatient();
  const [tab, setTab] = useState("upcoming");
  const [adding, setAdding] = useState(null);          // null | {initial, consultationId}
  const [confirmId, setConfirmId] = useState(null);
  const [err, setErr] = useState("");
  const appts = useApi(() => getAppointments(patient.id, tab), [patient.id, tab]);
  const sugg = useApi(() => getAppointmentSuggestions(patient.id), [patient.id]);
  const today = todayLocal();
  const toast = useToast();
  useAddParam(() => setAdding({ initial: {} }));

  const refresh = () => { appts.reload(); sugg.reload(); };
  const act = async (fn) => {
    setErr("");
    try { await fn(); refresh(); } catch (ex) { setErr(errMsg(ex)); }
  };

  return (
    <>
      {canEdit && !adding && (
        <p><button className="btn btn-primary" onClick={() => setAdding({ initial: {} })}><CalendarPlus size={16} /> Add appointment</button></p>
      )}
      {adding && (
        <AddForm
          patientId={patient.id}
          initial={adding.initial}
          consultationId={adding.consultationId}
          onCancel={() => setAdding(null)}
          onDone={() => { setAdding(null); refresh(); toast("Appointment saved"); }}
        />
      )}

      {(sugg.data || []).length > 0 && (
        <div className="card suggest-card">
          <h3>Follow-ups found in documents</h3>
          <p className="text-muted">Dates were read from uploaded records by AI. Check them against the original before relying on them.</p>
          {sugg.data.map((s) => (
            <div key={s.consultation_id} className="item-row">
              <div>
                <strong>{prettyDate(s.date)}</strong>
                <span className="text-muted">{[s.doctor, s.hospital].filter(Boolean).map((x) => ` · ${x}`).join("")}</span>
              </div>
              {canEdit && (
                <button className="btn btn-outline" onClick={() => setAdding({
                  consultationId: s.consultation_id,
                  initial: { title: "Follow-up", appt_date: s.date, doctor: s.doctor || "", location: s.hospital || "" },
                })}>Add to appointments</button>
              )}
            </div>
          ))}
        </div>
      )}

      <div className="tab-bar">
        {[["upcoming", "Upcoming"], ["past", "History"]].map(([k, label]) => (
          <button key={k} className={`tab ${tab === k ? "active" : ""}`} onClick={() => setTab(k)}>{label}</button>
        ))}
      </div>
      {(appts.error || err) && <p className="text-danger">{appts.error || err}</p>}
      {appts.data?.length === 0 && (
        <p className="placeholder">{tab === "upcoming" ? "No upcoming appointments." : "No past appointments yet."}</p>
      )}
      {(appts.data || []).map((a) => (
        <div key={a.id} className="card item-row">
          <CalendarCheck size={20} />
          <div className="item-main">
            <strong>{a.title}</strong>
            {a.status !== "scheduled" && <span className={`badge badge-${a.status === "done" ? "completed" : "discontinued"}`}>{a.status}</span>}
            {a.status === "scheduled" && a.appt_date === today && <span className="badge badge-lapsed">today</span>}
            <p>{prettyDate(a.appt_date)}{a.appt_time && ` · ${a.appt_time}`}</p>
            <p className="text-muted">{[a.doctor, a.location].filter(Boolean).join(" · ")}</p>
            {a.notes && <p className="text-muted">{a.notes}</p>}
          </div>
          {canEdit && (
            <div className="med-actions">
              {a.status === "scheduled" && (
                <>
                  <button className="btn btn-outline" onClick={() => act(() => updateAppointment(a.id, { status: "done" }))}><Check size={14} /> Done</button>
                  <button className="btn btn-outline" onClick={() => act(() => updateAppointment(a.id, { status: "cancelled" }))}>Cancel</button>
                </>
              )}
              {confirmId === a.id ? (
                <button className="btn btn-danger" onClick={() => act(() => deleteAppointment(a.id))}>Confirm delete</button>
              ) : (
                <button className="btn btn-outline btn-danger-outline" onClick={() => setConfirmId(a.id)}><Trash2 size={14} /> Delete</button>
              )}
            </div>
          )}
        </div>
      ))}
    </>
  );
}

export default function Appointments() {
  return (
    <div className="page">
      <h2>Appointments</h2>
      <NeedPatient>{(p) => <List key={p.id} patient={p} />}</NeedPatient>
    </div>
  );
}
