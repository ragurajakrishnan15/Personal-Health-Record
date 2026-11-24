"""Appointments and reminders.

Appointments: entered by hand, or created from a follow-up date the AI read off a document (a "suggestion" the user
accepts - nothing is created automatically, because extracted dates can be wrong).
Reminders: one-off or repeating (daily / weekly / monthly), optionally tied to a medication. They are shown in the app;
nothing is pushed to a phone or emailed (see HANDOFF.md).

Access is enforced centrally in auth.guard from the URL (patient_id / appt_id / rem_id): viewers read, editors write.
Audit entries hold ids and actions only - never titles or notes, which can contain health information.
"""
import calendar
import datetime as dt
import re
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

import auth
from database import Appointment, Consultation, Medication, Reminder, User, get_db

router = APIRouter()

_TIME = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def _check_date(v: str) -> str:
    try:
        return dt.date.fromisoformat(v).isoformat()
    except (TypeError, ValueError):
        raise ValueError("must be a date like 2026-12-31")


def _check_time(v: str | None) -> str | None:
    if v in (None, ""):
        return None
    if not _TIME.match(v):
        raise ValueError("must be a time like 09:30")
    return v


class _Dated(BaseModel):
    @field_validator("appt_date", "due_date", check_fields=False)
    @classmethod
    def _d(cls, v):
        return None if v is None else _check_date(v)

    @field_validator("appt_time", "due_time", check_fields=False)
    @classmethod
    def _t(cls, v):
        return _check_time(v)


class AppointmentIn(_Dated):
    title: str = Field(min_length=1, max_length=120)
    appt_date: str
    appt_time: str | None = None
    doctor: str | None = Field(default=None, max_length=120)
    location: str | None = Field(default=None, max_length=200)
    notes: str | None = Field(default=None, max_length=1000)
    consultation_id: int | None = None          # accept an extracted follow-up


class AppointmentUpdate(_Dated):
    title: str | None = Field(default=None, min_length=1, max_length=120)
    appt_date: str | None = None
    appt_time: str | None = None
    doctor: str | None = Field(default=None, max_length=120)
    location: str | None = Field(default=None, max_length=200)
    notes: str | None = Field(default=None, max_length=1000)
    status: Literal["scheduled", "done", "cancelled"] | None = None


class AppointmentOut(BaseModel):
    id: int
    title: str
    doctor: str | None
    location: str | None
    appt_date: str
    appt_time: str | None
    notes: str | None
    status: str
    consultation_id: int | None
    model_config = {"from_attributes": True}


class ReminderIn(_Dated):
    title: str = Field(min_length=1, max_length=120)
    due_date: str
    due_time: str | None = None
    repeat: Literal["none", "daily", "weekly", "monthly"] = "none"
    notes: str | None = Field(default=None, max_length=1000)
    medication_id: int | None = None


class ReminderUpdate(_Dated):
    title: str | None = Field(default=None, min_length=1, max_length=120)
    due_date: str | None = None
    due_time: str | None = None
    repeat: Literal["none", "daily", "weekly", "monthly"] | None = None
    notes: str | None = Field(default=None, max_length=1000)
    status: Literal["active", "done"] | None = None


class ReminderOut(BaseModel):
    id: int
    title: str
    notes: str | None
    due_date: str
    due_time: str | None
    repeat: str
    status: str
    medication_id: int | None
    medication_name: str | None = None
    model_config = {"from_attributes": True}


def _get(db: Session, model, item_id: int):
    row = db.get(model, item_id)
    if row is None:
        raise HTTPException(404, "Not found")
    return row


def _today() -> dt.date:
    return dt.date.today()


# ═════════════════════════ appointments ═════════════════════════

@router.get("/api/patients/{patient_id}/appointments", response_model=list[AppointmentOut])
def list_appointments(patient_id: int, when: Literal["upcoming", "past", "all"] = "all", db: Session = Depends(get_db)):
    q = db.query(Appointment).filter(Appointment.patient_id == patient_id)
    today = _today().isoformat()
    if when == "upcoming":
        q = q.filter(Appointment.appt_date >= today, Appointment.status == "scheduled")
        return q.order_by(Appointment.appt_date, Appointment.appt_time).all()
    if when == "past":
        q = q.filter((Appointment.appt_date < today) | (Appointment.status != "scheduled"))
        return q.order_by(Appointment.appt_date.desc(), Appointment.appt_time.desc()).all()
    return q.order_by(Appointment.appt_date, Appointment.appt_time).all()


@router.get("/api/patients/{patient_id}/appointment-suggestions")
def appointment_suggestions(patient_id: int, db: Session = Depends(get_db)):
    """Follow-up dates read from documents that have not been turned into an appointment (or dismissed) yet."""
    taken = {cid for (cid,) in db.query(Appointment.consultation_id).filter(
        Appointment.patient_id == patient_id, Appointment.consultation_id.isnot(None))}
    rows = db.query(Consultation).filter(
        Consultation.patient_id == patient_id, Consultation.follow_up_date >= _today().isoformat(),
    ).order_by(Consultation.follow_up_date).all()
    return [{"consultation_id": c.id, "date": c.follow_up_date, "doctor": c.doctor_name, "hospital": c.hospital,
             "from_visit": c.consultation_date, "document_id": c.document_id}
            for c in rows if c.id not in taken]


