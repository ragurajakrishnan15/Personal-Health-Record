import { NavLink } from "react-router-dom";
import {
  LayoutDashboard,
  Users,
  FileText,
  Pill,
  Activity,
  MessageSquare,
  Calendar,
  Bell,
  Settings,
  Upload,
} from "lucide-react";

const links = [
  { to: "/", icon: LayoutDashboard, label: "Dashboard" },
  { to: "/patients", icon: Users, label: "Family" },
  { to: "/records", icon: FileText, label: "Records" },
  { to: "/upload", icon: Upload, label: "Upload" },
  { to: "/medications", icon: Pill, label: "Medications" },
  { to: "/analytics", icon: Activity, label: "Analytics" },
  { to: "/chat", icon: MessageSquare, label: "AI Assistant" },
  { to: "/appointments", icon: Calendar, label: "Appointments" },
  { to: "/reminders", icon: Bell, label: "Reminders" },
  { to: "/settings", icon: Settings, label: "Settings" },
];

export default function Sidebar({ open = false, onClose = () => {} }) {
  return (
    <>
    <div className={`sidebar-backdrop ${open ? "show" : ""}`} onClick={onClose} aria-hidden="true" />
    <aside className={`sidebar ${open ? "open" : ""}`}>
      <div className="sidebar-brand">
        <Activity size={28} />
        <span>HealthVault</span>
      </div>
      <nav>
        {links.map(({ to, icon: Icon, label }) => (
          <NavLink
            key={to}
            to={to}
            onClick={onClose}
            className={({ isActive }) =>
              `sidebar-link ${isActive ? "active" : ""}`
            }
          >
            <Icon size={20} />
            <span>{label}</span>
          </NavLink>
        ))}
      </nav>
    </aside>
    </>
  );
}
