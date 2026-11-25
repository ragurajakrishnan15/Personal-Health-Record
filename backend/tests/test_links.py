"""A reminder or appointment must never end up pointing at another patient's record.

SQLite reuses the id of a deleted row, so links have to be removed together with the rows they point at.
"""
import pytest

import ai_service
from database import Appointment, Consultation, Medication, Reminder, SessionLocal, init_db
from persistence import persist_extraction, clear_derived
from database import MedicalDocument
from test_pipeline import FakeBackend
from test_schedule import mk_patient


@pytest.fixture(autouse=True)
def _fake_model():
    ai_service._backend = FakeBackend()


def add_doc(pid, medicine, follow_up="2099-02-01"):
    db = SessionLocal()
    try:
        extracted = {"category": "prescription", "document_date": "2026-01-01", "doctor": "Dr. A",
                     "follow_up_date": follow_up, "medications": [{"name": medicine, "generic_name": medicine.lower()}]}
        doc = MedicalDocument(patient_id=pid, filename="x.pdf", file_path="x.pdf", category="prescription",
                              document_date="2026-01-01", processing_status="done", extracted_data=extracted)
        db.add(doc)
        db.commit()
        persist_extraction(db, doc, extracted)
        return doc.id
    finally:
        db.close()


def link_everything(c, pid):
    """A reminder tied to the patient's medicine, and an appointment accepted from the follow-up."""
    med = c.get(f"/api/patients/{pid}/medications").json()[0]["id"]
    assert c.post(f"/api/patients/{pid}/reminders",
                  json={"title": "refill", "due_date": "2099-01-15", "medication_id": med}).status_code == 201
    visit = c.get(f"/api/patients/{pid}/appointment-suggestions").json()[0]["consultation_id"]
    assert c.post(f"/api/patients/{pid}/appointments",
                  json={"title": "FU", "appt_date": "2099-02-01", "consultation_id": visit}).status_code == 201


def links(c, pid):
    r = c.get(f"/api/patients/{pid}/reminders").json()[0]
    a = c.get(f"/api/patients/{pid}/appointments").json()[0]
    return r["medication_id"], r["medication_name"], a["consultation_id"]


def test_rejected_document_cannot_leak_another_accounts_medicine(client, make_client):
    pid = mk_patient(client)
    doc_id = add_doc(pid, "AlphaMed")
    link_everything(client, pid)
    other, _ = make_client()       # signed in BEFORE the rejection: starting a client runs the startup repair,
    assert client.put(f"/api/documents/{doc_id}/validate", json={"validation_status": "rejected"}).status_code == 200
    # ...which a running server would not do here, so it must not be what saves this test
    other_pid = mk_patient(other)
    add_doc(other_pid, "BetaPrivateMed")                   # takes over the freed ids
    db = SessionLocal()
    try:                                                   # checked in the database, not just in the API output
        assert db.query(Reminder.medication_id).filter(Reminder.patient_id == pid).scalar() is None
        assert db.query(Appointment.consultation_id).filter(Appointment.patient_id == pid).scalar() is None
    finally:
        db.close()
    assert links(client, pid) == (None, None, None)
    assert "BetaPrivateMed" not in client.get(f"/api/patients/{pid}/reminders").text
    assert len(other.get(f"/api/patients/{other_pid}/appointment-suggestions").json()) == 1


def test_clearing_one_document_keeps_links_to_other_documents(client):
    pid = mk_patient(client)
    add_doc(pid, "KeepMed")
    link_everything(client, pid)
    before = links(client, pid)
    unrelated = add_doc(pid, "OtherMed", follow_up=None)
    db = SessionLocal()
    try:
        clear_derived(db, unrelated)
        db.commit()
    finally:
        db.close()
    assert links(client, pid) == before and before[1] == "KeepMed"


def _point_links_at(pid, med_id, visit_id):
    db = SessionLocal()
    try:
        db.query(Reminder).filter(Reminder.patient_id == pid).update({"medication_id": med_id})
        db.query(Appointment).filter(Appointment.patient_id == pid).update({"consultation_id": visit_id})
        db.commit()
    finally:
        db.close()


def _someone_elses_rows(c):
    pid = mk_patient(c)
    add_doc(pid, "NotYours")
    db = SessionLocal()
    try:
        return (db.query(Medication.id).filter(Medication.patient_id == pid).scalar(),
                db.query(Consultation.id).filter(Consultation.patient_id == pid).scalar())
    finally:
        db.close()


def test_a_bad_stored_link_is_never_shown(client, make_client):
    pid = mk_patient(client)
    add_doc(pid, "Mine")
    link_everything(client, pid)
    other, _ = make_client()
    _point_links_at(pid, *_someone_elses_rows(other))
    r = client.get(f"/api/patients/{pid}/reminders")
    assert "NotYours" not in r.text and r.json()[0]["medication_id"] is None


@pytest.mark.parametrize("kind", ["other_patient", "missing"])
def test_startup_repairs_bad_links(client, make_client, kind):
    pid = mk_patient(client)
    add_doc(pid, "Mine")
    link_everything(client, pid)
    other, _ = make_client()
    _point_links_at(pid, *(_someone_elses_rows(other) if kind == "other_patient" else (10 ** 8, 10 ** 8)))
    init_db()
    db = SessionLocal()
    try:
        assert db.query(Reminder.medication_id).filter(Reminder.patient_id == pid).scalar() is None
        assert db.query(Appointment.consultation_id).filter(Appointment.patient_id == pid).scalar() is None
    finally:
        db.close()


def test_startup_repair_keeps_good_links(client):
    pid = mk_patient(client)
    add_doc(pid, "Mine")
    link_everything(client, pid)
    before = links(client, pid)
    init_db()
    assert links(client, pid) == before
