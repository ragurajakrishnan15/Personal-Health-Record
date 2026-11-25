import { useState } from "react";
import { Link } from "react-router-dom";
import { Check, ChevronDown, Moon, Search, Sun, UserPlus } from "lucide-react";
import { usePatient } from "../context/PatientContext";
import { setTheme } from "../lib/theme";
import { Avatar, Sheet } from "./ui";

const ROLE_LABEL = { owner: "Owner", editor: "Can edit", viewer: "View only" };

/** Who you are looking at. Tapping it opens the family switcher. */
export default function Header() {
  const { patients, patient, select } = usePatient();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [dark, setDark] = useState(() => document.documentElement.dataset.theme === "dark");
  const shown = patients.filter((p) => p.name.toLowerCase().includes(query.trim().toLowerCase()));
  const close = () => { setOpen(false); setQuery(""); };
  const flip = () => { setTheme(dark ? "light" : "dark"); setDark(!dark); };

  return (
    <header className="header">
      {patient ? (
        <button type="button" className="person-chip" onClick={() => setOpen(true)} aria-haspopup="dialog"
                aria-label={`Viewing ${patient.name}. Switch family member`}>
          <Avatar person={patient} />
          <span className="person-chip-text">
            <strong>{patient.name}</strong>
            <small>{ROLE_LABEL[patient.role]}</small>
          </span>
          <ChevronDown size={18} aria-hidden="true" />
        </button>
      ) : <span className="brand">HealthVault</span>}
      <div className="header-actions">
        <button type="button" className="icon-btn" onClick={flip} aria-label={dark ? "Use light mode" : "Use dark mode"}>
          {dark ? <Sun size={19} /> : <Moon size={19} />}
        </button>
      </div>

      <Sheet open={open} onClose={close} title="Switch person">
        {patients.length > 6 && (
          <div className="filter-bar">
            <div className="search">
              <Search size={18} />
              <input className="input" placeholder="Search family" aria-label="Search family members"
                     value={query} onChange={(e) => setQuery(e.target.value)} />
            </div>
          </div>
        )}
        {shown.map((p) => (
          <button key={p.id} type="button" className="sheet-option" aria-current={p.id === patient?.id}
                  onClick={() => { select(p.id); close(); }}>
            <Avatar person={p} />
            <span className="grow">
              <strong>{p.name}</strong>
              <small>{[p.age && `${p.age} years`, ROLE_LABEL[p.role]].filter(Boolean).join(", ")}</small>
            </span>
            {p.id === patient?.id && <Check size={20} aria-label="Selected" />}
          </button>
        ))}
        {shown.length === 0 && <p className="placeholder">No one matches that name.</p>}
        <Link to="/patients" className="sheet-option" onClick={close}>
          <span className="row-icon"><UserPlus size={20} /></span>
          <span className="grow"><strong>Manage family</strong><small>Add, share or export</small></span>
        </Link>
      </Sheet>
    </header>
  );
}
