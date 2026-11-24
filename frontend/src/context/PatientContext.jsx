import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { getPatients } from "../services/api";
import { useAuth } from "./AuthContext";

/** Shared "who are we looking at" state. Every page reads the selected patient from here. */
const Ctx = createContext(null);
export const usePatient = () => useContext(Ctx);

const KEY = "phr.patientId";
const readSaved = () => {
  try { return Number(localStorage.getItem(KEY)) || null; } catch { return null; }
};

export function PatientProvider({ children }) {
  const { user } = useAuth();
  const [patients, setPatients] = useState([]);
  const [patientId, setPatientId] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    try {
      const { data } = await getPatients();
      setPatients(data);
      setError("");
      setPatientId((cur) => {
        if (cur && data.some((p) => p.id === cur)) return cur;
        const saved = readSaved();
        return data.find((p) => p.id === saved)?.id ?? data[0]?.id ?? null;
      });
    } catch {
      setError("Cannot reach the backend. Start it with: python main.py (port 8000).");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (user) {
      setLoading(true);
      refresh();
    } else {                                   // signed out: drop every patient from memory and storage
      setPatients([]);
      setPatientId(null);
      setLoading(false);
      try { localStorage.removeItem(KEY); } catch { /* storage unavailable */ }
    }
  }, [user, refresh]);

  const select = useCallback((id) => {
    setPatientId(id);
    try { localStorage.setItem(KEY, String(id)); } catch { /* storage unavailable */ }
  }, []);

  const value = useMemo(() => {
    const patient = patients.find((p) => p.id === patientId) || null;
    // viewers (for example a doctor with read-only access) must not be offered write actions; the server enforces it too
    const canEdit = patient?.role === "owner" || patient?.role === "editor";
    return { patients, patient, select, refresh, loading, error, canEdit };
  }, [patients, patientId, select, refresh, loading, error]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}
