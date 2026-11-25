"""FastAPI backend for Personal Health Records Platform."""
import asyncio
import logging
import os
import uuid
from contextlib import asynccontextmanager
from datetime import date, datetime
from fastapi import BackgroundTasks, FastAPI, Request, UploadFile, File, Depends, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel

from database import init_db, get_db, SessionLocal, UPLOAD_DIR, Patient, MedicalDocument, Medication, \
    LabResult, Consultation, Allergy, TimelineEvent, ChatMessage, User, PatientAccess
from ai_service import extract_from_document
from chat_context import build_context
import chat_service
import auth
from auth_routes import router as auth_router
from account_routes import router as account_router
from patient_data import router as patient_data_router
from schedule_routes import router as schedule_router
from expense_routes import router as expense_router, expense_rows, totals_by_currency
from persistence import persist_extraction, clear_derived, refresh_patient
from corrections import check_corrected

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    task = asyncio.create_task(_recompute_loop()) if RECOMPUTE_HOURS > 0 else None
    try:
        yield
    finally:
        if task:
            task.cancel()


# Default deny: auth.guard runs on EVERY route (see auth.PUBLIC for the few open ones).
app = FastAPI(title="Health Records Platform API", version="0.2.0", dependencies=[Depends(auth.guard)], lifespan=lifespan)
app.include_router(auth_router)
app.include_router(account_router)
app.include_router(patient_data_router)
app.include_router(schedule_router)
app.include_router(expense_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=auth.CORS_ORIGINS,          # explicit origins only: credentials + "*" is unsafe
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Content-Type"],
)


@app.middleware("http")
async def security_layer(request: Request, call_next):
    # CSRF defence in depth on top of SameSite=Lax cookies: a browser always labels cross-site writes with their Origin.
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        origin = request.headers.get("origin")
        same_host = origin is not None and origin.split("//", 1)[-1] == request.headers.get("host")
        if origin and origin not in auth.CORS_ORIGINS and not same_host:
            return JSONResponse({"detail": "Cross-origin request blocked"}, status_code=403)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    if request.url.path.startswith("/api"):
        response.headers["Cache-Control"] = "no-store"       # health data must not sit in shared caches
    return response


log = logging.getLogger("phr")
os.makedirs(UPLOAD_DIR, exist_ok=True)
ALLOWED_EXT = {".pdf", ".jpg", ".jpeg", ".png"}
MAX_UPLOAD_BYTES = 15 * 1024 * 1024


RECOMPUTE_HOURS = float(os.getenv("STATUS_RECOMPUTE_HOURS", "24"))   # 0 disables the background job


def _recompute_once():
    from persistence import recompute_statuses
    db = SessionLocal()
    try:
        return recompute_statuses(db)
    finally:
        db.close()


async def _recompute_loop():
    while True:
        try:
            changed = await asyncio.to_thread(_recompute_once)
            if changed:
                log.info("medication statuses recomputed: %s", changed)
        except Exception:                      # never let the scheduler die
            log.exception("medication status recompute failed")
        await asyncio.sleep(RECOMPUTE_HOURS * 3600)


# ══════════════════════════════════════════════════════════
#  Pydantic schemas
# ══════════════════════════════════════════════════════════

class PatientCreate(BaseModel):
    name: str
    age: int | None = None
    gender: str | None = None
    blood_group: str | None = None
    phone: str | None = None
    email: str | None = None

class PatientOut(BaseModel):
    id: int
    name: str
    age: int | None
    gender: str | None
    blood_group: str | None
    phone: str | None
    email: str | None
    role: str | None = None        # the caller's role on this patient
    class Config:
        from_attributes = True

class MedicationOut(BaseModel):
    id: int
    name: str
    generic_name: str | None
    strength: str | None
    dosage: str | None
    frequency: str | None
    timing: str | None
    instructions: str | None
    start_date: str | None
    end_date: str | None
    prescribing_doctor: str | None
    status: str
    generic_inferred: bool | None = False
    class Config:
        from_attributes = True

class LabResultOut(BaseModel):
    id: int
    test_name: str
    test_value: str | None
    unit: str | None
    reference_range: str | None
    is_abnormal: bool | None = None
    report_date: str | None
    lab_name: str | None
    document_id: int | None = None
    class Config:
        from_attributes = True

