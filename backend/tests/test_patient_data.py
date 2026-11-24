"""Patient export and permanent deletion."""
import io
import json
import os
import tempfile
import zipfile

import pytest

import ai_service
from database import (Allergy, AuditLog, ChatMessage, Consultation, LabResult, MedicalDocument, Medication,
                      PatientAccess, Patient, SessionLocal, TimelineEvent, User)
from test_pipeline import RAW, FakeBackend, make_patient, upload

PW = "correct horse battery staple"
TABLES = (Medication, LabResult, Consultation, Allergy, TimelineEvent, MedicalDocument, ChatMessage, PatientAccess)


@pytest.fixture(autouse=True)
def _fake_model():
    ai_service._backend = FakeBackend()


def share(owner, pid, email, role):
    assert owner.post(f"/api/patients/{pid}/access", json={"email": email, "role": role}).status_code == 200


def counts(pid):
    db = SessionLocal()
    try:
        return {m.__tablename__: db.query(m).filter(m.patient_id == pid).count() for m in TABLES}
    finally:
        db.close()


def delete(c, pid, name="Test Patient", password=PW):
    return c.request("DELETE", f"/api/patients/{pid}", json={"confirm_name": name, "password": password})


def user_id(email):
    db = SessionLocal()
    try:
        return db.query(User).filter(User.email == email).first().id
    finally:
        db.close()


# ── export ────────────────────────────────────────────────────────────────────────────────────
def test_export_contains_data_originals_and_only_my_chat(client, make_client):
    pid = make_patient(client)
    upload(client, pid, data=b"%PDF-1.4 original-bytes")
    other, other_email = make_client()
    share(client, pid, other_email, "viewer")
    db = SessionLocal()
    db.add_all([ChatMessage(patient_id=pid, role="user", user_id=user_id(other_email), content="OTHER PERSON SECRET"),
                ChatMessage(patient_id=pid, role="user", user_id=int(client.get("/api/auth/me").json()["id"]), content="my question")])
    db.commit(); db.close()

    r = client.get(f"/api/patients/{pid}/export")
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    assert "Test Patient" not in r.headers["content-disposition"]                 # no personal data in the filename
    z = zipfile.ZipFile(io.BytesIO(r.content))
    names = z.namelist()
    assert {"README.txt", "patient.json", "medications.csv", "lab_results.csv", "my_chat.json"} <= set(names)
    data = json.loads(z.read("patient.json"))
    assert data["patient"]["name"] == "Test Patient"
    assert {m["name"] for m in data["medications"]} == {"Glycomet", "Dolo 650"}
    assert data["lab_results"][0]["test_name"] == "HbA1c" and data["allergies"][0]["allergen"] == "Penicillin"
    assert all(d["file_path"] is None for d in data["documents"])               # no server paths leak
    originals = [n for n in names if n.startswith("documents/")]
    assert len(originals) == 1 and z.read(originals[0]) == b"%PDF-1.4 original-bytes"
    chat = z.read("my_chat.json").decode()
    assert "my question" in chat and "OTHER PERSON SECRET" not in chat
    assert "Glycomet" in z.read("medications.csv").decode()


def test_export_csv_neutralises_formulas(client):
    ai_service._backend = FakeBackend(dict(RAW, medications=[dict(RAW["medications"][0], name='=HYPERLINK("http://evil","x")')]))
    pid = make_patient(client)
    upload(client, pid)
    z = zipfile.ZipFile(io.BytesIO(client.get(f"/api/patients/{pid}/export").content))
    rows = z.read("medications.csv").decode().splitlines()
    assert not any(line.startswith("=") for line in rows) and "'=HYPERLINK" in z.read("medications.csv").decode()


def test_export_is_owner_only_and_audited(client, make_client):
    pid = make_patient(client)
    ed, ed_email = make_client()
    vw, vw_email = make_client()
    out, _ = make_client()
    share(client, pid, ed_email, "editor")
    share(client, pid, vw_email, "viewer")
    assert ed.get(f"/api/patients/{pid}/export").status_code == 403
    assert vw.get(f"/api/patients/{pid}/export").status_code == 403
    assert out.get(f"/api/patients/{pid}/export").status_code == 404
    assert client.get(f"/api/patients/{pid}/export").status_code == 200
    db = SessionLocal()
    assert db.query(AuditLog).filter(AuditLog.patient_id == pid, AuditLog.action == "patient_exported").count() == 1
    db.close()


