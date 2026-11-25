"""Records stay correct through rejection, rebuilding and out-of-order uploads."""
import datetime as dt

import pytest

import ai_service
from database import Allergy, MedicalDocument, Medication, SessionLocal
from persistence import persist_extraction, refresh_patient
from test_pipeline import FakeBackend
from test_schedule import mk_patient

TODAY = dt.date.today()
day = lambda ago: (TODAY - dt.timedelta(days=ago)).isoformat()
LATER = (TODAY + dt.timedelta(days=30)).isoformat()


@pytest.fixture(autouse=True)
def _fake_model():
    ai_service._backend = FakeBackend()


def med(name, strength="500 mg", duration="3 months"):
    return {"name": name, "generic_name": name.lower(), "strength": strength, "duration": duration}


def add_doc(pid, date, **extra):
    db = SessionLocal()
    try:
        extracted = {"category": "prescription", "document_date": date, "doctor": "Dr. A", **extra}
        doc = MedicalDocument(patient_id=pid, filename="x.pdf", file_path="x.pdf", category="prescription",
                              document_date=date, processing_status="done", extracted_data=extracted)
        db.add(doc)
        db.commit()
        persist_extraction(db, doc, extracted)
        return doc.id
    finally:
        db.close()


def rebuild(doc_id, change=None):
    db = SessionLocal()
    try:
        doc = db.get(MedicalDocument, doc_id)
        data = {**doc.extracted_data, **(change or {})}
        persist_extraction(db, doc, data)
    finally:
        db.close()


def meds(c, pid):
    return sorted((m["start_date"], m["name"], m["status"]) for m in c.get(f"/api/patients/{pid}/medications").json())


def med_id(c, pid, name):
    return next(m["id"] for m in c.get(f"/api/patients/{pid}/medications").json() if m["name"] == name)


def allergies(c, pid):
    return sorted(a["allergen"] for a in c.get(f"/api/patients/{pid}/allergies").json())


def decide(c, doc_id, status, **body):
    return c.put(f"/api/documents/{doc_id}/validate", json={"validation_status": status, **body})


# ── rejection ───────────────────────────────────────────────

def test_rejecting_newer_prescription_brings_the_older_one_back(client):
    pid = mk_patient(client)
    add_doc(pid, day(40), medications=[med("Metformin")])
    newer = add_doc(pid, day(1), medications=[med("Metformin")])
    assert [s for *_, s in meds(client, pid)] == ["superseded", "active"]
    assert decide(client, newer, "rejected").status_code == 200
    assert meds(client, pid) == [(day(40), "Metformin", "active")]


def test_rejecting_the_middle_of_three_keeps_the_oldest_replaced(client):
    pid = mk_patient(client)
    add_doc(pid, day(60), medications=[med("Metformin")])
    middle = add_doc(pid, day(30), medications=[med("Metformin")])
    add_doc(pid, day(1), medications=[med("Metformin")])
    decide(client, middle, "rejected")
    assert [s for *_, s in meds(client, pid)] == ["superseded", "active"]


def test_rejected_allergy_goes_but_one_seen_elsewhere_stays(client):
    pid = mk_patient(client)
    add_doc(pid, day(40), allergies=[{"allergen": "Penicillin"}])
    wrong = add_doc(pid, day(1), allergies=[{"allergen": "penicillin", "reaction": "rash"}, {"allergen": "WrongDrug"}])
    assert allergies(client, pid) == ["Penicillin", "WrongDrug"]
    decide(client, wrong, "rejected")
    assert allergies(client, pid) == ["Penicillin"]


def test_accepting_a_rejected_document_restores_its_records(client):
    pid = mk_patient(client)
    doc = add_doc(pid, day(1), medications=[med("Metformin")], allergies=[{"allergen": "Latex"}])
    decide(client, doc, "rejected")
    assert meds(client, pid) == [] and allergies(client, pid) == []
    decide(client, doc, "verified")
    assert meds(client, pid) == [(day(1), "Metformin", "active")] and allergies(client, pid) == ["Latex"]


# ── upload order ────────────────────────────────────────────

def test_upload_order_does_not_matter(client):
    pid = mk_patient(client)
    add_doc(pid, day(1), medications=[med("Amlodipine")])
    add_doc(pid, day(40), medications=[med("Amlodipine")])          # the older one arrives second
    assert meds(client, pid) == [(day(40), "Amlodipine", "superseded"), (day(1), "Amlodipine", "active")]


def test_finished_short_course_stays_completed(client):
    pid = mk_patient(client)
    add_doc(pid, day(90), medications=[med("Amoxicillin", duration="5 days")])
    add_doc(pid, day(1), medications=[med("Amoxicillin", duration="5 days")])
    assert meds(client, pid)[0][2] == "completed"


def test_two_rows_of_one_drug_on_the_same_prescription_both_stay(client):
    pid = mk_patient(client)
    add_doc(pid, day(1), medications=[med("Metformin", "500 mg"), med("Metformin", "850 mg")])
    assert [s for *_, s in meds(client, pid)] == ["active", "active"]


# ── choices people made survive a rebuild ───────────────────

def test_stop_survives_a_rebuild(client):
    pid = mk_patient(client)
    doc = add_doc(pid, day(1), medications=[med("Atorvastatin")])
    client.put(f"/api/medications/{med_id(client, pid, 'Atorvastatin')}/status", params={"status": "discontinued"})
    rebuild(doc)
    assert meds(client, pid)[0][2] == "discontinued"


