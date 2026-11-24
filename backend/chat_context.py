"""Build the grounding context for the health chat from the database.

Every fact is tagged with a source id [S#] pointing at the document it came from, so the model can cite and
the UI can link back to the original file. Rejected documents are excluded; unverified ones are labelled.
"""
import datetime as dt
from collections import defaultdict

from sqlalchemy.orm import Session

from ai_service import abnormal_from_range
from database import (Allergy, Consultation, LabResult, MedicalDocument, Medication, Patient)

MAX_DOCS = 30            # most recent documents that get a source id
MAX_LAB_POINTS = 8       # readings kept per test (newest)
MAX_OTHER_MEDS = 25      # completed / superseded entries listed

CATEGORY_LABEL = {"prescription": "Prescription", "lab_report": "Lab report", "discharge_summary": "Discharge summary",
                  "consultation_note": "Consultation note", "imaging_report": "Imaging report"}


def _label(doc: MedicalDocument) -> str:
    kind = CATEGORY_LABEL.get(doc.category, (doc.category or "Document").replace("_", " ").title())
    who = doc.hospital or doc.doctor or "unknown provider"
    flag = "" if doc.validation_status in ("verified", "corrected") else " (UNVERIFIED: not yet reviewed by a person)"
    return f"{kind}, {doc.document_date or 'undated'}, {who}{flag}"


def build_context(db: Session, patient: Patient, today: dt.date | None = None) -> dict:
    """Return {"text": str, "sources": {"S1": {...}}}."""
    today = today or dt.date.today()
    docs = [d for d in db.query(MedicalDocument).filter(MedicalDocument.patient_id == patient.id,
                                                        MedicalDocument.validation_status != "rejected",
                                                        MedicalDocument.processing_status == "done").all()]
    docs.sort(key=lambda d: (d.document_date or "", d.id))
    docs = docs[-MAX_DOCS:]
    ref_of = {d.id: f"S{i}" for i, d in enumerate(docs, 1)}
    sources = {ref_of[d.id]: {"ref": ref_of[d.id], "document_id": d.id, "label": _label(d), "date": d.document_date,
                              "category": d.category, "unverified": d.validation_status not in ("verified", "corrected")}
               for d in docs}
    tag = lambda doc_id: f" [{ref_of[doc_id]}]" if doc_id in ref_of else ""

    out = [f"TODAY: {today.isoformat()}",
           f"PATIENT: {patient.name}" + (f", {patient.age} years" if patient.age else "") +
           (f", {patient.gender}" if patient.gender else "") + (f", blood group {patient.blood_group}" if patient.blood_group else "")]

    out.append("\nSOURCES (documents the facts below come from):")
    out += [f"[{s['ref']}] {s['label']}" for s in sources.values()] or ["(no documents on file)"]

    allergies = db.query(Allergy).filter(Allergy.patient_id == patient.id).all()
    out.append("\nALLERGIES: " + ("; ".join(f"{a.allergen}" + (f" ({a.reaction})" if a.reaction else "") for a in allergies)
                                  if allergies else "none recorded"))

    # ── medications ────────────────────────────────────────────────────────────────────────
    meds = db.query(Medication).filter(Medication.patient_id == patient.id).all()
    meds = [m for m in meds if m.document_id is None or m.document_id in ref_of]

    def med_line(m: Medication) -> str:
        bits = [m.name]
        if m.generic_name and m.generic_name.lower() != m.name.lower():
            bits.append(f"(generic: {m.generic_name}{', INFERRED from brand name, unverified' if m.generic_inferred else ''})")
        dose = " ".join(x for x in (m.strength, m.dosage) if x)
        bits.append(", ".join(x for x in (dose, m.frequency, m.timing) if x) or "no dosing details")
        span = f"started {m.start_date}" + (f", supply/course until {m.end_date}" if m.end_date else "")
        return f"- {' '.join(bits)}; {span}" + (f"; prescriber {m.prescribing_doctor}" if m.prescribing_doctor else "") + tag(m.document_id)

    for status, title, cap in (("active", "CURRENT MEDICATIONS", None),
                               ("lapsed", "UNCONFIRMED - long-term medicines whose last prescription ran out with no "
                                          "renewal on record (may or may not still be taken; do not call them current or stopped)", None),
                               ("discontinued", "DISCONTINUED MEDICATIONS", None),
                               ("completed", "COMPLETED COURSES (finished)", MAX_OTHER_MEDS),
                               ("superseded", "REPLACED BY A NEWER PRESCRIPTION", MAX_OTHER_MEDS)):
        rows = sorted([m for m in meds if m.status == status], key=lambda m: m.start_date or "", reverse=True)[:cap]
        if rows:
            out.append(f"\n{title}:")
            out += [med_line(m) for m in rows]
        elif status == "active":
            out.append("\nCURRENT MEDICATIONS: none recorded")

    # ── labs ────────────────────────────────────────────────────────────────────────────────
    labs = [l for l in db.query(LabResult).filter(LabResult.patient_id == patient.id).all()
            if l.document_id is None or l.document_id in ref_of]
    by_test = defaultdict(list)
    for l in labs:
        by_test[l.test_name].append(l)
    if by_test:
        out.append("\nLAB RESULTS (per test, oldest to newest; H/L = outside the printed reference range):")
    for name in sorted(by_test):
        rows = sorted(by_test[name], key=lambda l: l.report_date or "")[-MAX_LAB_POINTS:]
        ref = next((l.reference_range for l in reversed(rows) if l.reference_range), None)
        unit = rows[-1].unit or ""
        readings = []
        status = "no reference range printed"
        for l in rows:
            ab, flag = abnormal_from_range(l.test_value or "", l.reference_range)
            if flag:
                mark, status = f" {flag} (outside range)", ("HIGH" if flag == "H" else "LOW") + ", outside the reference range"
            elif ab is False:
                mark, status = " (in range)", "within the reference range"
            else:
                mark, status = " (no reference range)", "no reference range printed"
            readings.append(f"{l.report_date} {l.test_value}{mark}{tag(l.document_id)}")
        out.append(f"- {name} ({unit}; reference {ref or 'not printed'}): " + "; ".join(readings)
                   + f" => LATEST VALUE IS {status.upper()}")

    # ── diagnoses / visits ─────────────────────────────────────────────────────────────────
    cons = [c for c in db.query(Consultation).filter(Consultation.patient_id == patient.id).all()
            if c.document_id is None or c.document_id in ref_of]
    if cons:
        out.append("\nVISITS AND DIAGNOSES (newest first):")
        for c in sorted(cons, key=lambda c: c.consultation_date or "", reverse=True):
            line = f"- {c.consultation_date}: {c.doctor_name or 'unknown doctor'}" + (f" at {c.hospital}" if c.hospital else "")
            if c.diagnosis:
                line += f"; diagnosis: {c.diagnosis}"
            if c.follow_up_date:
                line += f"; follow-up date: {c.follow_up_date}"
            elif c.notes:
                line += f"; follow-up: {c.notes}"
            out.append(line + tag(c.document_id))

    # ── past history (from extracted documents) ─────────────────────────────────────────────
    history = {}
    for d in docs:
        for h in (d.extracted_data or {}).get("past_medical_history", []) or []:
            history.setdefault(h.lower(), (h, d.id))
    if history:
        out.append("\nPAST MEDICAL HISTORY (as listed in discharge summaries):")
        out += [f"- {h}{tag(did)}" for h, did in history.values()]

    return {"text": "\n".join(out), "sources": sources}
