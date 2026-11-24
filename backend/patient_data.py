"""Export a patient's records (data portability) and permanently delete them (erasure). Owner only.

Export: one ZIP with machine-readable JSON, spreadsheet-friendly CSVs and the original uploaded files. The caller's
own assistant conversation is included; other people's private conversations never are.
Delete: irreversible and re-authenticated (type the name + enter your password). Removes every row and uploaded file for
the patient. The audit log keeps ids and counts only (never names or contents) as proof the deletion happened.
"""
import csv
import datetime as dt
import io
import json
import os
import re
import tempfile
import zipfile

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

import auth
from database import (UPLOAD_DIR, Allergy, Appointment, ChatMessage, Consultation, LabResult, MedicalDocument, Medication,
                      Patient, PatientAccess, Reminder, TimelineEvent, User, get_db)

router = APIRouter()


class DeleteIn(BaseModel):
    confirm_name: str
    password: str


def _row(obj) -> dict:
    out = {}
    for c in obj.__table__.columns:
        v = getattr(obj, c.name)
        out[c.name] = v.isoformat() if isinstance(v, (dt.datetime, dt.date)) else v
    return out


def _csv_safe(v):
    """Values come from AI-read documents: stop spreadsheets treating them as formulas."""
    s = "" if v is None else str(v)
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s


def _csv(rows: list[dict], cols: list[str]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(cols)
    for r in rows:
        w.writerow([_csv_safe(r.get(c)) for c in cols])
    return buf.getvalue()


def _safe_name(name: str) -> str:
    base = os.path.basename((name or "document").replace("\\", "/"))
    return re.sub(r"[^A-Za-z0-9._ -]", "_", base)[:80] or "document"


def _inside_uploads(path: str) -> bool:
    root = os.path.realpath(UPLOAD_DIR)
    return os.path.realpath(path).startswith(root + os.sep)


README = """HealthVault export
Generated: {when} (UTC)

patient.json     everything stored about this person (profile, medications, lab results, allergies, visits,
                 timeline, appointments, reminders, and the documents' extracted data with review status)
medications.csv  medications, one per row
lab_results.csv  lab results, one per row ("is_abnormal" is blank when the report printed no reference range)
documents/       the original files you uploaded
my_chat.json     YOUR conversation with the assistant about this person (other people's conversations are not included)

Important: values were read from documents by AI. Rows with validation_status "pending_review" have not been checked by
a person, and "confidence" is the model's own estimate. Check against the original files in documents/ before relying on
them. This export contains sensitive health information - store and share it carefully.
"""


@router.get("/api/patients/{patient_id}/export")
def export_patient(patient_id: int, request: Request, db: Session = Depends(get_db),
                   user: User = Depends(auth.current_user)):
    if not auth.throttle(f"export:{user.id}", 5, 3600):
        raise HTTPException(429, "Too many exports. Try again later.")
    p = db.get(Patient, patient_id)
    if not p:
        raise HTTPException(404, "Not found")
    q = lambda m: [_row(r) for r in db.query(m).filter(m.patient_id == patient_id).order_by(m.id)]
    docs = db.query(MedicalDocument).filter(MedicalDocument.patient_id == patient_id).order_by(MedicalDocument.id).all()
    meds, labs = q(Medication), q(LabResult)
    chat = [{"role": m.role, "content": m.content, "sources": m.sources, "created_at": m.created_at.isoformat()}
            for m in db.query(ChatMessage).filter(ChatMessage.patient_id == patient_id, ChatMessage.user_id == user.id)
            .order_by(ChatMessage.created_at, ChatMessage.id)]

    tmp = tempfile.NamedTemporaryFile(prefix="phr-export-", suffix=".zip", delete=False)
    n_files = 0
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("README.txt", README.format(when=dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M")))
        z.writestr("patient.json", json.dumps({
            "patient": _row(p), "allergies": q(Allergy), "medications": meds, "lab_results": labs,
            "consultations": q(Consultation), "timeline": q(TimelineEvent),
            "appointments": q(Appointment), "reminders": q(Reminder),
            "documents": [{**_row(d), "file_path": None,
                           "exported_file": f"documents/{d.id}-{_safe_name(d.filename)}"} for d in docs],
        }, indent=2, ensure_ascii=False))
        z.writestr("medications.csv", _csv(meds, ["name", "generic_name", "strength", "dosage", "frequency", "route",
                                                  "timing", "instructions", "start_date", "end_date",
                                                  "prescribing_doctor", "status", "confidence"]))
        z.writestr("lab_results.csv", _csv(labs, ["report_date", "test_name", "test_value", "unit", "reference_range",
                                                  "is_abnormal", "lab_name", "specimen_type", "confidence"]))
        z.writestr("my_chat.json", json.dumps(chat, indent=2, ensure_ascii=False))
        for d in docs:
            if d.file_path and _inside_uploads(d.file_path) and os.path.isfile(d.file_path):
                z.write(d.file_path, f"documents/{d.id}-{_safe_name(d.filename)}")
                n_files += 1
    auth.audit(db, request, user.id, patient_id, "patient_exported", f"{len(docs)} documents, {n_files} files")
    name = f"healthvault-export-{patient_id}-{dt.date.today().isoformat()}.zip"     # no personal data in the filename
    return FileResponse(tmp.name, media_type="application/zip", filename=name,
                        background=BackgroundTask(os.remove, tmp.name))


@router.delete("/api/patients/{patient_id}", status_code=200)
def delete_patient(patient_id: int, body: DeleteIn, request: Request, db: Session = Depends(get_db),
                   user: User = Depends(auth.current_user)):
    if not auth.throttle(f"delpatient:{user.id}", 5, 600):
        raise HTTPException(429, "Too many attempts. Try again in a few minutes.")
    p = db.get(Patient, patient_id)
    if not p:
        raise HTTPException(404, "Not found")
    if body.confirm_name.strip() != p.name.strip():
        raise HTTPException(422, "The name you typed does not match.")
    if not auth.verify_password(body.password, user.password_hash):
        auth.audit(db, request, user.id, patient_id, "patient_delete_bad_password")
        raise HTTPException(403, "Password is incorrect.")
    docs = db.query(MedicalDocument).filter(MedicalDocument.patient_id == patient_id).all()
    if any(d.processing_status == "processing" for d in docs):
        raise HTTPException(409, "A document is still being read. Wait for it to finish (or stop it), then delete.")

    paths = [d.file_path for d in docs if d.file_path]
    # children first: rows reference documents and the patient
    for m in (ChatMessage, TimelineEvent, Appointment, Reminder, Consultation, LabResult, Medication, Allergy, MedicalDocument, PatientAccess):
        db.query(m).filter(m.patient_id == patient_id).delete()
    db.delete(p)
    db.commit()

    removed = failed = 0
    for path in paths:                       # only ever inside the uploads folder
        try:
            if _inside_uploads(path) and os.path.isfile(path):
                os.remove(path)
                removed += 1
        except OSError:
            failed += 1
    auth.audit(db, request, user.id, patient_id, "patient_deleted",
               f"{len(docs)} documents, {removed} files removed" + (f", {failed} files could not be removed" if failed else ""))
    return {"deleted": True, "documents": len(docs), "files_removed": removed, "files_failed": failed}
