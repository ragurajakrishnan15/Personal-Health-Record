import { Calendar } from "lucide-react";

/**
 * Appointments & Follow-ups
 *
 * TODO:
 * - Upcoming appointments list
 * - Past appointments
 * - Add appointment form
 * - Auto-extracted follow-up dates from prescriptions
 * - Doctor/hospital info
 * - Attach records to appointments
 * - Reminder settings
 */

export default function Appointments() {
  return (
    <div className="page">
      <h2>Appointments</h2>
      <div className="card">
        <Calendar size={48} />
        <p className="placeholder">Appointment management coming soon.</p>
        <p className="text-muted">Follow-up dates will be auto-extracted from prescriptions.</p>
      </div>
    </div>
  );
}