class DocumentOut(BaseModel):
    id: int
    filename: str
    category: str
    document_date: str | None
    upload_date: datetime | None
    hospital: str | None
    doctor: str | None
    validation_status: str
    processing_status: str | None = None
    processing_error: str | None = None
    extracted_data: dict | None
    class Config:
        from_attributes = True

class TimelineEventOut(BaseModel):
    id: int
    event_date: str
    event_type: str
    title: str
    description: str | None
    class Config:
        from_attributes = True

class ChatRequest(BaseModel):
    patient_id: int
    message: str

class ChatResponse(BaseModel):
    reply: str
    sources: list[dict] = []

class ValidationUpdate(BaseModel):
    validation_status: str  # verified, corrected, rejected
    corrected_data: dict | None = None


# ══════════════════════════════════════════════════════════
#  PATIENTS
# ══════════════════════════════════════════════════════════

def _patient_out(p: Patient, role: str) -> PatientOut:
    return PatientOut(id=p.id, name=p.name, age=p.age, gender=p.gender, blood_group=p.blood_group,
                      phone=p.phone, email=p.email, role=role)


@app.post("/api/patients", response_model=PatientOut)
def create_patient(patient: PatientCreate, request: Request, db: Session = Depends(get_db),
                   user: User = Depends(auth.current_user)):
    db_patient = Patient(**patient.model_dump())
    db.add(db_patient)
    db.commit()
    db.refresh(db_patient)
    db.add(PatientAccess(user_id=user.id, patient_id=db_patient.id, role="owner"))   # the creator owns the record
    db.commit()
    auth.audit(db, request, user.id, db_patient.id, "patient_created")
    return _patient_out(db_patient, "owner")


@app.get("/api/patients", response_model=list[PatientOut])
def list_patients(db: Session = Depends(get_db), user: User = Depends(auth.current_user)):
    """Only patients this user has been given access to."""
    rows = db.query(Patient, PatientAccess.role).join(PatientAccess, PatientAccess.patient_id == Patient.id) \
        .filter(PatientAccess.user_id == user.id).order_by(Patient.id).all()
    return [_patient_out(p, role) for p, role in rows]


@app.get("/api/patients/{patient_id}", response_model=PatientOut)
def get_patient(patient_id: int, request: Request, db: Session = Depends(get_db)):
    patient = db.query(Patient).filter(Patient.id == patient_id).first()
    if not patient:
        raise HTTPException(404, "Not found")
    return _patient_out(patient, request.state.role)


# ══════════════════════════════════════════════════════════
#  DOCUMENT UPLOAD & AI EXTRACTION
# ══════════════════════════════════════════════════════════

async def process_document(doc_id: int) -> None:
    """Background job: run AI extraction, store the JSON, create medication/lab/timeline rows."""
    db = SessionLocal()
    try:
        doc = db.get(MedicalDocument, doc_id)
        if not doc:
            return
        extracted = await extract_from_document(doc.file_path)
        issues = extracted.get("validation_issues") or []
        failed = bool(issues) and str(issues[0]).startswith("extraction failed")
        db.refresh(doc)                       # a person may have rejected it while it was being read
        if failed and doc.extracted_data and (doc.extracted_data.get("medications") or doc.extracted_data.get("lab_results")
                                              or doc.extracted_data.get("allergies")):
            # re-reading failed: keep what was read before, so the records built from it still have their source
            doc.processing_status, doc.processing_error = "failed", issues[0]
            db.commit()
            return
        doc.extracted_data = extracted
        doc.category = extracted.get("category", "other")
        doc.document_date = extracted.get("document_date")
        doc.hospital = extracted.get("hospital")
        doc.doctor = extracted.get("doctor")
        if failed:
            doc.processing_status, doc.processing_error = "failed", issues[0]
            db.commit()
        else:
            doc.processing_status, doc.processing_error = "done", None
            db.commit()
            if doc.validation_status != "rejected":
                persist_extraction(db, doc, extracted)
    except Exception as e:  # never leave a document stuck in "processing"
        db.rollback()
        doc = db.get(MedicalDocument, doc_id)
        if doc:
            doc.processing_status, doc.processing_error = "failed", f"{type(e).__name__}: {e}"
            db.commit()
    finally:
        db.close()


