import { useState } from "react";
import { Activity, LogIn, UserPlus } from "lucide-react";
import { useAuth } from "../context/AuthContext";
import { forgotPassword } from "../services/api";

const errorText = (err) => {
  const d = err.response?.data?.detail;
  if (typeof d === "string") return d;
  if (Array.isArray(d)) return d[0]?.msg || "Please check the details.";
  return err.response ? "Something went wrong. Please try again." : "Cannot reach the server.";
};

export default function Login() {
  const { login, register } = useAuth();
  const [mode, setMode] = useState("login");           // login | register | forgot
  const [f, setF] = useState({ name: "", email: "", password: "" });
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState(false);
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });
  const signup = mode === "register";
  const forgot = mode === "forgot";

  const goto = (m) => { setMode(m); setErr(""); setSent(false); };

  const submit = async (e) => {
    e.preventDefault();
    setErr("");
    if (signup && !f.name.trim()) return setErr("Enter your name.");
    setBusy(true);
    try {
      if (forgot) {
        await forgotPassword(f.email);
        setSent(true);
        setBusy(false);
        return;
      }
      if (signup) await register(f.email, f.name, f.password);
      else await login(f.email, f.password);
    } catch (e2) {
      setErr(errorText(e2));
      setBusy(false);
    }
  };

  return (
    <div className="login-page">
      <form className="card login-card" onSubmit={submit}>
        <div className="login-brand"><Activity size={28} /> HealthVault</div>
        <h2>{signup ? "Create your account" : forgot ? "Reset your password" : "Sign in"}</h2>
        <p className="text-muted">Personal and family health records, shared only with people you choose.</p>

        {signup && (
          <label>Your name
            <input className="input" autoComplete="name" value={f.name} onChange={set("name")} maxLength={100} />
          </label>
        )}
        <label>Email
          <input className="input" type="email" autoComplete="email" autoFocus value={f.email} onChange={set("email")} required />
        </label>
        {!forgot && (
          <label>Password
            <input className="input" type="password" autoComplete={signup ? "new-password" : "current-password"}
                   value={f.password} onChange={set("password")} required />
          </label>
        )}
        {signup && <p className="text-muted login-hint">At least 10 characters. Avoid common passwords and your email name.</p>}
        {mode === "login" && (
          <button type="button" className="link-btn" onClick={() => goto("forgot")}>Forgot your password?</button>
        )}
        {forgot && !sent && <p className="text-muted login-hint">Enter your email and we will send a link to choose a new password.</p>}
        {forgot && sent && (
          <p className="text-success" role="status">
            If an account exists for that email, a reset link is on its way. It expires in 30 minutes.
          </p>
        )}

        {err && <p className="text-danger" role="alert">{err}</p>}
        {!(forgot && sent) && (
          <button className="btn btn-primary" disabled={busy}>
            {signup ? <><UserPlus size={16} /> Create account</> : forgot ? "Send reset link" : <><LogIn size={16} /> Sign in</>}
          </button>
        )}
        <button type="button" className="link-btn" onClick={() => goto(mode === "login" ? "register" : "login")}>
          {signup || forgot ? "Back to sign in" : "New here? Create an account"}
        </button>
      </form>
    </div>
  );
}
