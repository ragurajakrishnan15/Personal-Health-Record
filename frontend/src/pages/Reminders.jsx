import { Bell } from "lucide-react";

/**
 * Medication Reminders & Adherence
 *
 * TODO:
 * - Today's medication schedule
 * - Acknowledge buttons (Taken / Snooze / Skip)
 * - Adherence calendar/heatmap
 * - Escalation config
 * - Family notification settings
 * - Missed dose history
 */

export default function Reminders() {
  return (
    <div className="page">
      <h2>Reminders</h2>
      <div className="card">
        <Bell size={48} />
        <p className="placeholder">Medication reminders & adherence tracking coming soon.</p>
        <p className="text-muted">Set up schedules, get reminders, track adherence.</p>
      </div>
    </div>
  );
}
