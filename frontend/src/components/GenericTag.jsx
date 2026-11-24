import { AlertTriangle } from "lucide-react";

/** Shows a medicine's generic name, with a "verify" tag when it was guessed from the brand name. */
export default function GenericTag({ name, brand, inferred }) {
  if (!name || name.toLowerCase() === (brand || "").toLowerCase()) return null;
  return (
    <span className={inferred ? "generic-inferred" : "text-muted"}
          title={inferred ? "The generic name was inferred from the brand name, not printed on the document. Please verify." : "Printed on the document"}>
      {" "}({name}){inferred && <span className="badge badge-verify"><AlertTriangle size={11} /> verify</span>}
    </span>
  );
}

/** Banner listing every guessed generic in an extraction. */
export function InferredBanner({ list }) {
  if (!list || list.length === 0) return null;
  return (
    <p className="text-warning">
      <AlertTriangle size={16} /> Generic names were inferred from brand names for: {list.join(", ")}. Please verify them
      against the original document.
    </p>
  );
}