def test_still_taking_survives_rebuild_and_a_rejected_replacement(client):
    pid = mk_patient(client)
    old = add_doc(pid, day(400), medications=[med("Thyroxine")])
    assert meds(client, pid)[0][2] == "lapsed"
    client.put(f"/api/medications/{med_id(client, pid, 'Thyroxine')}/status", params={"status": "active"})
    rebuild(old)
    assert meds(client, pid)[0][2] == "active"
    newer = add_doc(pid, day(1), medications=[med("Thyroxine")])
    assert meds(client, pid)[0][2] == "superseded"
    decide(client, newer, "rejected")
    assert meds(client, pid) == [(day(400), "Thyroxine", "active")]


def test_reminder_and_accepted_follow_up_survive_a_rebuild(client):
    pid = mk_patient(client)
    doc = add_doc(pid, day(1), medications=[med("Aspirin"), med("Metformin")], follow_up_date=LATER)
    add_doc(pid, day(1), diagnoses=["x"])                          # moves the id counters on
    client.post(f"/api/patients/{pid}/reminders",
                json={"title": "refill", "due_date": LATER, "medication_id": med_id(client, pid, "Metformin")})
    visit = client.get(f"/api/patients/{pid}/appointment-suggestions").json()[0]["consultation_id"]
    client.post(f"/api/patients/{pid}/appointments", json={"title": "FU", "appt_date": LATER, "consultation_id": visit})
    rebuild(doc, {"medications": [med("Metformin"), med("Aspirin")]})   # same medicines, different order
    assert client.get(f"/api/patients/{pid}/reminders").json()[0]["medication_name"] == "Metformin"
    assert client.get(f"/api/patients/{pid}/appointment-suggestions").json() == []


def test_a_choice_is_never_moved_to_a_different_drug(client):
    pid = mk_patient(client)
    doc = add_doc(pid, day(1), medications=[med("Aspirin")])
    client.post(f"/api/patients/{pid}/reminders",
                json={"title": "r", "due_date": LATER, "medication_id": med_id(client, pid, "Aspirin")})
    client.put(f"/api/medications/{med_id(client, pid, 'Aspirin')}/status", params={"status": "discontinued"})
    rebuild(doc, {"medications": [med("Warfarin")]})
    assert meds(client, pid) == [(day(1), "Warfarin", "active")]
    assert client.get(f"/api/patients/{pid}/reminders").json()[0]["medication_id"] is None


def test_failed_reread_keeps_what_was_read_before(client):
    class Broken:
        async def extract(self, paths):
            raise RuntimeError("model unavailable")

    pid = mk_patient(client)
    doc = add_doc(pid, day(1), medications=[med("Metformin")], allergies=[{"allergen": "Latex"}])
    ai_service._backend = Broken()
    client.post(f"/api/documents/{doc}/reprocess")
    after = client.get(f"/api/documents/{doc}").json()
    assert after["processing_status"] == "failed" and after["extracted_data"]["medications"]
    db = SessionLocal()
    try:
        refresh_patient(db, pid)
        db.commit()
    finally:
        db.close()
    assert allergies(client, pid) == ["Latex"] and meds(client, pid)[0][1] == "Metformin"


# ── bad corrections and old data ────────────────────────────

@pytest.mark.parametrize("bad", [
    {"medications": [{}]}, {"medications": None}, {"medications": "Metformin"}, {"lab_results": [{"test_value": "1"}]},
    {"allergies": [{"reaction": "x"}]}, {"document_date": "yesterday"}, {"category": None},
    {"bill_total": -3, "bill_currency": "INR"}, {"diagnoses": [1]},
])
def test_bad_correction_is_refused_and_changes_nothing(client, bad):
    pid = mk_patient(client)
    doc = add_doc(pid, day(1), medications=[med("Metformin")])
    before = client.get(f"/api/documents/{doc}").json()
    assert decide(client, doc, "corrected", corrected_data=bad).status_code == 422
    assert client.get(f"/api/documents/{doc}").json() == before and len(meds(client, pid)) == 1


def test_good_correction_is_saved(client):
    pid = mk_patient(client)
    doc = add_doc(pid, day(1), medications=[med("Metformin")])
    good = {"category": "prescription", "document_date": day(2), "medications": [med("Glipizide")], "bill_total": "40",
            "bill_currency": "INR"}
    assert decide(client, doc, "corrected", corrected_data=good).status_code == 200
    assert meds(client, pid) == [(day(2), "Glipizide", "active")]
    assert client.get(f"/api/patients/{pid}/expenses").json()["totals"][0]["total"] == 40


def test_refresh_repairs_records_saved_by_the_old_code(client):
    pid = mk_patient(client)
    add_doc(pid, day(40), medications=[med("Metformin")])
    db = SessionLocal()
    try:                                                   # the state the old code could leave behind
        db.query(Medication).filter(Medication.patient_id == pid).update({"status": "superseded"})
        db.add(Allergy(patient_id=pid, allergen="Orphan"))
        db.commit()
        refresh_patient(db, pid)
        db.commit()
    finally:
        db.close()
    assert meds(client, pid)[0][2] == "active" and allergies(client, pid) == []
