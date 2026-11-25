import { useState } from "react";
import { LogOut, Monitor, Moon, Sun } from "lucide-react";
import { useAuth } from "../context/AuthContext";
import { changePassword } from "../services/api";
import { errMsg } from "../lib/dates";
import { getTheme, setTheme } from "../lib/theme";
import { useToast } from "../components/ui";

const THEMES = [["system", "Match device", Monitor], ["light", "Light", Sun], ["dark", "Dark", Moon]];

function PasswordForm() {
  const toast = useToast();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    setErr("");
    try {
      await changePassword(current, next);
      setCurrent("");
      setNext("");
      toast("Password changed");
    } catch (ex) {
      setErr(errMsg(ex));
    } finally {
      setBusy(false);
    }
  };

  return (
    <form className="card stack" onSubmit={submit}>
      <h3>Change password</h3>
      <label>Current password
        <input className="input" type="password" autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} required />
      </label>
      <label>New password
        <input className="input" type="password" autoComplete="new-password" minLength={10} value={next} onChange={(e) => setNext(e.target.value)} required />
      </label>
      <p className="text-muted">At least 10 characters. Changing it signs out your other devices.</p>
      {err && <p className="text-danger" role="alert">{err}</p>}
      <div className="row-actions"><button className="btn btn-primary" disabled={busy}>{busy ? "Changing…" : "Change password"}</button></div>
    </form>
  );
}

export default function SettingsPage() {
  const { user, logout } = useAuth();
  const [theme, setChoice] = useState(getTheme);
  const choose = (k) => { setTheme(k); setChoice(k); };

  return (
    <div className="page">
      <h2>Settings</h2>
      <section className="card">
        <h3>Account</h3>
        <p><strong>{user.name}</strong></p>
        <p className="text-muted">{user.email}{user.email_verified ? ", confirmed" : ", not confirmed yet"}</p>
        <div className="row-actions"><button type="button" className="btn btn-outline" onClick={logout}><LogOut size={16} /> Sign out</button></div>
      </section>

      <section className="card">
        <h3>Appearance</h3>
        <div className="chips" role="group" aria-label="Colour mode">
          {THEMES.map(([k, label, Icon]) => (
            <button key={k} type="button" className={`chip ${theme === k ? "active" : ""}`} aria-pressed={theme === k} onClick={() => choose(k)}>
              <Icon size={16} /> {label}
            </button>
          ))}
        </div>
      </section>

      <PasswordForm />

      <section className="card">
        <h3>Use it like an app</h3>
        <p className="text-muted">
          On Android, open the browser menu and choose "Add to Home screen". On iPhone, tap Share, then "Add to Home Screen".
          You still need an internet connection.
        </p>
      </section>
    </div>
  );
}
