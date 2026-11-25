import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Bell, Calendar, Check, ChevronRight, ClipboardCheck, FlaskConical, MessageSquare, Pill, ScanLine, ShieldCheck, TrendingUp, Wallet } from "lucide-react";
import { completeReminder, getAppointments, getHealthSummary, getLabResults, getMedications, getReminders, getTimeline } from "../services/api";
import useApi from "../hooks/useApi";
import NeedPatient from "../components/NeedPatient";
import { usePatient } from "../context/PatientContext";
import { Avatar, LabResult, Skeleton, useToast } from "../components/ui";
import { groupLabs } from "../lib/labs";
import { errMsg, prettyDate, todayLocal } from "../lib/dates";
import { money } from "../lib/money";

const count = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;

function CheckRow({ to, icon: Icon, tone, title, hint }) {
  return (
    <li>
      <Link to={to} className="row-link">
        <span className={`row-icon ${tone}`}><Icon size={20} /></span>
        <span className="grow"><strong>{title}</strong><small>{hint}</small></span>
        <ChevronRight size={18} className="text-muted" aria-hidden="true" />
      </Link>
    </li>
  );
}

function Overview({ patient }) {
  const { canEdit } = usePatient();
  const toast = useToast();
  const [busyId, setBusyId] = useState(null);
  const [error, setError] = useState("");
  const [moreTimeline, setMoreTimeline] = useState(false);
  const summary = useApi(() => getHealthSummary(patient.id), [patient.id]);
  const labs = useApi(() => getLabResults(patient.id), [patient.id]);
  const lapsed = useApi(() => getMedications(patient.id, "lapsed"), [patient.id]);
  const reminders = useApi(() => getReminders(patient.id, "active"), [patient.id]);
  const appointments = useApi(() => getAppointments(patient.id, "upcoming"), [patient.id]);
  const timeline = useApi(() => getTimeline(patient.id), [patient.id]);
  const s = summary.data;
  const today = todayLocal();

  // out-of-range latest results first, then the most recent
  const groups = useMemo(
    () => groupLabs(labs.data).sort((a, b) => b.latest.abnormal - a.latest.abnormal || b.latest.t - a.latest.t),
    [labs.data],
  );
  const abnormalNow = groups.filter((g) => g.latest.abnormal).length;
  const due = (reminders.data || []).filter((r) => r.due_date <= today);
  const next = appointments.data?.[0];
  const toCheck = !!(s?.pending_reviews || lapsed.data?.length || abnormalNow);
  const checksLoaded = summary.data && lapsed.data && labs.data;
  const val = (v) => (v ?? "…");

  const done = async (r) => {
    setBusyId(r.id);
    setError("");
    try {
      await completeReminder(r.id);
      toast(r.repeat === "none" ? "Reminder done" : "Done. Moved to the next date");
      reminders.reload();
    } catch (e) {
      setError(errMsg(e));
    } finally {
      setBusyId(null);
    }
  };

  const events = timeline.data || [];

  return (
    <>
      <section className="hero">
        <div className="hero-top">
          <Avatar person={patient} large />
          <div>
            <h2>{patient.name}</h2>
            <p>{[patient.age && `${patient.age} years`, patient.gender, patient.blood_group && `Blood group ${patient.blood_group}`].filter(Boolean).join(", ")}</p>
          </div>
        </div>
        <div className="hero-stats">
          <Link to="/records" className="hero-stat"><b>{val(s?.total_documents)}</b><span>Documents</span></Link>
          <Link to="/medications" className="hero-stat"><b>{val(s?.active_medications)}</b><span>Active medicines</span></Link>
          <Link to="/appointments" className="hero-stat"><b>{val(appointments.data?.length)}</b><span>Upcoming visits</span></Link>
        </div>
      </section>

      <nav className="quick-grid" aria-label="Quick actions">
        {canEdit
          ? <Link to="/upload" className="quick"><ScanLine size={24} /> Scan record</Link>
          : <Link to="/records" className="quick"><ScanLine size={24} /> Records</Link>}
        <Link to="/chat" className="quick"><MessageSquare size={24} /> Ask a question</Link>
        <Link to="/analytics" className="quick"><TrendingUp size={24} /> Lab trends</Link>
        <Link to="/medications" className="quick"><Pill size={24} /> Medicines</Link>
      </nav>
      {summary.error && <p className="text-danger" role="alert">{summary.error}</p>}
      {error && <p className="text-danger" role="alert">{error}</p>}

      <div className="home-cols">
        <div>
          <div className="section-head"><h3>To check</h3></div>
          <section className="card">
            {!checksLoaded ? <Skeleton rows={2} height={48} /> : !toCheck ? (
              <ul className="rows"><li><div className="row-link">
                <span className="row-icon good"><ShieldCheck size={20} /></span>
                <span className="grow"><strong>Nothing flagged</strong><small>No documents or medicines are waiting for you.</small></span>
              </div></li></ul>
            ) : (
              <ul className="rows">
                {s.pending_reviews > 0 && <CheckRow to="/records?status=pending_review" icon={ClipboardCheck} tone="warn"
                  title={`${count(s.pending_reviews, "document")} to review`} hint="Compare what the AI read with the original" />}
                {lapsed.data.length > 0 && <CheckRow to="/medications?tab=lapsed" icon={Pill} tone="warn"
                  title={`${count(lapsed.data.length, "medicine")} to confirm`} hint="No newer prescription is on file" />}
                {abnormalNow > 0 && <CheckRow to="/analytics" icon={FlaskConical} tone="bad"
                  title={`${count(abnormalNow, "test")} outside the range`} hint="Latest results, based on each report's range" />}
              </ul>
            )}
          </section>

          <div className="section-head"><h3>Latest results</h3><Link to="/analytics">All trends</Link></div>
          <section className="card">
            {labs.loading ? <Skeleton rows={3} height={56} /> : labs.error ? <p className="text-danger">{labs.error}</p> : groups.length === 0 ? (
              <p className="placeholder">No lab results yet. Upload a lab report to see them here.</p>
            ) : (
              <ul className="rows">{groups.slice(0, 4).map((g) => <li key={g.name}><LabResult group={g} /></li>)}</ul>
            )}
          </section>
        </div>

        <div>
          <div className="section-head"><h3>Coming up</h3><Link to="/reminders">Reminders</Link></div>
          <section className="card">
            <ul className="rows">
              {due.slice(0, 3).map((r) => (
                <li key={r.id}><div className="row-link">
                  <span className={`row-icon ${r.due_date < today ? "bad" : ""}`}><Bell size={20} /></span>
                  <span className="grow">
                    <strong>{r.title}</strong>
                    <small>{r.due_date < today ? `Overdue since ${prettyDate(r.due_date)}` : r.due_time ? `Today at ${r.due_time}` : "Today"}</small>
                  </span>
                  {canEdit && (
                    <button type="button" className="check-btn" disabled={busyId === r.id} onClick={() => done(r)} aria-label={`Mark done: ${r.title}`}>
                      <Check size={20} />
                    </button>
                  )}
                </div></li>
              ))}
              {next && <CheckRow to="/appointments" icon={Calendar} tone="" title={next.title}
                                 hint={`${prettyDate(next.appt_date)}${next.appt_time ? ` at ${next.appt_time}` : ""}`} />}
            </ul>
            {reminders.data && appointments.data && !next && due.length === 0 && <p className="placeholder">Nothing due today and no visits booked.</p>}
          </section>

          <div className="section-head"><h3>Spending</h3><Link to="/expenses">All expenses</Link></div>
          <Link to="/expenses" className="stat-card stat-link">
            <Wallet size={22} />
            <div>
              <span className="stat-value">{s ? (s.expense_totals.map((t) => money(t.total, t.currency)).join(" + ") || "No expenses") : "…"}</span>
              <span className="stat-label">Total medical expenses</span>
            </div>
          </Link>

          <div className="section-head"><h3>History</h3></div>
          <section className="card">
            {timeline.data?.length === 0 && <p className="placeholder">History appears here as records are added.</p>}
            <ol className="timeline">
              {events.slice(0, moreTimeline ? events.length : 4).map((e) => (
                <li key={e.id} className={`tl-${e.event_type}`}>
                  <span className="tl-date">{prettyDate(e.event_date)}</span>
                  <strong>{e.title}</strong>
                  {e.description && <p className="text-muted">{e.description}</p>}
                </li>
              ))}
            </ol>
            {events.length > 4 && (
              <button type="button" className="btn btn-outline btn-block" onClick={() => setMoreTimeline((v) => !v)} aria-expanded={moreTimeline}>
                {moreTimeline ? "Show less" : `Show all ${events.length}`}
              </button>
            )}
          </section>
        </div>
      </div>
    </>
  );
}

export default function Dashboard() {
  return (
    <div className="page">
      <NeedPatient>{(p) => <Overview key={p.id} patient={p} />}</NeedPatient>
    </div>
  );
}
