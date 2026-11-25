import { useEffect } from "react";
import { BrowserRouter, Link, Routes, Route, useLocation } from "react-router-dom";
import { ToastProvider } from "./components/ui";
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
import Expenses from "./pages/Expenses";
import SettingsPage from "./pages/SettingsPage";
import Login from "./pages/Login";
import { ResetPassword, VerifyEmail } from "./pages/AccountLinks";
import VerifyBanner from "./components/VerifyBanner";
import { AuthProvider, useAuth } from "./context/AuthContext";
import { PatientProvider } from "./context/PatientContext";
import "./App.css";

/** A new page starts at the top. */
function ScrollTop() {
  const { pathname } = useLocation();
  useEffect(() => { window.scrollTo(0, 0); }, [pathname]);
  return null;
}

const NotFound = () => (
  <div className="page">
    <h2>Page not found</h2>
    <p className="placeholder">That page does not exist. <Link to="/">Go to the home page</Link>.</p>
  </div>
);

/** Nothing but the sign-in page is rendered (or fetched) until there is a session. */
function Gate() {
  const { user, loading } = useAuth();
  // one-time email links work whether or not you are signed in
  if (window.location.pathname === "/reset-password") return <ResetPassword />;
  if (window.location.pathname === "/verify-email") return <VerifyEmail />;
  if (loading) return <p className="placeholder" style={{ padding: 40 }}>Loading…</p>;
  if (!user) return <Login />;
  return (
    <PatientProvider>
      <BrowserRouter>
        <ScrollTop />
        <div className="app-layout">
          <a className="skip-link" href="#main">Skip to content</a>
          <Sidebar />
          <div className="main-area">
            <Header />
            <VerifyBanner />
            <main className="content" id="main">
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
                <Route path="/expenses" element={<Expenses />} />
                <Route path="/settings" element={<SettingsPage />} />
                <Route path="*" element={<NotFound />} />
              </Routes>
            </main>
          </div>
          <BottomNav />
        </div>
      </BrowserRouter>
    </PatientProvider>
  );
}

export default function App() {
  return (
    <AuthProvider>
      <ToastProvider>
        <Gate />
      </ToastProvider>
    </AuthProvider>
  );
}
