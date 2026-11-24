"""Appointments and reminders: validation, follow-up suggestions, repeat logic, access control, export/delete."""
import datetime as dt
import io
import json
import zipfile

import pytest

import ai_service
import schedule_routes
from conftest import PASSWORD
from database import Appointment, Consultation, Reminder, SessionLocal
from test_pipeline import FakeBackend, make_patient, upload

D = dt.date


@pytest.fixture(autouse=True)
def _fake_model():
    ai_service._backend = FakeBackend()


def mk_patient(c, name="Pat"):
    r = c.post("/api/patients", json={"name": name, "age": 40})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def seeded(c):
    """Patient with one processed prescription (so it has medications)."""
    pid = mk_patient(c)
    doc_id = upload(c, pid).json()["id"]
    med_id = c.get(f"/api/patients/{pid}/medications").json()[0]["id"]
    return pid, doc_id, med_id


def share(owner, pid, email, role):
    assert owner.post(f"/api/patients/{pid}/access", json={"email": email, "role": role}).status_code == 200


def db_scalar(fn):
    db = SessionLocal()
    try:
        return fn(db)
    finally:
        db.close()


def appt(c, pid, **kw):
    body = {"title": "Check-up", "appt_date": "2099-01-15", **kw}
    return c.post(f"/api/patients/{pid}/appointments", json=body)


def remind(c, pid, **kw):
    body = {"title": "Take pill", "due_date": "2099-01-15", **kw}
    return c.post(f"/api/patients/{pid}/reminders", json=body)


# ═════════════════════════ appointments ═════════════════════════

def test_create_list_update_delete_appointment(client):
    pid = mk_patient(client)
    r = appt(client, pid, doctor="Dr Roe", appt_time="09:30", location="Maple Clinic")
    assert r.status_code == 201, r.text
    a = r.json()
    assert (a["status"], a["appt_time"], a["doctor"]) == ("scheduled", "09:30", "Dr Roe")

    assert [x["id"] for x in client.get(f"/api/patients/{pid}/appointments?when=upcoming").json()] == [a["id"]]
    assert client.get(f"/api/patients/{pid}/appointments?when=past").json() == []

    r = client.put(f"/api/appointments/{a['id']}", json={"status": "done"})
    assert r.status_code == 200 and r.json()["status"] == "done"
    assert client.get(f"/api/patients/{pid}/appointments?when=upcoming").json() == []
    assert len(client.get(f"/api/patients/{pid}/appointments?when=past").json()) == 1   # done moves to history

    assert client.delete(f"/api/appointments/{a['id']}").status_code == 204
    assert client.get(f"/api/patients/{pid}/appointments").json() == []


@pytest.mark.parametrize("bad", [
    {"appt_date": "2099-13-45"}, {"appt_date": "tomorrow"}, {"appt_time": "25:00"}, {"appt_time": "9:30"},
    {"title": ""}, {"title": "x" * 121}, {"notes": "x" * 1001},
])
def test_appointment_validation(client, bad):
    pid = mk_patient(client)
    assert appt(client, pid, **bad).status_code == 422


def test_appointment_update_cannot_blank_required_fields_or_set_bad_status(client):
    pid = mk_patient(client)
    a = appt(client, pid).json()
    r = client.put(f"/api/appointments/{a['id']}", json={"title": None, "appt_date": None, "status": None})
    assert r.status_code == 200 and r.json()["title"] == "Check-up" and r.json()["appt_date"] == "2099-01-15"
    assert client.put(f"/api/appointments/{a['id']}", json={"status": "exploded"}).status_code == 422


def test_unknown_fields_cannot_reassign_an_appointment_to_another_patient(client):
    p1, p2 = mk_patient(client, "One"), mk_patient(client, "Two")
    a = appt(client, p1).json()
    client.put(f"/api/appointments/{a['id']}", json={"patient_id": p2})
    assert db_scalar(lambda db: db.get(Appointment, a["id"]).patient_id) == p1


def _add_followup(pid, when, doctor="Dr Roe"):
    def go(db):
        c = Consultation(patient_id=pid, doctor_name=doctor, hospital="Maple Clinic",
                         consultation_date="2099-01-01", follow_up_date=when)
        db.add(c)
        db.commit()
        return c.id
    return db_scalar(go)


