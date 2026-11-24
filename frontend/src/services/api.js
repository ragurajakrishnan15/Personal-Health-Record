/**
 * API service — all backend calls go through here.
 * Base URL switches between dev proxy and production.
 */
import axios from "axios";

const api = axios.create({
  baseURL: "/api",
});

// Any 401 from a data call means the session ended (expired, signed out elsewhere, password changed):
// tell the app so it can show the sign-in page. The login/register/me calls handle their own 401s.
api.interceptors.response.use(
  (r) => r,
  (err) => {
    const url = err.config?.url || "";
    if (err.response?.status === 401 && !url.startsWith("/auth/")) window.dispatchEvent(new Event("phr:unauthorized"));
    return Promise.reject(err);
  },
);

// ── Auth ──────────────────────────────────────────────
export const login = (email, password) => api.post("/auth/login", { email, password });
export const register = (email, name, password) => api.post("/auth/register", { email, name, password });
export const logout = () => api.post("/auth/logout");
export const getMe = () => api.get("/auth/me");
export const verifyEmail = (token) => api.post("/auth/verify-email", { token });
export const resendVerification = () => api.post("/auth/resend-verification");
export const exportPatient = (id) => api.get(`/patients/${id}/export`, { responseType: "blob" });
export const deletePatient = (id, confirm_name, password) => api.delete(`/patients/${id}`, { data: { confirm_name, password } });
export const forgotPassword = (email) => api.post("/auth/forgot-password", { email });
export const resetPassword = (token, new_password) => api.post("/auth/reset-password", { token, new_password });
export const changePassword = (current_password, new_password) =>
  api.post("/auth/password", { current_password, new_password });

// ── Sharing (owner only) ──────────────────────────────
export const getAccess = (patientId) => api.get(`/patients/${patientId}/access`);
export const grantAccess = (patientId, email, role) => api.post(`/patients/${patientId}/access`, { email, role });
export const changeAccess = (patientId, userId, role) => api.put(`/patients/${patientId}/access/${userId}`, { role });
export const revokeAccess = (patientId, userId) => api.delete(`/patients/${patientId}/access/${userId}`);

// ── Patients ──────────────────────────────────────────
export const getPatients = () => api.get("/patients");
export const getPatient = (id) => api.get(`/patients/${id}`);
export const createPatient = (data) => api.post("/patients", data);

// ── Documents ─────────────────────────────────────────
export const uploadDocument = (patientId, file) => {
  const form = new FormData();
  form.append("file", file);
  return api.post(`/patients/${patientId}/documents`, form);
};
export const getDocument = (docId) => api.get(`/documents/${docId}`);
export const reprocessDocument = (docId) => api.post(`/documents/${docId}/reprocess`);
export const getAllergies = (patientId) => api.get(`/patients/${patientId}/allergies`);
export const getDocuments = (patientId) =>
  api.get(`/patients/${patientId}/documents`);
export const validateDocument = (docId, data) =>
  api.put(`/documents/${docId}/validate`, data);

// ── Medications ───────────────────────────────────────
export const getMedications = (patientId, status) =>
  api.get(`/patients/${patientId}/medications`, { params: { status } });
export const updateMedicationStatus = (medId, status) =>
  api.put(`/medications/${medId}/status`, null, { params: { status } });

// ── Lab Results ───────────────────────────────────────
export const getLabResults = (patientId, testName) =>
  api.get(`/patients/${patientId}/lab-results`, { params: { test_name: testName } });

// ── Timeline ──────────────────────────────────────────
export const getTimeline = (patientId) =>
  api.get(`/patients/${patientId}/timeline`);

// ── Health Summary ────────────────────────────────────
export const getHealthSummary = (patientId) =>
  api.get(`/patients/${patientId}/health-summary`);

// ── Chat ──────────────────────────────────────────────
export const sendChatMessage = (patientId, message) =>
  api.post("/chat", { patient_id: patientId, message });
export const getChatHistory = (patientId) =>
  api.get(`/patients/${patientId}/chat-history`);
export const clearChatHistory = (patientId) =>
  api.delete(`/patients/${patientId}/chat-history`);

export default api;