@router.post("/api/patients/{patient_id}/appointments", response_model=AppointmentOut, status_code=201)
def create_appointment(patient_id: int, body: AppointmentIn, request: Request, db: Session = Depends(get_db),
                       user: User = Depends(auth.current_user)):
    if body.consultation_id is not None:
        c = db.get(Consultation, body.consultation_id)
        if c is None or c.patient_id != patient_id:        # never link another patient's record
            raise HTTPException(422, "That follow-up does not belong to this patient")
        if db.query(Appointment).filter(Appointment.consultation_id == c.id).first():
            raise HTTPException(409, "That follow-up is already an appointment")
    a = Appointment(patient_id=patient_id, created_by=user.id, **body.model_dump())
    db.add(a)
    db.commit()
    auth.audit(db, request, user.id, patient_id, "appointment_created", f"appt {a.id}")
    return a


@router.put("/api/appointments/{appt_id}", response_model=AppointmentOut)
def update_appointment(appt_id: int, body: AppointmentUpdate, request: Request, db: Session = Depends(get_db),
                       user: User = Depends(auth.current_user)):
    a = _get(db, Appointment, appt_id)
    for k, v in body.model_dump(exclude_unset=True).items():
        if v is None and k in ("title", "appt_date", "status"):
            continue                                         # required fields cannot be blanked
        setattr(a, k, v)
    db.commit()
    auth.audit(db, request, user.id, a.patient_id, "appointment_updated", f"appt {a.id}")
    return a


@router.delete("/api/appointments/{appt_id}", status_code=204)
def delete_appointment(appt_id: int, request: Request, db: Session = Depends(get_db),
                       user: User = Depends(auth.current_user)):
    a = _get(db, Appointment, appt_id)
    pid = a.patient_id
    db.delete(a)
    db.commit()
    auth.audit(db, request, user.id, pid, "appointment_deleted", f"appt {appt_id}")


# ═════════════════════════ reminders ═════════════════════════

def _reminder_out(db: Session, r: Reminder) -> dict:
    med = db.get(Medication, r.medication_id) if r.medication_id else None
    return {**ReminderOut.model_validate(r).model_dump(), "medication_name": med.name if med else None}


def _check_medication(db: Session, patient_id: int, med_id: int | None):
    if med_id is None:
        return
    m = db.get(Medication, med_id)
    if m is None or m.patient_id != patient_id:
        raise HTTPException(422, "That medication does not belong to this patient")


def next_due(due: dt.date, repeat: str, today: dt.date) -> dt.date:
    """First occurrence strictly after both the current due date and today (missed days are not replayed)."""
    nxt = due
    while nxt <= max(due, today):
        if repeat == "daily":
            nxt += dt.timedelta(days=1)
        elif repeat == "weekly":
            nxt += dt.timedelta(days=7)
        else:                                               # monthly: same day, clamped to month length
            y, m = (nxt.year + (nxt.month == 12), nxt.month % 12 + 1)
            nxt = dt.date(y, m, min(due.day, calendar.monthrange(y, m)[1]))
    return nxt


@router.get("/api/patients/{patient_id}/reminders", response_model=list[ReminderOut])
def list_reminders(patient_id: int, status: Literal["active", "done", "all"] = "active", db: Session = Depends(get_db)):
    q = db.query(Reminder).filter(Reminder.patient_id == patient_id)
    if status != "all":
        q = q.filter(Reminder.status == status)
    return [_reminder_out(db, r) for r in q.order_by(Reminder.due_date, Reminder.due_time, Reminder.id)]


@router.post("/api/patients/{patient_id}/reminders", response_model=ReminderOut, status_code=201)
def create_reminder(patient_id: int, body: ReminderIn, request: Request, db: Session = Depends(get_db),
                    user: User = Depends(auth.current_user)):
    _check_medication(db, patient_id, body.medication_id)
    r = Reminder(patient_id=patient_id, created_by=user.id, **body.model_dump())
    db.add(r)
    db.commit()
    auth.audit(db, request, user.id, patient_id, "reminder_created", f"reminder {r.id}")
    return _reminder_out(db, r)


@router.put("/api/reminders/{rem_id}", response_model=ReminderOut)
def update_reminder(rem_id: int, body: ReminderUpdate, request: Request, db: Session = Depends(get_db),
                    user: User = Depends(auth.current_user)):
    r = _get(db, Reminder, rem_id)
    for k, v in body.model_dump(exclude_unset=True).items():
        if v is None and k in ("title", "due_date", "repeat", "status"):
            continue
        setattr(r, k, v)
    db.commit()
    auth.audit(db, request, user.id, r.patient_id, "reminder_updated", f"reminder {r.id}")
    return _reminder_out(db, r)


@router.post("/api/reminders/{rem_id}/complete", response_model=ReminderOut)
def complete_reminder(rem_id: int, request: Request, db: Session = Depends(get_db),
                      user: User = Depends(auth.current_user)):
    """One-off: mark done. Repeating: stay active and move to the next occurrence."""
    r = _get(db, Reminder, rem_id)
    if r.status == "done":
        return _reminder_out(db, r)
    if r.repeat == "none":
        r.status = "done"
    else:
        r.due_date = next_due(dt.date.fromisoformat(r.due_date), r.repeat, _today()).isoformat()
    db.commit()
    auth.audit(db, request, user.id, r.patient_id, "reminder_completed", f"reminder {r.id}")
    return _reminder_out(db, r)


@router.delete("/api/reminders/{rem_id}", status_code=204)
def delete_reminder(rem_id: int, request: Request, db: Session = Depends(get_db),
                    user: User = Depends(auth.current_user)):
    r = _get(db, Reminder, rem_id)
    pid = r.patient_id
    db.delete(r)
    db.commit()
    auth.audit(db, request, user.id, pid, "reminder_deleted", f"reminder {rem_id}")
