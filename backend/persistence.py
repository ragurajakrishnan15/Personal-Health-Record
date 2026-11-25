"""Turn a document's extracted JSON into relational rows (medications, labs, consultations,
allergies, timeline). Idempotent per document: re-running replaces that document's rows.

Anything that depends on MORE than one document (which prescription replaced which, the allergy list) is worked out
again from what is on file by refresh_patient, so upload order and rejection cannot leave it wrong."""
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


def _drug_key(m: Medication) -> str:
    return (m.generic_name or m.name or "").lower()


def resolve_supersession(db: Session, patient_id: int, today: dt.date | None = None) -> None:
    """A prescription is "superseded" only while a newer document on file lists the same drug. Worked out from the
    rows that exist now: it does not depend on upload order, and removing the newer one brings the older one back.
    Medicines a person stopped (discontinued) are never touched."""
    today = today or dt.date.today()
    rows = db.query(Medication).filter(Medication.patient_id == patient_id).all()
    age = lambda m: (m.start_date or "", m.document_id or 0)       # same date: the later upload counts as newer
    by_key: dict[str, list] = {}
    for m in rows:
        by_key.setdefault(_drug_key(m), []).append((age(m), m.document_id))
    for m in rows:
        if m.status == "discontinued":
            continue
        replaced = any(other_age > age(m) and other_doc != m.document_id
                       for name in {(m.generic_name or "").lower(), (m.name or "").lower()} - {""}
                       for other_age, other_doc in by_key.get(name, []))
        # a manual row that is not discontinued was marked "Still taking" by a person
        own = "active" if m.status_manual else status_for(m.start_date, m.end_date, today)
        if replaced:
            if own in ("active", "lapsed"):                        # a finished short course stays "completed"
                m.status = "superseded"
        elif m.status == "superseded":
            m.status = own


def rebuild_allergies(db: Session, patient_id: int) -> None:
    """The allergy list is exactly what the documents that have not been rejected say."""
    found: dict[str, dict] = {}
    docs = db.query(MedicalDocument).filter(MedicalDocument.patient_id == patient_id,
                                            MedicalDocument.validation_status != "rejected").order_by(MedicalDocument.id)
    for doc in docs:
        for a in (doc.extracted_data or {}).get("allergies", []) or []:
            name = a.get("allergen")
            if not name:
                continue
            entry = found.setdefault(name.lower(), {"allergen": name, "reaction": None})
            entry["reaction"] = entry["reaction"] or a.get("reaction")
    db.query(Allergy).filter(Allergy.patient_id == patient_id).delete()
    for entry in found.values():
        db.add(Allergy(patient_id=patient_id, **entry))


def refresh_patient(db: Session, patient_id: int) -> None:
    """Recalculate everything that depends on more than one document. The caller commits."""
    db.flush()                                 # the session does not autoflush: make pending changes visible first
    resolve_supersession(db, patient_id)
    rebuild_allergies(db, patient_id)


def _remember(db: Session, doc: MedicalDocument) -> tuple[list[dict], list[int]]:
    """What people did with this document's rows, noted before the rows are replaced."""
    meds = []
    for m in db.query(Medication).filter(Medication.document_id == doc.id).order_by(Medication.id):
        reminders = [r.id for r in db.query(Reminder).filter(Reminder.medication_id == m.id,
                                                             Reminder.patient_id == doc.patient_id)]
        meds.append({"name": (m.name or "").lower(), "strength": m.strength, "key": _drug_key(m),
                     "status": m.status, "manual": bool(m.status_manual), "reminders": reminders})
    visits = db.query(Consultation.id).filter(Consultation.document_id == doc.id)
    appointments = [a.id for a in db.query(Appointment).filter(
        Appointment.consultation_id.in_(visits.scalar_subquery()), Appointment.patient_id == doc.patient_id)]
    return meds, appointments


def _match(old: list[dict], new: list[Medication]) -> list[tuple[dict, Medication]]:
    """Pair old and rebuilt medicines: same name and strength first, then the same drug if only one is left.
    No confident match means no pair, so a choice or reminder is never moved to a different medicine."""
    pairs, free = [], list(new)
    waiting = []
    for o in old:
        hit = next((n for n in free if (n.name or "").lower() == o["name"] and n.strength == o["strength"]), None)
        if hit:
            free.remove(hit)
            pairs.append((o, hit))
        else:
            waiting.append(o)
    for o in waiting:
        hits = [n for n in free if _drug_key(n) == o["key"]]
        if len(hits) == 1 and sum(w["key"] == o["key"] for w in waiting) == 1:
            free.remove(hits[0])
            pairs.append((o, hits[0]))
    return pairs


def persist_extraction(db: Session, doc: MedicalDocument, extracted: dict) -> dict:
    """Create rows from `extracted`. Returns counts. Caller owns nothing: commits here."""
    old_meds, old_appointments = _remember(db, doc)
    clear_derived(db, doc.id)
    today_d = dt.date.today()
    date_iso = _doc_date(doc, extracted)
    category = extracted.get("category", "other")
    doctor, hospital = extracted.get("doctor"), extracted.get("hospital")

    # Medications
    new_meds = []
    for m in extracted.get("medications", []):
        end = end_date(date_iso, m.get("duration"))
        new_meds.append(Medication(
            patient_id=doc.patient_id, document_id=doc.id, name=m["name"], generic_name=m.get("generic_name"),
            strength=m.get("strength"), dosage=m.get("dosage"), frequency=m.get("frequency"),
            route=m.get("route"), timing=m.get("timing"), instructions=m.get("instructions"),
            start_date=date_iso, end_date=end, prescribing_doctor=doctor,
            status=med_status(date_iso, m.get("duration"), today_d), confidence=m.get("confidence"),
            generic_inferred=bool(m.get("generic_inferred"))))
    db.add_all(new_meds)
    db.flush()                                                   # ids are needed to restore reminder links
    for old, new in _match(old_meds, new_meds):
        if old["manual"]:                                        # Stop / Still taking survive a rebuild
            new.status_manual = True
            new.status = "discontinued" if old["status"] == "discontinued" else "active"
        if old["reminders"]:
            db.query(Reminder).filter(Reminder.id.in_(old["reminders"])).update({"medication_id": new.id})
    n_med = len(new_meds)

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
        visit = Consultation(
            patient_id=doc.patient_id, document_id=doc.id, doctor_name=doctor, hospital=hospital,
            consultation_date=extracted.get("discharge_date") or date_iso, diagnosis="; ".join(dx) or None,
            follow_up_date=extracted.get("follow_up_date"), notes=extracted.get("follow_up_text"),
            confidence=extracted.get("confidence"))
        db.add(visit)
        db.flush()
        if old_appointments:                                     # keep an accepted follow-up accepted
            db.query(Appointment).filter(Appointment.id.in_(old_appointments)).update({"consultation_id": visit.id})

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
    refresh_patient(db, doc.patient_id)
    db.commit()
    return {"medications": n_med, "lab_results": n_lab, "diagnoses": len(dx)}
