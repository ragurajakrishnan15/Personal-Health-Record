import { Link } from "react-router-dom";
import { usePatient } from "../context/PatientContext";

/** Renders children only when a patient is selected; otherwise a helpful empty state. */
export default function NeedPatient({ children }) {
  const { patient, loading, error } = usePatient();
  if (loading) return <p className="placeholder">Loading…</p>;
  if (error) return <p className="text-danger">{error}</p>;
  if (!patient) {
    return <p className="placeholder">No patient yet. <Link to="/patients">Add a family member</Link> to get started.</p>;
  }
  return children(patient);
}