def test_followup_suggestions_can_be_accepted_once(client):
    pid = mk_patient(client)
    future = _add_followup(pid, "2099-03-01")
    _add_followup(pid, "2000-01-01")                         # in the past: never suggested
    sug = client.get(f"/api/patients/{pid}/appointment-suggestions").json()
    assert [s["consultation_id"] for s in sug] == [future]
    assert sug[0]["doctor"] == "Dr Roe"

    r = appt(client, pid, title="Follow-up", appt_date="2099-03-01", consultation_id=future)
    assert r.status_code == 201
    assert client.get(f"/api/patients/{pid}/appointment-suggestions").json() == []   # gone once accepted
    assert appt(client, pid, consultation_id=future).status_code == 409                # and cannot be accepted twice


def test_cannot_link_another_patients_followup(client):
    mine, theirs = mk_patient(client, "Mine"), mk_patient(client, "Theirs")
    cid = _add_followup(theirs, "2099-03-01")
    assert appt(client, mine, consultation_id=cid).status_code == 422
    assert appt(client, mine, consultation_id=99999).status_code == 422


# ═════════════════════════ reminders ═════════════════════════

def test_reminder_lifecycle_and_one_off_completion(client):
    pid = mk_patient(client)
    r = remind(client, pid, due_time="08:00", notes="with water")
    assert r.status_code == 201, r.text
    rem = r.json()
    assert (rem["repeat"], rem["status"]) == ("none", "active")
    done = client.post(f"/api/reminders/{rem['id']}/complete").json()
    assert done["status"] == "done"
    assert client.get(f"/api/patients/{pid}/reminders").json() == []                  # active only by default
    assert len(client.get(f"/api/patients/{pid}/reminders?status=done").json()) == 1
    assert client.delete(f"/api/reminders/{rem['id']}").status_code == 204


def test_repeating_reminder_moves_to_next_occurrence_and_stays_active(client, monkeypatch):
    monkeypatch.setattr(schedule_routes, "_today", lambda: D(2099, 1, 15))
    pid = mk_patient(client)
    rem = remind(client, pid, repeat="daily").json()
    after = client.post(f"/api/reminders/{rem['id']}/complete").json()
    assert (after["status"], after["due_date"]) == ("active", "2099-01-16")


@pytest.mark.parametrize("repeat,due,today,expected", [
    ("daily", D(2099, 1, 15), D(2099, 1, 15), D(2099, 1, 16)),
    ("daily", D(2099, 1, 10), D(2099, 1, 15), D(2099, 1, 16)),       # missed days are skipped, not replayed
    ("daily", D(2099, 1, 20), D(2099, 1, 15), D(2099, 1, 21)),       # completed early: still moves forward
    ("weekly", D(2099, 1, 15), D(2099, 1, 15), D(2099, 1, 22)),
    ("monthly", D(2099, 1, 31), D(2099, 1, 31), D(2099, 2, 28)),     # clamps to a short month
    ("monthly", D(2099, 12, 5), D(2099, 12, 5), D(2100, 1, 5)),      # year rollover
])
def test_next_due(repeat, due, today, expected):
    assert schedule_routes.next_due(due, repeat, today) == expected


def test_monthly_keeps_original_day_after_a_short_month():
    d = schedule_routes.next_due(D(2099, 1, 31), "monthly", D(2099, 1, 31))      # -> Feb 28
    assert schedule_routes.next_due(D(2099, 1, 31), "monthly", D(2099, 2, 28)) == D(2099, 3, 31)
    assert d == D(2099, 2, 28)


@pytest.mark.parametrize("bad", [{"repeat": "hourly"}, {"due_date": "2099-02-30"}, {"due_time": "7pm"}, {"title": " " * 0}])
def test_reminder_validation(client, bad):
    pid = mk_patient(client)
    assert remind(client, pid, **bad).status_code == 422


def test_medication_reminder_shows_medication_name_and_rejects_foreign_medication(client):
    pid, _doc, med_id = seeded(client)
    other, _d2, other_med = seeded(client)
    r = remind(client, pid, medication_id=med_id, repeat="daily")
    assert r.status_code == 201 and r.json()["medication_name"]
    assert remind(client, pid, medication_id=other_med).status_code == 422
    assert remind(client, pid, medication_id=987654).status_code == 422


# ═════════════════════════ access control ═════════════════════════

