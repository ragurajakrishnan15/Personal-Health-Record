import { useState } from "react";
import { Plus, Receipt, Trash2, Wallet } from "lucide-react";
import { createExpense, deleteExpense, getExpenses } from "../services/api";
import useApi from "../hooks/useApi";
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

function List({ patient }) {
  const { canEdit } = usePatient();
  const [adding, setAdding] = useState(false);
  const [confirmId, setConfirmId] = useState(null);
  const [err, setErr] = useState("");
  const expenses = useApi(() => getExpenses(patient.id), [patient.id]);
  const totals = expenses.data?.totals || [];
  const items = expenses.data?.items || [];

  const remove = async (id) => {
    setErr("");
    try { await deleteExpense(id); expenses.reload(); } catch (ex) { setErr(errMsg(ex)); }
  };

  return (
    <>
      {totals.length > 0 && (
        <div className="stats-grid">
          {totals.map((t) => (
            <div key={t.currency} className="stat-card">
              <Wallet size={24} />
              <div>
                <span className="stat-value">{money(t.total, t.currency)}</span>
                <span className="stat-label">Total ({t.currency}) · {t.count} {t.count === 1 ? "expense" : "expenses"}</span>
                {t.unverified > 0 && <p className="text-warning">Includes {money(t.unverified, t.currency)} not yet reviewed</p>}
              </div>
            </div>
          ))}
        </div>
      )}
      {totals.length > 1 && <p className="text-muted">Each currency is totalled separately; amounts are not converted.</p>}

      {canEdit && !adding && (
        <p><button className="btn btn-primary" onClick={() => setAdding(true)}><Plus size={16} /> Add expense</button></p>
      )}
      {adding && (
        <AddForm
          patientId={patient.id}
          defaultCurrency={items[0]?.currency || (patient.phone?.startsWith("+91") ? "INR" : "USD")}
          onCancel={() => setAdding(false)}
          onDone={() => { setAdding(false); expenses.reload(); }}
        />
      )}

      {(expenses.error || err) && <p className="text-danger">{expenses.error || err}</p>}
      {expenses.data && items.length === 0 && (
        <p className="placeholder">No expenses yet. Add one, or upload a medical bill.</p>
      )}
      {items.map((x) => (
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
