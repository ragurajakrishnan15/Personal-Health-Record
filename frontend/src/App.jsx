import { useEffect, useState } from "react";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import Sidebar from "./components/Sidebar";
import Header from "./components/Header";
import BottomNav from "./components/BottomNav";
import Dashboard from "./pages/Dashboard";
import Patients from "./pages/Patients";
import Records from "./pages/Records";
import UploadPage from "./pages/Upload";
import Medications from "./pages/Medications";
import Analytics from "./pages/Analytics";
import Chat from "./pages/Chat";
import Appointments from "./pages/Appointments";
import Reminders from "./pages/Reminders";
import SettingsPage from "./pages/SettingsPage";
import Login from "./pages/Login";
import { ResetPassword, VerifyEmail } from "./pages/AccountLinks";
import VerifyBanner from "./components/VerifyBanner";
import { AuthProvider, useAuth } from "./context/AuthContext";
import { PatientProvider } from "./context/PatientContext";
import "./App.css";

/** Nothing but the sign-in page is rendered (or fetched) until there is a session. */
function Gate() {
  const { user, loading } = useAuth();
  const [navOpen, setNavOpen] = useState(false);   // mobile slide-out menu
  useEffect(() => {
    // while the drawer is open: Escape closes it and the page behind it does not scroll
    if (!navOpen) return;
    const onKey = (e) => e.key === "Escape" && setNavOpen(false);
    document.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
    return () => { document.removeEventListener("keydown", onKey); document.body.style.overflow = ""; };
  }, [navOpen]);
  // one-time email links work whether or not you are signed in
  if (window.location.pathname === "/reset-password") return <ResetPassword />;
  if (window.location.pathname === "/verify-email") return <VerifyEmail />;
  if (loading) return <p className="placeholder" style={{ padding: 40 }}>Loading…</p>;
  if (!user) return <Login />;
  return (
    <PatientProvider>
      <BrowserRouter>
        <div className="app-layout">
          <Sidebar open={navOpen} onClose={() => setNavOpen(false)} />
          <div className="main-area">
            <Header onMenu={() => setNavOpen(true)} />
            <VerifyBanner />
            <main className="content">
              <Routes>
                <Route path="/" element={<Dashboard />} />
                <Route path="/patients" element={<Patients />} />
                <Route path="/records" element={<Records />} />
                <Route path="/upload" element={<UploadPage />} />
                <Route path="/medications" element={<Medications />} />
                <Route path="/analytics" element={<Analytics />} />
                <Route path="/chat" element={<Chat />} />
                <Route path="/appointments" element={<Appointments />} />
                <Route path="/reminders" element={<Reminders />} />
                <Route path="/settings" element={<SettingsPage />} />
              </Routes>
            </main>
          </div>
          <BottomNav onMore={() => setNavOpen(true)} />
        </div>
      </BrowserRouter>
    </PatientProvider>
  );
}

export default function App() {
  return (
    <AuthProvider>
      <Gate />
    </AuthProvider>
  );
}
