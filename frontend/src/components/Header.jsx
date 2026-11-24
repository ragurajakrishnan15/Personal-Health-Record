import { LogOut, User } from "lucide-react";
import { usePatient } from "../context/PatientContext";
import { useAuth } from "../context/AuthContext";

const ROLE_LABEL = { owner: "Owner", editor: "Can edit", viewer: "View only" };

export default function Header() {
  const { patients, patient, select } = usePatient();
  const { user, logout } = useAuth();
  return (
    <header className="header">
      <h1 className="header-title">Personal & Family Health Records</h1>
      <div className="header-actions">
        {patients.length > 0 && (
          <label className="patient-switch">
            <User size={16} />
            <select aria-label="Select patient" className="select" value={patient?.id ?? ""}
                    onChange={(e) => select(Number(e.target.value))}>
              {patients.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
            {patient?.role && <span className={`badge role-badge role-${patient.role}`}>{ROLE_LABEL[patient.role]}</span>}
          </label>
        )}
        <span className="header-user" title={user.email}>{user.name}</span>
        <button className="btn btn-outline" onClick={logout} title="Sign out"><LogOut size={14} /> Sign out</button>
      </div>
    </header>
  );
}
