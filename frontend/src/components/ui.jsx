/** Small shared building blocks: avatar, sheet, toasts, loading and empty states, range bar. */
import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { CheckCircle, X } from "lucide-react";
import { formatRange } from "../lib/labs";

export function Avatar({ person, large = false }) {
  const parts = (person?.name || "?").trim().split(/\s+/);
  const initials = (parts[0][0] + (parts.length > 1 ? parts.at(-1)[0] : "")).toUpperCase();
  return (
    <span className={`avatar ${large ? "avatar-lg" : ""}`} style={{ "--hue": ((person?.id || 0) * 67 + 232) % 360 }} aria-hidden="true">
      {initials}
    </span>
  );
}

/** Bottom sheet on phones, centred dialog on wide screens. For short choices only, never a whole page. */
export function Sheet({ open, onClose, title, children }) {
  const ref = useRef(null);
  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) d.showModal();
    if (!open && d.open) d.close();
  }, [open]);
  return (
    <dialog ref={ref} className="sheet" aria-label={title} onClose={onClose}
            onClick={(e) => e.target === ref.current && onClose()}>
      {open && (
        <>
          <div className="sheet-head">
            <h2>{title}</h2>
            <button type="button" className="icon-btn" onClick={onClose} aria-label="Close"><X size={18} /></button>
          </div>
          <div className="sheet-body">{children}</div>
        </>
      )}
    </dialog>
  );
}

const ToastCtx = createContext(() => {});
export const useToast = () => useContext(ToastCtx);

export function ToastProvider({ children }) {
  const [items, setItems] = useState([]);
  const next = useRef(0);
  const push = useCallback((text) => {
    const id = ++next.current;
    setItems((s) => [...s, { id, text }]);
    setTimeout(() => setItems((s) => s.filter((t) => t.id !== id)), 3500);
  }, []);
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="toasts" role="status" aria-live="polite">
        {items.map((t) => <div key={t.id} className="toast"><CheckCircle size={18} /> {t.text}</div>)}
      </div>
    </ToastCtx.Provider>
  );
}

export function Skeleton({ rows = 3, height = 72 }) {
  return (
    <div className="stack" aria-busy="true">
      <span className="sr-only">Loading</span>
      {Array.from({ length: rows }, (_, i) => <span key={i} className="skeleton" style={{ height }} />)}
    </div>
  );
}

export function Empty({ icon: Icon, title, children }) {
  return (
    <div className="empty">
      {Icon && <span className="row-icon"><Icon size={20} /></span>}
      <h3>{title}</h3>
      {children}
    </div>
  );
}

/** Where a value sits against the range printed on its report. */
export function RangeBar({ value, range }) {
  const { lo, hi } = range;
  const span = lo != null && hi != null ? hi - lo || Math.abs(hi) || 1 : Math.abs(hi ?? lo) || 1;
  let min = lo != null ? lo - span * 0.5 : 0;
  let max = hi != null ? hi + span * 0.5 : lo + span;
  min = Math.min(min, value);
  max = Math.max(max, value);
  if (lo == null || lo >= 0) min = Math.max(0, min);
  const at = (v) => ((v - min) / (max - min || 1)) * 100;
  const left = lo != null ? at(lo) : 0;
  const right = hi != null ? at(hi) : 100;
  const outside = (lo != null && value < lo) || (hi != null && value > hi);
  return (
    <div className="rbar" aria-hidden="true">
      <span className="rbar-band" style={{ left: `${left}%`, width: `${Math.max(2, right - left)}%` }} />
      <span className={`rbar-dot ${outside ? "bad" : ""}`} style={{ left: `${at(value)}%` }} />
    </div>
  );
}

const WORD = { H: "High", L: "Low", "!": "Marked abnormal" };

/** One lab test's latest reading. Status is always written out, never shown by colour alone. */
export function LabResult({ group }) {
  const p = group.latest;
  return (
    <div className="result">
      <div className="result-head">
        <span>{group.name}</span>
        <span className="result-value">{p.raw}<small>{group.unit}</small></span>
      </div>
      {p.range && <RangeBar value={p.value} range={p.range} />}
      <div className="rbar-foot">
        {p.abnormal ? <span className="status status-bad">{WORD[p.flag] || "Abnormal"}</span>
          : p.status === "unknown" ? <span className="status status-unknown">No reference range printed</span>
            : <span className="status status-ok">In range</span>}
        <span>{p.range ? `Range ${formatRange(p.ref, p.range)}` : p.ref ? `Report says ${p.ref}` : ""}</span>
      </div>
    </div>
  );
}
