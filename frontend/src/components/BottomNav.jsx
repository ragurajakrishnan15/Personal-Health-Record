import { useState } from "react";
import { Link, NavLink, useLocation } from "react-router-dom";
import { FileText, LayoutDashboard, LogOut, Menu, MessageSquare, Plus } from "lucide-react";
import { useAuth } from "../context/AuthContext";
import { usePatient } from "../context/PatientContext";
import { ADD_ACTIONS, PAGES } from "./nav";
import { Sheet } from "./ui";

function Tab({ to, icon: Icon, label }) {
  return (
    <NavLink to={to} end={to === "/"} className={({ isActive }) => `bottom-tab ${isActive ? "active" : ""}`}>
      <span className="pill"><Icon size={22} aria-hidden="true" /></span> {label}
    </NavLink>
  );
}

/** Thumb-reach navigation for phones: four places plus a central Add button (hidden on wide screens by CSS). */
export default function BottomNav() {
  const [sheet, setSheet] = useState(null);          // null | "add" | "more"
  const { canEdit, patient } = usePatient();
  const { user, logout } = useAuth();
  const { pathname } = useLocation();
  const close = () => setSheet(null);

  return (
    <>
      <nav className="bottom-nav" aria-label="Main">
        <Tab to="/" icon={LayoutDashboard} label="Home" />
        <Tab to="/records" icon={FileText} label="Records" />
        <button type="button" className="bottom-tab bottom-add" onClick={() => setSheet("add")} aria-haspopup="dialog">
          <span className="fab"><Plus size={28} aria-hidden="true" /></span> Add
        </button>
        <Tab to="/chat" icon={MessageSquare} label="Assistant" />
        <button type="button" className="bottom-tab" onClick={() => setSheet("more")} aria-haspopup="dialog">
          <span className="pill"><Menu size={22} aria-hidden="true" /></span> More
        </button>
      </nav>

      <Sheet open={sheet === "add"} onClose={close} title={patient ? `Add for ${patient.name.split(" ")[0]}` : "Add"}>
        {canEdit ? ADD_ACTIONS.map(({ to, icon: Icon, label, hint }) => (
          <Link key={to} to={to} className="sheet-option" onClick={close}>
            <span className="row-icon"><Icon size={20} /></span>
            <span className="grow"><strong>{label}</strong><small>{hint}</small></span>
          </Link>
        )) : (
          <p className="placeholder">
            {patient ? `You can view ${patient.name}'s records but not add to them. Ask an owner for edit access.` : "Add a family member first."}
          </p>
        )}
      </Sheet>

      <Sheet open={sheet === "more"} onClose={close} title="All pages">
        <div className="menu-grid">
          {PAGES.map(({ to, icon: Icon, label }) => (
            <Link key={to} to={to} className="quick" onClick={close} aria-current={pathname === to ? "page" : undefined}>
              <Icon size={22} aria-hidden="true" /> {label}
            </Link>
          ))}
        </div>
        <button type="button" className="btn btn-outline btn-block" onClick={logout}>
          <LogOut size={16} /> Sign out of {user.email}
        </button>
      </Sheet>
    </>
  );
}
