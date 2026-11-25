"""Turn a document's extracted JSON into relational rows (medications, labs, consultations,
allergies, timeline). Idempotent per document: re-running replaces that document's rows."""
import datetime as dt
import re

from sqlalchemy.orm import Session

from database import (Allergy, Appointment, Consultation, Expense, LabResult, Reminder, MedicalDocument, Medication, TimelineEvent)

BILL_CATEGORY = {"prescription": "medicine", "lab_report": "lab_test", "discharge_summary": "hospital",
                 "consultation_note": "consultation"}
CONSULT_CATEGORIES = {"prescription", "discharge_summary", "consultation_note"}


def duration_days(text: str | None) -> int | None:
    m = re.match(r"\s*(\d+)\s*(day|week|month)", (text or "").lower())
    if not m:
        return None
    return int(m.group(1)) * {"day": 1, "week": 7, "month": 30}[m.group(2)]


def end_date(start_iso: str | None, duration: str | None) -> str | None:
    days = duration_days(duration)
    if not start_iso or days is None:
        return None
    try:
        return (dt.date.fromisoformat(start_iso) + dt.timedelta(days=days)).isoformat()
    except ValueError:
        return None


ONGOING_MIN_DAYS = 28      # courses at least this long are maintenance therapy
LAPSE_GRACE_DAYS = 120     # ...and stay "active" this long after the supply runs out (refill window)


MED_STATUSES = {"active", "lapsed", "completed", "superseded", "discontinued"}


def status_for(start_iso: str | None, end_iso: str | None, today: dt.date) -> str:
    if not start_iso or not end_iso:
        return "active"
    try:
        start, end = dt.date.fromisoformat(start_iso), dt.date.fromisoformat(end_iso)
    except ValueError:
        return "active"
    maintenance = (end - start).days >= ONGOING_MIN_DAYS
    limit = today - dt.timedelta(days=LAPSE_GRACE_DAYS if maintenance else 0)
    if end >= limit:
        return "active"
    return "lapsed" if maintenance else "completed"


def med_status(date_iso: str, duration: str | None, today: dt.date) -> str:
    """active    - supply not finished (maintenance therapy gets a refill grace period)
    completed - a short course (antibiotic etc.) that has ended
    lapsed    - maintenance therapy whose supply ran out long ago with no newer prescription on
                record. We do NOT know it was stopped (chronic medicines are often refilled
                without a new document), so it is shown for confirmation, never as 'completed'."""
    return status_for(date_iso, end_date(date_iso, duration), today)


AUTO_STATUSES = ("active", "completed", "lapsed")


def recompute_statuses(db: Session, today: dt.date | None = None) -> dict:
    """Re-apply the status rule as time passes. Only automatic statuses are touched: anything a
    person set by hand (Stop / Still taking) and superseded entries are left alone."""
    today = today or dt.date.today()
    changed: dict[str, int] = {}
    rows = db.query(Medication).filter(Medication.status.in_(AUTO_STATUSES),
                                       Medication.status_manual.isnot(True)).all()
    for m in rows:
        new = status_for(m.start_date, m.end_date, today)
        if new != m.status:
            key = f"{m.status}->{new}"
            changed[key] = changed.get(key, 0) + 1
            m.status = new
    db.commit()
    return changed


def _unlink(db: Session, doc_id: int) -> None:
    """Reminders and appointments outlive the rows they point at, so drop those links BEFORE the rows are deleted.
    SQLite hands a deleted id to the next new row, which may belong to a different patient: a link left behind
    would then show someone else's record."""
    for owner, column, target in ((Reminder, Reminder.medication_id, Medication),
                                  (Appointment, Appointment.consultation_id, Consultation)):
        doomed = db.query(target.id).filter(target.document_id == doc_id)
        db.query(owner).filter(column.in_(doomed.scalar_subquery())).update({column: None}, synchronize_session=False)


def clear_derived(db: Session, doc_id: int) -> None:
    _unlink(db, doc_id)
    for model in (Medication, LabResult, Consultation, TimelineEvent, Expense):
        db.query(model).filter(model.document_id == doc_id).delete()


def _doc_date(doc: MedicalDocument, extracted: dict) -> str:
    return extracted.get("document_date") or (doc.upload_date or dt.datetime.utcnow()).date().isoformat()


def _supersede_older(db: Session, doc: MedicalDocument, key: str, date_iso: str) -> None:
    """A newer prescription of the same drug replaces older active entries."""
    rows = db.query(Medication).filter(Medication.patient_id == doc.patient_id, Medication.status.in_(("active", "lapsed")),
                                       Medication.document_id != doc.id).all()
    for r in rows:
        if key not in {(r.generic_name or "").lower(), (r.name or "").lower()}:
            continue
        other = db.get(MedicalDocument, r.document_id) if r.document_id else None
        other_date = (other.document_date if other else None) or ""
        if other_date <= date_iso:
            r.status = "superseded"


