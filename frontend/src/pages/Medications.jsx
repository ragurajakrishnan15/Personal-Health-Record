import { useState } from "react";
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
  const [filter, setFilter] = useState("active");
  const meds = useApi(() => getMedications(patient.id, filter === "all" ? undefined : filter), [patient.id, filter]);

  const setStatus = async (id, status) => {
    await updateMedicationStatus(id, status);
    meds.reload();
  };

  return (
    <>
      <div className="tab-bar">
        {TABS.map((f) => (
          <button key={f} className={`tab ${filter === f ? "active" : ""}`} onClick={() => setFilter(f)}>
            {TAB_LABEL[f] || f.charAt(0).toUpperCase() + f.slice(1)}
          </button>
        ))}
      </div>
      {filter === "lapsed" && (
        <p className="text-muted">
          Long-term medicines whose last prescription has run out and no newer one is on file. They may still be taken
          (refills are often not recorded). Confirm each one.
        </p>
      )}
      {meds.error && <p className="text-danger">{meds.error}</p>}
      <div className="med-list">
        {meds.data?.length === 0 && (
          <p className="placeholder">No {filter === "all" ? "" : filter} medications. Upload a prescription to auto-extract them.</p>
        )}
        {(meds.data || []).map((m) => (
          <div key={m.id} className="card med-card">
            <Pill size={20} />
            <div>
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
