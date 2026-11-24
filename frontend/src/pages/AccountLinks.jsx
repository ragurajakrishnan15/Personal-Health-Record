import { useEffect, useState } from "react";
import { Activity } from "lucide-react";
import { resetPassword, verifyEmail } from "../services/api";

/** The token lives in the URL fragment (never sent to a server). Read it once, then remove it from the address bar. */
function takeToken() {
  const t = new URLSearchParams(window.location.hash.replace(/^#/, "")).get("token") || "";
  if (t) window.history.replaceState(null, "", window.location.pathname);
  return t;
}

const detail = (e) => (typeof e.response?.data?.detail === "string" ? e.response.data.detail : "Something went wrong. Please try again.");
const home = () => { window.location.assign("/"); };

function Shell({ title, children }) {
  return (
    <div className="login-page">
      <div className="card login-card">
        <div className="login-brand"><Activity size={28} /> HealthVault</div>
        <h2>{title}</h2>
        {children}
      </div>
    </div>
  );
}

let verifyStarted = false;                 // StrictMode runs effects twice; a one-time link must be used once

export function VerifyEmail() {
  const [state, setState] = useState({ status: "working", msg: "" });
  useEffect(() => {
    if (verifyStarted) return;
    verifyStarted = true;
    const token = takeToken();
    if (!token) return setState({ status: "error", msg: "This link is incomplete. Open it again from the email." });
    verifyEmail(token)
      .then(() => setState({ status: "ok", msg: "" }))
      .catch((e) => setState({ status: "error", msg: detail(e) }));
  }, []);
  return (
    <Shell title="Confirm your email">
      {state.status === "working" && <p className="text-muted">Confirming…</p>}
      {state.status === "ok" && <p className="text-success" role="status">Your email is confirmed.</p>}
      {state.status === "error" && <p className="text-danger" role="alert">{state.msg}</p>}
      {state.status !== "working" && <button className="btn btn-primary" onClick={home}>Continue</button>}
    </Shell>
  );
}

export function ResetPassword() {
  const [token] = useState(takeToken);
  const [pw, setPw] = useState("");
  const [pw2, setPw2] = useState("");
  const [err, setErr] = useState("");
  const [done, setDone] = useState(false);
  const [busy, setBusy] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    if (pw !== pw2) return setErr("The two passwords do not match.");
    setBusy(true);
    setErr("");
    try {
      await resetPassword(token, pw);
      setDone(true);
    } catch (e2) {
      setErr(detail(e2));
      setBusy(false);
    }
  };

  if (done) {
    return (
      <Shell title="Password changed">
        <p className="text-success" role="status">Your password was changed and you were signed out everywhere. Sign in with the new one.</p>
        <button className="btn btn-primary" onClick={home}>Sign in</button>
      </Shell>
    );
  }
  if (!token) {
    return (
      <Shell title="Reset your password">
        <p className="text-danger">This link is incomplete. Open it again from the email, or request a new one.</p>
        <button className="btn btn-primary" onClick={home}>Back to sign in</button>
      </Shell>
    );
  }
  return (
    <Shell title="Choose a new password">
      <form onSubmit={submit} className="login-card" style={{ boxShadow: "none", padding: 0 }}>
        <label>New password
          <input className="input" type="password" autoComplete="new-password" autoFocus value={pw} onChange={(e) => setPw(e.target.value)} required />
        </label>
        <label>Repeat it
          <input className="input" type="password" autoComplete="new-password" value={pw2} onChange={(e) => setPw2(e.target.value)} required />
        </label>
        <p className="text-muted login-hint">At least 10 characters. Avoid common passwords and your email name.</p>
        {err && <p className="text-danger" role="alert">{err}</p>}
        <button className="btn btn-primary" disabled={busy}>Change password</button>
      </form>
    </Shell>
  );
}