def persist_extraction(db: Session, doc: MedicalDocument, extracted: dict) -> dict:
    """Create rows from `extracted`. Returns counts. Caller owns nothing: commits here."""
    clear_derived(db, doc.id)
    today_d = dt.date.today()
    date_iso = _doc_date(doc, extracted)
    category = extracted.get("category", "other")
    doctor, hospital = extracted.get("doctor"), extracted.get("hospital")

    # Medications
    n_med = 0
    for m in extracted.get("medications", []):
        key = (m.get("generic_name") or m.get("name") or "").lower()
        end = end_date(date_iso, m.get("duration"))
        _supersede_older(db, doc, key, date_iso)
        db.add(Medication(
            patient_id=doc.patient_id, document_id=doc.id, name=m["name"], generic_name=m.get("generic_name"),
            strength=m.get("strength"), dosage=m.get("dosage"), frequency=m.get("frequency"),
            route=m.get("route"), timing=m.get("timing"), instructions=m.get("instructions"),
            start_date=date_iso, end_date=end, prescribing_doctor=doctor,
            status=med_status(date_iso, m.get("duration"), today_d), confidence=m.get("confidence"),
            generic_inferred=bool(m.get("generic_inferred"))))
        n_med += 1

    # Labs
    abnormal = []
    for l in extracted.get("lab_results", []):
        is_ab = l.get("is_abnormal")            # True / False / None (None = no reference range printed)
        if is_ab:
            abnormal.append(l["test_name"])
        db.add(LabResult(
            patient_id=doc.patient_id, document_id=doc.id,
            lab_name=hospital if category == "lab_report" else None, report_date=date_iso,
            test_name=l["test_name"], test_value=l.get("test_value"), unit=l.get("unit"),
            reference_range=l.get("reference_range"), is_abnormal=is_ab,
            specimen_type=l.get("specimen_type"), confidence=l.get("confidence")))
    n_lab = len(extracted.get("lab_results", []))

    # Consultation
    dx = extracted.get("diagnoses", [])
    if category in CONSULT_CATEGORIES and (dx or doctor):
        db.add(Consultation(
            patient_id=doc.patient_id, document_id=doc.id, doctor_name=doctor, hospital=hospital,
            consultation_date=extracted.get("discharge_date") or date_iso, diagnosis="; ".join(dx) or None,
            follow_up_date=extracted.get("follow_up_date"), notes=extracted.get("follow_up_text"),
            confidence=extracted.get("confidence")))

    # Allergies (dedupe per patient)
    existing = {a.allergen.lower() for a in db.query(Allergy).filter(Allergy.patient_id == doc.patient_id)}
    for a in extracted.get("allergies", []):
        if a.get("allergen") and a["allergen"].lower() not in existing:
            db.add(Allergy(patient_id=doc.patient_id, allergen=a["allergen"], reaction=a.get("reaction")))
            existing.add(a["allergen"].lower())

    # Expense: only when the document printed a total in a currency we recognise
    if extracted.get("bill_total") and extracted.get("bill_currency"):
        db.add(Expense(
            patient_id=doc.patient_id, document_id=doc.id, expense_date=date_iso,
            description=f"Bill - {hospital or doctor or doc.filename}"[:200],
            category=BILL_CATEGORY.get(category, "other"),
            amount_minor=round(extracted["bill_total"] * 100), currency=extracted["bill_currency"]))

    # Timeline
    who = doctor or hospital or "unknown provider"
    if category == "lab_report":
        title = f"Lab report - {hospital or who}"
        desc = f"{n_lab} tests" + (f", {len(abnormal)} abnormal: {', '.join(abnormal[:6])}" if abnormal else ", all normal")
    elif category == "discharge_summary":
        title = f"Hospital discharge - {dx[0] if dx else who}"
        span = f"Admitted {extracted['admission_date']}. " if extracted.get("admission_date") else ""
        desc = span + f"{n_med} discharge medications"
    elif category == "prescription":
        title = f"Prescription - {who}"
        desc = ("; ".join(dx) + ". " if dx else "") + ", ".join(m["name"] for m in extracted.get("medications", []))
    else:
        title, desc = f"{category.replace('_', ' ').title()} - {who}", "; ".join(dx)
    db.add(TimelineEvent(patient_id=doc.patient_id, document_id=doc.id, event_date=date_iso,
                         event_type=category, title=title, description=desc or None))
    db.commit()
    return {"medications": n_med, "lab_results": n_lab, "diagnoses": len(dx)}
