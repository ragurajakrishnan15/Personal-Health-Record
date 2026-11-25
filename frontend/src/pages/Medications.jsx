import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Skeleton, useToast } from "../components/ui";
import { errMsg } from "../lib/dates";
import { Pill } from "lucide-react";
import { getMedications, updateMedicationStatus } from "../services/api";
import useApi from "../hooks/useApi";
import NeedPatient from "../components/NeedPatient";
import { usePatient } from "../context/PatientContext";
import GenericTag from "../components/GenericTag";

const TABS = ["active", "lapsed", "completed", "superseded", "discontinued", "all"];
const TAB_LABEL = { lapsed: "To confirm" };
const BADGE = { lapsed: "not renewed" };

function MedList({ patient }) {
  const { canEdit } = usePatient();
  const [params, setParams] = useSearchParams();
  const filter = TABS.includes(params.get("tab")) ? params.get("tab") : "active";
  const meds = useApi(() => getMedications(patient.id), [patient.id]);
  const toast = useToast();
  const [error, setError] = useState("");
  const all = meds.data || [];
  const inTab = (tab) => (tab === "all" ? all : all.filter((m) => m.status === tab));
  const shown = inTab(filter);

  const setStatus = async (id, status) => {
    setError("");
    try {
      await updateMedicationStatus(id, status);
      toast(status === "active" ? "Marked as active" : "Marked as stopped");
      meds.reload();
    } catch (e) {
      setError(errMsg(e));
    }
  };

  return (
    <>
      <div className="chips" role="group" aria-label="Show medicines">
        {TABS.map((f) => (
          <button key={f} type="button" className={`chip ${filter === f ? "active" : ""}`} aria-pressed={filter === f}
                  onClick={() => setParams(f === "active" ? {} : { tab: f }, { replace: true })}>
            {TAB_LABEL[f] || f.charAt(0).toUpperCase() + f.slice(1)}
            {meds.data && <span className="chip-count">{inTab(f).length}</span>}
          </button>
        ))}
      </div>
      {meds.loading && !meds.data && <Skeleton />}
      {error && <p className="text-danger" role="alert">{error}</p>}
      {filter === "lapsed" && (
        <p className="text-muted">
          Long-term medicines whose last prescription has run out and no newer one is on file. They may still be taken
          (refills are often not recorded). Confirm each one.
        </p>
      )}
      {meds.error && <p className="text-danger">{meds.error}</p>}
      <div className="med-list">
        {meds.data && shown.length === 0 && (
          <p className="placeholder">No {filter === "all" ? "" : filter} medications. Upload a prescription to auto-extract them.</p>
        )}
        {shown.map((m) => (
          <div key={m.id} className="card med-card">
            <span className="row-icon"><Pill size={20} /></span>
            <div className="item-main">
              <strong>{m.name}</strong>
              <GenericTag name={m.generic_name} brand={m.name} inferred={m.generic_inferred} />
              {m.strength && <span> — {m.strength}</span>}
              <p>{[m.dosage, m.frequency, m.timing].filter(Boolean).join(" · ") || "No dosing details"}</p>
              <p className="text-muted">
                {m.start_date && `From ${m.start_date}`}
                {m.end_date && ` · until ${m.end_date}`}
                {m.prescribing_doctor && ` · ${m.prescribing_doctor}`}
              </p>
            </div>
            <div className="med-actions">
              <span className={`badge badge-${m.status}`}>{BADGE[m.status] || m.status}</span>
              {canEdit && m.status === "lapsed" && (
                <button className="btn btn-outline" onClick={() => setStatus(m.id, "active")}>Still taking</button>
              )}
              {canEdit && (m.status === "active" || m.status === "lapsed") && (
                <button className="btn btn-outline" onClick={() => setStatus(m.id, "discontinued")}>Stop</button>
              )}
              {canEdit && m.status === "discontinued" && (
                <button className="btn btn-outline" onClick={() => setStatus(m.id, "active")}>Reactivate</button>
              )}
            </div>
          </div>
        ))}
      </div>
    </>
  );
}

export default function Medications() {
  return (
    <div className="page">
      <h2>Medications</h2>
      <NeedPatient>{(p) => <MedList key={p.id} patient={p} />}</NeedPatient>
    </div>
  );
}
