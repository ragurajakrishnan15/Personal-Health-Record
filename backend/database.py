"""Database models — SQLAlchemy + SQLite."""
import datetime
import os
from sqlalchemy import (
    create_engine, Column, Integer, String, Text, Float,
    DateTime, Boolean, ForeignKey, JSON, UniqueConstraint,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship

from dotenv import load_dotenv

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./health_records.db")
UPLOAD_DIR = os.getenv("UPLOAD_DIR", "../uploads")
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


# ── Patients ──────────────────────────────────────────────
class Patient(Base):
    __tablename__ = "patients"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    age = Column(Integer)
    gender = Column(String)
    blood_group = Column(String)
    phone = Column(String)
    email = Column(String)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    documents = relationship("MedicalDocument", back_populates="patient")
    medications = relationship("Medication", back_populates="patient")
    lab_results = relationship("LabResult", back_populates="patient")
    consultations = relationship("Consultation", back_populates="patient")
    allergies = relationship("Allergy", back_populates="patient")
    timeline_events = relationship("TimelineEvent", back_populates="patient")


# ── Documents ─────────────────────────────────────────────
class MedicalDocument(Base):
    __tablename__ = "medical_documents"
    id = Column(Integer, primary_key=True, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False)
    filename = Column(String, nullable=False)
    file_path = Column(String, nullable=False)
    category = Column(String, default="other")
    document_date = Column(String)
    upload_date = Column(DateTime, default=datetime.datetime.utcnow)
    hospital = Column(String)
    doctor = Column(String)
    extracted_data = Column(JSON)
    validation_status = Column(String, default="pending_review")
    processing_status = Column(String, default="processing")  # processing | done | failed
    processing_error = Column(Text)
    notes = Column(Text)

    patient = relationship("Patient", back_populates="documents")


# ── Medications ───────────────────────────────────────────
class Medication(Base):
    __tablename__ = "medications"
    id = Column(Integer, primary_key=True, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False)
    document_id = Column(Integer, ForeignKey("medical_documents.id"), nullable=True)
    name = Column(String, nullable=False)
    generic_name = Column(String)
    strength = Column(String)
    dosage = Column(String)
    frequency = Column(String)
    route = Column(String)
    timing = Column(String)
    instructions = Column(String)
    start_date = Column(String)
    end_date = Column(String)
    prescribing_doctor = Column(String)
    status = Column(String, default="active")
    confidence = Column(Float)
    generic_inferred = Column(Boolean, default=False)   # generic name was guessed from the brand: user should verify
    status_manual = Column(Boolean, default=False)       # a person set the status; automatic recompute leaves it alone

    patient = relationship("Patient", back_populates="medications")


# ── Lab Results ───────────────────────────────────────────
class LabResult(Base):
    __tablename__ = "lab_results"
    id = Column(Integer, primary_key=True, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False)
    document_id = Column(Integer, ForeignKey("medical_documents.id"), nullable=True)
    lab_name = Column(String)
    report_date = Column(String)
    test_name = Column(String, nullable=False)
    test_value = Column(String)
    unit = Column(String)
    reference_range = Column(String)
    is_abnormal = Column(Boolean)   # None = unknown (no reference range printed); never default to False
    specimen_type = Column(String)
    comments = Column(Text)
    confidence = Column(Float)

    patient = relationship("Patient", back_populates="lab_results")


# ── Consultations ─────────────────────────────────────────
class Consultation(Base):
    __tablename__ = "consultations"
    id = Column(Integer, primary_key=True, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False)
    document_id = Column(Integer, ForeignKey("medical_documents.id"), nullable=True)
    doctor_name = Column(String)
    hospital = Column(String)
    consultation_date = Column(String)
    diagnosis = Column(Text)
    symptoms = Column(Text)
    follow_up_date = Column(String)
    notes = Column(Text)
    confidence = Column(Float)

    patient = relationship("Patient", back_populates="consultations")


# ── Allergies ─────────────────────────────────────────────
class Allergy(Base):
    __tablename__ = "allergies"
    id = Column(Integer, primary_key=True, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False)
    allergen = Column(String, nullable=False)
    reaction = Column(String)
    severity = Column(String)

    patient = relationship("Patient", back_populates="allergies")


# ── Timeline ──────────────────────────────────────────────
class TimelineEvent(Base):
    __tablename__ = "timeline_events"
    id = Column(Integer, primary_key=True, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False)
    document_id = Column(Integer, ForeignKey("medical_documents.id"), nullable=True)
    event_date = Column(String, nullable=False)
    event_type = Column(String, nullable=False)
    title = Column(String, nullable=False)
    description = Column(Text)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    patient = relationship("Patient", back_populates="timeline_events")


# ── Chat ──────────────────────────────────────────────────
class ChatMessage(Base):
    __tablename__ = "chat_messages"
    id = Column(Integer, primary_key=True, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False)
    role = Column(String, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)   # conversations are private to each user
    content = Column(Text, nullable=False)
    sources = Column(JSON)          # documents cited in an assistant reply
    created_at = Column(DateTime, default=datetime.datetime.utcnow)



# ── Authentication & access control ───────────────────────
class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, nullable=False, index=True)   # stored lower-case
    name = Column(String, nullable=False)
    password_hash = Column(String, nullable=False)                    # scrypt$N$r$p$salt$hash — never the password
    is_active = Column(Boolean, default=True)
    failed_attempts = Column(Integer, default=0)
    locked_until = Column(DateTime)
    email_verified_at = Column(DateTime)                              # NULL until the user proves they own the mailbox
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class EmailToken(Base):
    """One-time link for email verification / password reset. Only a SHA-256 of the token is stored."""
    __tablename__ = "email_tokens"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    purpose = Column(String, nullable=False)          # verify | reset
    token_hash = Column(String, unique=True, nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)
    used_at = Column(DateTime)


class UserSession(Base):
    """Server-side login session. Only a SHA-256 of the cookie token is stored, so a database leak can't be replayed."""
    __tablename__ = "user_sessions"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    token_hash = Column(String, unique=True, nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    last_used = Column(DateTime, default=datetime.datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)
    user_agent = Column(String)


class PatientAccess(Base):
    """Who may see which patient, and what they may do: owner (manage sharing) > editor (upload/validate) > viewer."""
    __tablename__ = "patient_access"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False, index=True)
    role = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    __table_args__ = (UniqueConstraint("user_id", "patient_id", name="uq_access_user_patient"),)


class AuditLog(Base):
    """Who did what to whose record. Never stores record contents, passwords or tokens."""
    __tablename__ = "audit_log"
    id = Column(Integer, primary_key=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, index=True)
    user_id = Column(Integer, index=True)
    patient_id = Column(Integer, index=True)
    action = Column(String, nullable=False)
    detail = Column(String)
    ip = Column(String)


# ── Helpers ───────────────────────────────────────────────
def _add_missing_columns():
    """Tiny forward-only migration: add columns that models gained since the database was created.
    (Stopgap until Alembic is introduced; only handles simple nullable columns.)"""
    from sqlalchemy import inspect, text
    insp = inspect(engine)
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if not insp.has_table(table.name):
                continue
            have = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name not in have:
                    ddl = col.type.compile(engine.dialect)
                    default = " DEFAULT 0" if isinstance(col.type, Boolean) else ""
                    conn.execute(text(f'ALTER TABLE {table.name} ADD COLUMN {col.name} {ddl}{default}'))


def init_db():
    Base.metadata.create_all(bind=engine)
    _add_missing_columns()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
