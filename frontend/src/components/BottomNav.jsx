import { NavLink } from "react-router-dom";
import { Activity, FileText, LayoutDashboard, Menu, MessageSquare, Pill } from "lucide-react";

const tabs = [
  { to: "/", icon: LayoutDashboard, label: "Home", end: true },
  { to: "/records", icon: FileText, label: "Records" },
  { to: "/medications", icon: Pill, label: "Meds" },
  { to: "/chat", icon: MessageSquare, label: "Assistant" },
];

/** Thumb-reach navigation for phones (hidden on wide screens by CSS). "More" opens the full menu. */
export default function BottomNav({ onMore = () => {} }) {
  return (
    <nav className="bottom-nav" aria-label="Main">
      {tabs.map(({ to, icon: Icon, label, end }) => (
        <NavLink key={to} to={to} end={end} className={({ isActive }) => `bottom-tab ${isActive ? "active" : ""}`}>
          <Icon size={22} aria-hidden="true" />
          <span>{label}</span>
        </NavLink>
      ))}
      <button type="button" className="bottom-tab" onClick={onMore} aria-label="More pages">
        <Menu size={22} aria-hidden="true" />
        <span>More</span>
      </button>
    </nav>
  );
}