def test_export_is_rate_limited(client):
    pid = make_patient(client)
    assert [client.get(f"/api/patients/{pid}/export").status_code for _ in range(6)] == [200] * 5 + [429]


# ── deletion ──────────────────────────────────────────────────────────────────────────────────
def test_delete_removes_everything_including_files(client, make_client):
    pid, keep = make_patient(client), make_patient(client)
    upload(client, pid)
    upload(client, keep)
    viewer, vemail = make_client()
    share(client, pid, vemail, "viewer")
    db = SessionLocal()
    path = db.query(MedicalDocument).filter(MedicalDocument.patient_id == pid).first().file_path
    db.add(ChatMessage(patient_id=pid, role="user", user_id=user_id(vemail), content="hello"))
    db.commit(); db.close()
    assert os.path.isfile(path) and sum(counts(pid).values()) > 0

    r = delete(client, pid)
    assert r.status_code == 200 and r.json()["deleted"] is True and r.json()["files_removed"] == 1
    assert not os.path.exists(path)
    assert sum(counts(pid).values()) == 0
    assert client.get(f"/api/patients/{pid}").status_code == 404
    assert viewer.get(f"/api/patients/{pid}/medications").status_code == 404           # shared users lose access too
    assert pid not in [p["id"] for p in client.get("/api/patients").json()]
    assert sum(counts(keep).values()) > 0 and client.get(f"/api/patients/{keep}").status_code == 200   # others untouched

    db = SessionLocal()
    rows = db.query(AuditLog).filter(AuditLog.patient_id == pid, AuditLog.action == "patient_deleted").all()
    assert len(rows) == 1 and "Test Patient" not in (rows[0].detail or "")           # id and counts only
    assert db.get(Patient, pid) is None
    db.close()


def test_delete_needs_name_and_password(client):
    pid = make_patient(client)
    upload(client, pid)
    assert delete(client, pid, name="test patient").status_code == 422                  # exact name
    assert delete(client, pid, password="wrong password here").status_code == 403
    assert delete(client, pid, name="").status_code == 422
    assert sum(counts(pid).values()) > 0                                                  # nothing happened
    assert delete(client, pid, name=" Test Patient ").status_code == 200                  # surrounding spaces tolerated


def test_delete_is_owner_only(client, make_client):
    pid = make_patient(client)
    ed, ed_email = make_client()
    out, _ = make_client()
    share(client, pid, ed_email, "editor")
    assert delete(ed, pid).status_code == 403
    assert delete(out, pid).status_code == 404
    assert client.get(f"/api/patients/{pid}").status_code == 200


def test_delete_blocked_while_a_document_is_processing(client):
    pid = make_patient(client)
    upload(client, pid)
    db = SessionLocal()
    db.query(MedicalDocument).filter(MedicalDocument.patient_id == pid).update({"processing_status": "processing"})
    db.commit(); db.close()
    assert delete(client, pid).status_code == 409
    assert sum(counts(pid).values()) > 0


def test_delete_never_removes_files_outside_the_upload_folder(client):
    pid = make_patient(client)
    upload(client, pid)
    outside = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
    outside.close()
    db = SessionLocal()
    db.query(MedicalDocument).filter(MedicalDocument.patient_id == pid).update({"file_path": outside.name})
    db.commit(); db.close()
    r = delete(client, pid)
    assert r.status_code == 200 and r.json()["files_removed"] == 0
    assert os.path.exists(outside.name)
    os.remove(outside.name)


def test_wrong_password_is_throttled_and_audited(client):
    pid = make_patient(client)
    codes = [delete(client, pid, password="nope nope nope nope").status_code for _ in range(6)]
    assert codes == [403] * 5 + [429]
    db = SessionLocal()
    assert db.query(AuditLog).filter(AuditLog.patient_id == pid, AuditLog.action == "patient_delete_bad_password").count() == 5
    db.close()
