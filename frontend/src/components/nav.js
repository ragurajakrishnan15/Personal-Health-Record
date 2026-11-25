/** One list of pages and "add" actions, shared by the sidebar and the phone menus. */
import {
  Activity, Bell, BellPlus, Calendar, CalendarPlus, FileText, LayoutDashboard, MessageSquare, Pill, ScanLine, Settings, Users, Wallet,
} from "lucide-react";

export const PAGES = [
  { to: "/", icon: LayoutDashboard, label: "Home" },
  { to: "/records", icon: FileText, label: "Records" },
  { to: "/medications", icon: Pill, label: "Medications" },
  { to: "/analytics", icon: Activity, label: "Lab trends" },
  { to: "/chat", icon: MessageSquare, label: "Assistant" },
  { to: "/appointments", icon: Calendar, label: "Appointments" },
  { to: "/reminders", icon: Bell, label: "Reminders" },
  { to: "/expenses", icon: Wallet, label: "Expenses" },
  { to: "/patients", icon: Users, label: "Family" },
  { to: "/settings", icon: Settings, label: "Settings" },
];

export const ADD_ACTIONS = [
  { to: "/upload", icon: ScanLine, label: "Scan or upload", hint: "Prescription, lab report or bill" },
  { to: "/expenses?add=1", icon: Wallet, label: "Add expense", hint: "A cost without a bill" },
  { to: "/appointments?add=1", icon: CalendarPlus, label: "Add appointment", hint: "A visit or test" },
  { to: "/reminders?add=1", icon: BellPlus, label: "Add reminder", hint: "Shown when you open the app" },
];
