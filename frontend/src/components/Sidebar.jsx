import { NavLink, Link } from "react-router-dom";
import { Activity, Plus } from "lucide-react";
import { usePatient } from "../context/PatientContext";
import { PAGES } from "./nav";

/** Wide-screen navigation. Phones use BottomNav. */
export default function Sidebar() {
  const { canEdit } = usePatient();
  return (
    <aside className="sidebar">
      <div className="sidebar-brand"><span className="brand-mark"><Activity size={20} /></span> HealthVault</div>
      {canEdit && <Link to="/upload" className="btn btn-primary"><Plus size={18} /> Upload record</Link>}
      <nav aria-label="Main">
        {PAGES.map(({ to, icon: Icon, label }) => (
          <NavLink key={to} to={to} end={to === "/"} className={({ isActive }) => `sidebar-link ${isActive ? "active" : ""}`}>
            <Icon size={19} aria-hidden="true" /> <span>{label}</span>
          </NavLink>
        ))}
      </nav>
    </aside>
  );
}