def test_viewer_reads_but_cannot_write(client, make_client):
    pid = mk_patient(client)
    a, r = appt(client, pid).json(), remind(client, pid).json()
    doctor, email = make_client("Dr Viewer")
    share(client, pid, email, "viewer")

    for url in (f"/api/patients/{pid}/appointments", f"/api/patients/{pid}/appointment-suggestions",
                f"/api/patients/{pid}/reminders"):
        assert doctor.get(url).status_code == 200, url
    writes = [("POST", f"/api/patients/{pid}/appointments", {"json": {"title": "x", "appt_date": "2099-01-01"}}),
              ("PUT", f"/api/appointments/{a['id']}", {"json": {"status": "cancelled"}}),
              ("DELETE", f"/api/appointments/{a['id']}", {}),
              ("POST", f"/api/patients/{pid}/reminders", {"json": {"title": "x", "due_date": "2099-01-01"}}),
              ("PUT", f"/api/reminders/{r['id']}", {"json": {"status": "done"}}),
              ("POST", f"/api/reminders/{r['id']}/complete", {}),
              ("DELETE", f"/api/reminders/{r['id']}", {})]
    for method, url, kw in writes:
        assert doctor.request(method, url, **kw).status_code == 403, f"{method} {url}"
    assert len(client.get(f"/api/patients/{pid}/appointments").json()) == 1


def test_editor_can_write(client, make_client):
    pid = mk_patient(client)
    helper, email = make_client("Family Editor")
    share(client, pid, email, "editor")
    assert appt(helper, pid).status_code == 201
    assert remind(helper, pid).status_code == 201


def test_strangers_get_404_everywhere_and_cannot_touch_items_by_id(client, make_client):
    pid = mk_patient(client)
    a, r = appt(client, pid).json(), remind(client, pid).json()
    stranger, _ = make_client("Stranger")
    checks = [("GET", f"/api/patients/{pid}/appointments", {}), ("GET", f"/api/patients/{pid}/reminders", {}),
              ("GET", f"/api/patients/{pid}/appointment-suggestions", {}),
              ("POST", f"/api/patients/{pid}/appointments", {"json": {"title": "x", "appt_date": "2099-01-01"}}),
              ("PUT", f"/api/appointments/{a['id']}", {"json": {"status": "cancelled"}}),
              ("DELETE", f"/api/appointments/{a['id']}", {}),
              ("PUT", f"/api/reminders/{r['id']}", {"json": {"status": "done"}}),
              ("POST", f"/api/reminders/{r['id']}/complete", {}),
              ("DELETE", f"/api/reminders/{r['id']}", {})]
    for method, url, kw in checks:
        assert stranger.request(method, url, **kw).status_code == 404, f"{method} {url}"
    assert db_scalar(lambda db: db.get(Appointment, a["id"]) is not None and db.get(Reminder, r["id"]) is not None)


def test_unknown_item_ids_are_404(client):
    assert client.put("/api/appointments/999999", json={"status": "done"}).status_code == 404
    assert client.post("/api/reminders/999999/complete").status_code == 404


def test_audit_log_records_ids_not_content(client):
    from database import AuditLog
    pid = mk_patient(client)
    appt(client, pid, title="Secret oncology visit", notes="private note")
    rows = db_scalar(lambda db: [(x.action, x.detail) for x in db.query(AuditLog).filter(AuditLog.patient_id == pid)])
    assert any(a == "appointment_created" for a, _ in rows)
    assert not any("oncology" in (d or "") or "private" in (d or "") for _, d in rows)


# ═════════════════════════ export / delete ═════════════════════════

def test_export_includes_and_delete_removes_appointments_and_reminders(client):
    pid, _doc, med_id = seeded(client)
    cid = _add_followup(pid, "2099-03-01")
    appt(client, pid, title="Visit", consultation_id=cid)
    remind(client, pid, medication_id=med_id)

    z = zipfile.ZipFile(io.BytesIO(client.get(f"/api/patients/{pid}/export").content))
    data = json.loads(z.read("patient.json"))
    assert [a["title"] for a in data["appointments"]] == ["Visit"]
    assert len(data["reminders"]) == 1

    name = client.get(f"/api/patients/{pid}").json()["name"]
    r = client.request("DELETE", f"/api/patients/{pid}", json={"confirm_name": name, "password": PASSWORD})
    assert r.status_code == 200, r.text
    assert db_scalar(lambda db: db.query(Appointment).filter(Appointment.patient_id == pid).count()) == 0
    assert db_scalar(lambda db: db.query(Reminder).filter(Reminder.patient_id == pid).count()) == 0
