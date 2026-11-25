import { useState } from "react";
import { Plus, Receipt, Trash2, Wallet } from "lucide-react";
import { createExpense, deleteExpense, getExpenses } from "../services/api";
import useApi from "../hooks/useApi";
import useAddParam from "../hooks/useAddParam";
import { Skeleton, useToast } from "../components/ui";
import NeedPatient from "../components/NeedPatient";
import { usePatient } from "../context/PatientContext";
import { errMsg, prettyDate, todayLocal } from "../lib/dates";
import { money } from "../lib/money";

const CATEGORIES = {
  consultation: "Consultation", medicine: "Medicine", lab_test: "Lab test", hospital: "Hospital",
  insurance: "Insurance", other: "Other",
};
const CURRENCIES = ["INR", "USD", "EUR", "GBP"];

function AddForm({ patientId, defaultCurrency, onDone, onCancel }) {
  const [f, setF] = useState({
    description: "", amount: "", currency: defaultCurrency, category: "consultation", expense_date: todayLocal(),
  });
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const set = (k) => (e) => setF((s) => ({ ...s, [k]: e.target.value }));

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    setErr("");
    try {
      await createExpense(patientId, f);
      onDone();
    } catch (ex) {
      setErr(errMsg(ex));
      setBusy(false);
    }
  };

  return (
    <form className="card" onSubmit={submit}>
      <div className="form-grid">
        <label className="form-span"><span>Description</span>
          <input className="input" value={f.description} onChange={set("description")} maxLength={200} required
                 placeholder="e.g. Pharmacy bill" />
        </label>
        <label><span>Amount</span>
          <input className="input" type="number" inputMode="decimal" min="0.01" step="0.01" value={f.amount}
                 onChange={set("amount")} required />
        </label>
        <label><span>Currency</span>
          <select className="select" value={f.currency} onChange={set("currency")}>
            {CURRENCIES.map((c) => <option key={c}>{c}</option>)}
          </select>
        </label>
        <label><span>Category</span>
          <select className="select" value={f.category} onChange={set("category")}>
            {Object.entries(CATEGORIES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </label>
        <label><span>Date</span><input className="input" type="date" value={f.expense_date} onChange={set("expense_date")} required /></label>
      </div>
      {err && <p className="text-danger">{err}</p>}
      <div className="row-actions">
        <button className="btn btn-primary" disabled={busy}>Save expense</button>
        <button type="button" className="btn btn-outline" onClick={onCancel}>Cancel</button>
      </div>
    </form>
  );
}

const PERIODS = [["all", "All time"], ["year", "This year"], ["month", "This month"]];

/** Totals for one currency over whatever is currently shown. Whole cents, so sums stay exact. */
function summarise(rows) {
  const by = {};
  for (const x of rows) {
    const t = (by[x.currency] ||= { currency: x.currency, cents: 0, unverified: 0, count: 0, categories: {} });
    const cents = Math.round(x.amount * 100);
    t.cents += cents;
    t.count += 1;
    if (x.unverified) t.unverified += cents;
    t.categories[x.category] = (t.categories[x.category] || 0) + cents;
  }
  return Object.values(by).sort((a, b) => a.currency.localeCompare(b.currency));
}

function Breakdown({ total, selected, onSelect }) {
  const rows = Object.entries(total.categories).sort((a, b) => b[1] - a[1]);
  const top = rows[0][1];
  return (
    <section className="card">
      <h3>Where it went ({total.currency})</h3>
      <p className="text-muted">Tap a bar to show only that category.</p>
      {rows.map(([key, cents]) => (
        <button key={key} type="button" className="spend-bar" aria-pressed={selected === key}
                onClick={() => onSelect(selected === key ? "" : key)}>
          <span>{CATEGORIES[key] || key}</span>
          <span className="spend-track" aria-hidden="true"><span className="spend-fill" style={{ width: `${(cents / top) * 100}%` }} /></span>
          <span>{money(cents / 100, total.currency)}</span>
        </button>
      ))}
    </section>
  );
}

function List({ patient }) {
  const { canEdit } = usePatient();
  const [adding, setAdding] = useState(false);
  const [confirmId, setConfirmId] = useState(null);
  const [err, setErr] = useState("");
  const expenses = useApi(() => getExpenses(patient.id), [patient.id]);
  const [period, setPeriod] = useState("all");
  const [category, setCategory] = useState("");
  const toast = useToast();
  useAddParam(() => setAdding(true));
  const items = expenses.data?.items || [];
  const prefix = period === "all" ? "" : todayLocal().slice(0, period === "year" ? 4 : 7);
  const inPeriod = items.filter((x) => x.expense_date.startsWith(prefix));
  const totals = summarise(inPeriod);
  const shown = inPeriod.filter((x) => !category || x.category === category);

  const remove = async (id) => {
    setErr("");
    try { await deleteExpense(id); toast("Expense deleted"); expenses.reload(); } catch (ex) { setErr(errMsg(ex)); }
  };

  return (
    <>
      <div className="chips" role="group" aria-label="Time period">
        {PERIODS.map(([k, label]) => (
          <button key={k} type="button" className={`chip ${period === k ? "active" : ""}`} aria-pressed={period === k}
                  onClick={() => { setPeriod(k); setCategory(""); }}>{label}</button>
        ))}
      </div>
      {expenses.loading && !expenses.data && <Skeleton />}
      {totals.length > 0 && (
        <div className="stats-grid">
          {totals.map((t) => (
            <div key={t.currency} className="stat-card">
              <Wallet size={24} />
              <div>
                <span className="stat-value">{money(t.cents / 100, t.currency)}</span>
                <span className="stat-label">Total ({t.currency}) · {t.count} {t.count === 1 ? "expense" : "expenses"}</span>
                {t.unverified > 0 && <p className="text-warning">Includes {money(t.unverified / 100, t.currency)} not yet reviewed</p>}
              </div>
            </div>
          ))}
        </div>
      )}
      {totals.length > 1 && <p className="text-muted">Each currency is totalled separately; amounts are not converted.</p>}
      {totals.map((t) => <Breakdown key={t.currency} total={t} selected={category} onSelect={setCategory} />)}

      {canEdit && !adding && (
        <p><button className="btn btn-primary" onClick={() => setAdding(true)}><Plus size={16} /> Add expense</button></p>
      )}
      {adding && (
        <AddForm
          patientId={patient.id}
          defaultCurrency={items[0]?.currency || (patient.phone?.startsWith("+91") ? "INR" : "USD")}
          onCancel={() => setAdding(false)}
          onDone={() => { setAdding(false); expenses.reload(); toast("Expense saved"); }}
        />
      )}

      {(expenses.error || err) && <p className="text-danger">{expenses.error || err}</p>}
      {expenses.data && items.length === 0 && (
        <p className="placeholder">No expenses yet. Add one, or upload a medical bill.</p>
      )}
      {expenses.data && items.length > 0 && shown.length === 0 && <p className="placeholder">No expenses in this view.</p>}
      {shown.map((x) => (
        <div key={x.id} className="card item-row">
          <Receipt size={20} />
          <div className="item-main">
            <strong>{x.description}</strong> <span className="badge">{CATEGORIES[x.category] || x.category}</span>
            {x.unverified && <span className="badge badge-lapsed">needs review</span>}
            <p>{money(x.amount, x.currency)}</p>
            <p className="text-muted">
              {prettyDate(x.expense_date)}
              {x.document_id && (
                <> · <a href={`/api/documents/${x.document_id}/file`} target="_blank" rel="noreferrer">View bill</a></>
              )}
            </p>
          </div>
          {canEdit && (
            <div className="med-actions">
              {confirmId === x.id ? (
                <button className="btn btn-danger" onClick={() => remove(x.id)}>Confirm delete</button>
              ) : (
                <button className="btn btn-outline btn-danger-outline" onClick={() => setConfirmId(x.id)}><Trash2 size={14} /> Delete</button>
              )}
            </div>
          )}
        </div>
      ))}
    </>
  );
}

export default function Expenses() {
  return (
    <div className="page">
      <h2>Medical Expenses</h2>
      <NeedPatient>{(p) => <List key={p.id} patient={p} />}</NeedPatient>
    </div>
  );
}