@app.post("/api/patients/{patient_id}/documents", response_model=DocumentOut, status_code=202)
async def upload_document(
    patient_id: int,
    request: Request,
    background: BackgroundTasks,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Save the upload and return immediately; AI extraction runs in the background.
    Poll GET /api/documents/{id} until processing_status is 'done' or 'failed'."""
    patient = db.query(Patient).filter(Patient.id == patient_id).first()
    if not patient:
        raise HTTPException(404, "Patient not found")

    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_EXT:
        raise HTTPException(415, f"Unsupported file type. Allowed: {', '.join(sorted(ALLOWED_EXT))}")

    # Server-chosen filename: the client's name is never used as a path (prevents path traversal)
    file_path = os.path.join(UPLOAD_DIR, f"{uuid.uuid4().hex}{ext}")
    size = 0
    with open(file_path, "wb") as f:
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_UPLOAD_BYTES:
                f.close()
                os.remove(file_path)
                raise HTTPException(413, "File too large (max 15 MB)")
            f.write(chunk)

    doc = MedicalDocument(patient_id=patient_id, filename=os.path.basename(file.filename or "upload" + ext),
                          file_path=file_path, category="other", validation_status="pending_review",
                          processing_status="processing")
    db.add(doc)
    db.commit()
    db.refresh(doc)
    auth.audit(db, request, request.state.user.id, patient_id, "document_uploaded", f"doc {doc.id}")
    background.add_task(process_document, doc.id)
    return doc


@app.get("/api/documents/{doc_id}", response_model=DocumentOut)
def get_document(doc_id: int, db: Session = Depends(get_db)):
    doc = db.get(MedicalDocument, doc_id)
    if not doc:
        raise HTTPException(404, "Document not found")
    return doc


@app.get("/api/documents/{doc_id}/file")
def get_document_file(doc_id: int, request: Request, db: Session = Depends(get_db)):
    """Serve the original upload. Access is checked by auth.guard (viewer or above on the document's patient)."""
    doc = db.get(MedicalDocument, doc_id)
    if not doc or not os.path.isfile(doc.file_path):
        raise HTTPException(404, "File not found")
    auth.audit(db, request, request.state.user.id, doc.patient_id, "document_viewed", f"doc {doc_id}")
    ext = os.path.splitext(doc.file_path)[1].lower()
    media = {".pdf": "application/pdf", ".png": "image/png"}.get(ext, "image/jpeg")
    return FileResponse(doc.file_path, media_type=media, headers={"Content-Disposition": "inline"})


@app.post("/api/documents/{doc_id}/reprocess", response_model=DocumentOut, status_code=202)
def reprocess_document(doc_id: int, background: BackgroundTasks, db: Session = Depends(get_db)):
    doc = db.get(MedicalDocument, doc_id)
    if not doc:
        raise HTTPException(404, "Document not found")
    doc.processing_status, doc.processing_error, doc.validation_status = "processing", None, "pending_review"
    db.commit()
    background.add_task(process_document, doc.id)
    return doc


@app.get("/api/patients/{patient_id}/documents", response_model=list[DocumentOut])
def list_documents(patient_id: int, db: Session = Depends(get_db)):
    return db.query(MedicalDocument).filter(
        MedicalDocument.patient_id == patient_id
    ).order_by(MedicalDocument.upload_date.desc()).all()


@app.put("/api/documents/{doc_id}/validate")
def validate_document(doc_id: int, body: ValidationUpdate, request: Request, db: Session = Depends(get_db)):
    """User verifies, corrects or rejects AI-extracted data. Derived rows follow the decision."""
    if body.validation_status not in ("verified", "corrected", "rejected"):
        raise HTTPException(422, "validation_status must be verified, corrected or rejected")
    doc = db.query(MedicalDocument).filter(MedicalDocument.id == doc_id).first()
    if not doc:
        raise HTTPException(404, "Document not found")
    corrected = None
    if body.corrected_data and body.validation_status != "rejected":
        corrected = check_corrected(body.corrected_data)       # raises 422 before anything is changed
    was_rejected = doc.validation_status == "rejected"
    doc.validation_status = body.validation_status
    if body.validation_status == "rejected":
        clear_derived(db, doc.id)
        refresh_patient(db, doc.patient_id)                    # older prescriptions come back, its allergies go
        db.commit()
    elif corrected:
        doc.extracted_data = corrected
        for k in ("category", "document_date", "hospital", "doctor"):
            if corrected.get(k):
                setattr(doc, k, corrected[k])
        db.commit()
        persist_extraction(db, doc, corrected)
    elif was_rejected and doc.extracted_data and doc.processing_status != "processing":
        db.commit()
        persist_extraction(db, doc, doc.extracted_data)        # accepted after all: rebuild what rejection removed
    else:
        db.commit()
    auth.audit(db, request, request.state.user.id, doc.patient_id, f"document_{body.validation_status}", f"doc {doc_id}")
    return {"status": "updated"}


# ══════════════════════════════════════════════════════════
#  MEDICATIONS
# ══════════════════════════════════════════════════════════

@app.get("/api/patients/{patient_id}/medications", response_model=list[MedicationOut])
def list_medications(
    patient_id: int,
    status: str | None = None,
    db: Session = Depends(get_db),
):
    q = db.query(Medication).filter(Medication.patient_id == patient_id)
    if status:
        q = q.filter(Medication.status == status)
    return q.all()


@app.put("/api/medications/{med_id}/status")
def update_medication_status(med_id: int, status: str = Query(...), db: Session = Depends(get_db)):
    med = db.query(Medication).filter(Medication.id == med_id).first()
    if not med:
        raise HTTPException(404, "Medication not found")
    if status not in {"active", "discontinued"}:
        raise HTTPException(422, "Status can only be set to active or discontinued")
    med.status = status
    med.status_manual = True
    db.commit()
    return {"status": "updated"}


# ══════════════════════════════════════════════════════════
#  LAB RESULTS
# ══════════════════════════════════════════════════════════

@app.get("/api/patients/{patient_id}/lab-results", response_model=list[LabResultOut])
def list_lab_results(
    patient_id: int,
    test_name: str | None = None,
    db: Session = Depends(get_db),
):
    q = db.query(LabResult).filter(LabResult.patient_id == patient_id)
    if test_name:
        q = q.filter(LabResult.test_name.ilike(f"%{test_name}%"))
    return q.order_by(LabResult.report_date.desc()).all()


@app.get("/api/patients/{patient_id}/allergies")
def list_allergies(patient_id: int, db: Session = Depends(get_db)):
    return [{"id": a.id, "allergen": a.allergen, "reaction": a.reaction, "severity": a.severity}
            for a in db.query(Allergy).filter(Allergy.patient_id == patient_id)]


# ══════════════════════════════════════════════════════════
#  TIMELINE
# ══════════════════════════════════════════════════════════

@app.get("/api/patients/{patient_id}/timeline", response_model=list[TimelineEventOut])
def get_timeline(patient_id: int, db: Session = Depends(get_db)):
    return db.query(TimelineEvent).filter(
        TimelineEvent.patient_id == patient_id
    ).order_by(TimelineEvent.event_date.desc()).all()


# ══════════════════════════════════════════════════════════
#  AI CHAT
# ══════════════════════════════════════════════════════════

@app.post("/api/chat", response_model=ChatResponse)
async def chat(req: ChatRequest, request: Request, db: Session = Depends(get_db),
               user: User = Depends(auth.current_user)):
    """Grounded Q&A over the patient's records. Nothing is saved unless the model actually answered."""
    message = req.message.strip()
    if not message:
        raise HTTPException(422, "Message is empty")
    if len(message) > chat_service.MAX_QUESTION_CHARS:
        raise HTTPException(422, f"Message too long (max {chat_service.MAX_QUESTION_CHARS} characters)")
    auth.authorize(db, request, user, req.patient_id, "viewer")     # patient id is in the body, so check it here
    patient = db.query(Patient).filter(Patient.id == req.patient_id).first()
    if not patient:
        raise HTTPException(404, "Not found")

    context = build_context(db, patient)
    history = db.query(ChatMessage).filter(ChatMessage.patient_id == req.patient_id, ChatMessage.user_id == user.id) \
        .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc()).limit(chat_service.HISTORY_TURNS).all()
    chat_history = [{"role": m.role, "content": m.content} for m in reversed(history)]

    try:
        reply, used = await chat_service.answer(message, context, chat_history)
    except Exception:
        raise HTTPException(503, "The assistant is temporarily unavailable. Please try again in a moment.")

    db.add(ChatMessage(patient_id=req.patient_id, user_id=user.id, role="user", content=message))
    db.add(ChatMessage(patient_id=req.patient_id, user_id=user.id, role="assistant", content=reply, sources=used))
    db.commit()
    auth.audit(db, request, user.id, req.patient_id, "chat_question")      # no message text in the audit log
    return ChatResponse(reply=reply, sources=used)


@app.get("/api/patients/{patient_id}/chat-history")
def get_chat_history(patient_id: int, request: Request, db: Session = Depends(get_db)):
    messages = db.query(ChatMessage).filter(
        ChatMessage.patient_id == patient_id, ChatMessage.user_id == request.state.user.id
    ).order_by(ChatMessage.created_at.asc(), ChatMessage.id.asc()).all()
    return [{"role": m.role, "content": m.content, "sources": m.sources or [], "created_at": m.created_at}
            for m in messages]


@app.delete("/api/patients/{patient_id}/chat-history", status_code=204)
def clear_chat_history(patient_id: int, request: Request, db: Session = Depends(get_db)):
    db.query(ChatMessage).filter(ChatMessage.patient_id == patient_id, ChatMessage.user_id == request.state.user.id).delete()
    db.commit()


# ══════════════════════════════════════════════════════════
#  HEALTH ANALYTICS (summary endpoint)
# ══════════════════════════════════════════════════════════

@app.get("/api/patients/{patient_id}/health-summary")
def get_health_summary(patient_id: int, db: Session = Depends(get_db)):
    """Dashboard summary: active meds count, recent labs, upcoming appointments, etc."""
    patient = db.query(Patient).filter(Patient.id == patient_id).first()
    if not patient:
        raise HTTPException(404, "Patient not found")

    active_meds = db.query(Medication).filter(
        Medication.patient_id == patient_id,
        Medication.status == "active",
    ).count()

    total_docs = db.query(MedicalDocument).filter(
        MedicalDocument.patient_id == patient_id
    ).count()

    pending_reviews = db.query(MedicalDocument).filter(
        MedicalDocument.patient_id == patient_id,
        MedicalDocument.validation_status == "pending_review",
    ).count()

    recent_labs = db.query(LabResult).filter(
        LabResult.patient_id == patient_id
    ).order_by(LabResult.report_date.desc()).limit(5).all()

    upcoming = db.query(Consultation).filter(
        Consultation.patient_id == patient_id,
        Consultation.follow_up_date >= date.today().isoformat(),
    ).count()
    abnormal = db.query(LabResult).filter(
        LabResult.patient_id == patient_id, LabResult.is_abnormal.is_(True)
    ).count()

    return {
        "patient": {"id": patient.id, "name": patient.name},
        "upcoming_followups": upcoming,
        "expense_totals": totals_by_currency(expense_rows(db, patient_id)),
        "abnormal_labs": abnormal,
        "active_medications": active_meds,
        "total_documents": total_docs,
        "pending_reviews": pending_reviews,
        "recent_labs": [
            {"test": r.test_name, "value": r.test_value, "unit": r.unit,
             "date": r.report_date, "abnormal": r.is_abnormal}
            for r in recent_labs
        ],
    }


# Optional: serve the built frontend from this same app (single-container deploys such as Render).
# Mounted last so every /api route above wins. Unknown paths fall back to index.html for client-side routing.
_DIST = os.getenv("FRONTEND_DIST")
if _DIST and os.path.isfile(os.path.join(_DIST, "index.html")):
    class _SPAFiles(StaticFiles):
        async def get_response(self, path, scope):
            try:
                resp = await super().get_response(path, scope)
            except StarletteHTTPException as e:
                if e.status_code != 404:
                    raise
                resp = None
            if resp is None or resp.status_code == 404:
                # a missing API route or missing hashed asset must be a real 404, never the app shell
                if scope.get("path", "").startswith(("/api", "/assets")):
                    raise HTTPException(status_code=404)
                resp = await super().get_response("index.html", scope)
            # The app shell must be revalidated on every visit, otherwise a cached index.html points at
            # asset files that no longer exist after a deploy (blank page). Hashed assets never change.
            resp.headers["Cache-Control"] = ("public, max-age=31536000, immutable"
                                             if scope.get("path", "").startswith("/assets/") else "no-cache")
            return resp

    app.mount("/", _SPAFiles(directory=_DIST, html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000)
