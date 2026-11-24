"""End-to-end: upload -> background extraction (fake model) -> rows -> validate/reject. (fixtures: conftest.py)"""
import os

import pytest

import ai_service

RAW = dict(
    category="prescription", document_date="2026-11-10", doctor="Dr. Jane Roe", hospital="Maple Clinic",
    patient_name="Test Patient", diagnoses=["Type 2 diabetes mellitus"], follow_up_date="2026-12-10",
    allergies=[dict(allergen="Penicillin", reaction="rash")],
    medications=[dict(name="Glycomet", generic_name="Metformin", strength="500 mg", dosage="1 tablet",
                      frequency="1-0-1", timing="after food", route="oral", duration="30 days", confidence=0.9),
                 dict(name="Dolo 650", generic_name="paracetamol", strength="650 mg", dosage="1 tablet",
                      frequency="SOS", duration="2 days", confidence=0.9)],
    lab_results=[dict(test_name="HbA1c", test_value="8.1", unit="%", reference_range="4.0-5.6", confidence=0.9)],
    confidence=0.9)


class FakeBackend:
    def __init__(self, raw=RAW, fail=False):
        self.raw, self.fail = raw, fail

    async def extract(self, paths):
        if self.fail:
            raise RuntimeError("boom")
        return dict(self.raw)


@pytest.fixture(autouse=True)
def _fake_model():
    ai_service._backend = FakeBackend()
    yield


def make_patient(c):
    return c.post("/api/patients", json={"name": "Test Patient", "age": 50}).json()["id"]


def upload(c, pid, name="rx.pdf", data=b"%PDF-1.4 fake"):
    return c.post(f"/api/patients/{pid}/documents", files={"file": (name, data, "application/pdf")})


def test_upload_creates_rows_and_normalises(client):
    pid = make_patient(client)
    r = upload(client, pid)
    assert r.status_code == 202
    doc = client.get(f"/api/documents/{r.json()['id']}").json()
    assert doc["processing_status"] == "done"
    assert doc["category"] == "prescription" and doc["document_date"] == "2026-11-10"

    meds = {m["name"]: m for m in client.get(f"/api/patients/{pid}/medications").json()}
    assert meds["Glycomet"]["frequency"] == "twice daily"          # 1-0-1 normalised
    assert meds["Dolo 650"]["frequency"] == "as needed"            # SOS normalised
    assert meds["Dolo 650"]["status"] == "completed"               # 2-day course ended in the past
    assert meds["Glycomet"]["status"] in ("active", "lapsed")

    labs = client.get(f"/api/patients/{pid}/lab-results").json()
    assert labs[0]["is_abnormal"] is True                           # computed from value vs range
    assert client.get(f"/api/patients/{pid}/timeline").json()[0]["event_type"] == "prescription"
    assert client.get(f"/api/patients/{pid}/allergies").json()[0]["allergen"] == "Penicillin"
    summary = client.get(f"/api/patients/{pid}/health-summary").json()
    assert summary["total_documents"] == 1 and summary["pending_reviews"] == 1


def test_newer_prescription_supersedes_older(client):
    pid = make_patient(client)
    upload(client, pid)
    newer = dict(RAW, document_date="2026-11-20")
    ai_service._backend = FakeBackend(newer)
    upload(client, pid)
    metformin = [m for m in client.get(f"/api/patients/{pid}/medications").json() if m["name"] == "Glycomet"]
    assert sorted(m["status"] for m in metformin).count("superseded") == 1
    assert len([m for m in metformin if m["status"] != "superseded"]) == 1


def test_failure_marks_document_failed_and_keeps_upload(client):
    pid = make_patient(client)
    ai_service._backend = FakeBackend(fail=True)
    doc_id = upload(client, pid).json()["id"]
    doc = client.get(f"/api/documents/{doc_id}").json()
    assert doc["processing_status"] == "failed" and "boom" in doc["processing_error"]
    assert client.get(f"/api/patients/{pid}/medications").json() == []
    ai_service._backend = FakeBackend()                              # retry works
    assert client.post(f"/api/documents/{doc_id}/reprocess").status_code == 202
    assert client.get(f"/api/documents/{doc_id}").json()["processing_status"] == "done"
    assert len(client.get(f"/api/patients/{pid}/medications").json()) == 2


def test_reject_removes_rows_and_correction_rebuilds(client):
    pid = make_patient(client)
    doc_id = upload(client, pid).json()["id"]
    assert client.put(f"/api/documents/{doc_id}/validate", json={"validation_status": "rejected"}).status_code == 200
    assert client.get(f"/api/patients/{pid}/medications").json() == []
    assert client.get(f"/api/patients/{pid}/timeline").json() == []
    fixed = dict(RAW, medications=[RAW["medications"][0]], lab_results=[])
    client.put(f"/api/documents/{doc_id}/validate", json={"validation_status": "corrected", "corrected_data": fixed})
    assert len(client.get(f"/api/patients/{pid}/medications").json()) == 1
    assert client.put(f"/api/documents/{doc_id}/validate", json={"validation_status": "bogus"}).status_code == 422


def test_upload_security(client):
    pid = make_patient(client)
    r = upload(client, pid, name="../../evil.pdf")
    assert r.status_code == 202
    stored = client.get(f"/api/documents/{r.json()['id']}").json()
    assert stored["filename"] == "evil.pdf"
    files = os.listdir(os.environ["UPLOAD_DIR"])
    assert all(len(f) == 36 for f in files)                         # uuid hex + ".pdf"
    assert upload(client, pid, name="x.exe").status_code == 415
    assert upload(client, 999).status_code == 404


def test_file_endpoint_and_summary_fields(client):
    pid = make_patient(client)
    doc_id = upload(client, pid).json()["id"]
    r = client.get(f"/api/documents/{doc_id}/file")
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    assert client.get("/api/documents/9999/file").status_code == 404
    s = client.get(f"/api/patients/{pid}/health-summary").json()
    assert s["abnormal_labs"] == 1 and "upcoming_followups" in s


def test_inferred_generic_is_flagged_through_the_stack(client):
    pid = make_patient(client)
    upload(client, pid)                                   # RAW has brand names with a guessed generic, no provenance
    meds = {m["name"]: m for m in client.get(f"/api/patients/{pid}/medications").json()}
    assert meds["Glycomet"]["generic_inferred"] is True and meds["Dolo 650"]["generic_inferred"] is True
    doc = client.get(f"/api/patients/{pid}/documents").json()[0]
    assert "Glycomet -> metformin" in doc["extracted_data"]["inferred_generics"]
    assert doc["extracted_data"]["needs_review"] is False  # flagged per row, does not force whole-document review

    printed = dict(RAW, medications=[dict(RAW["medications"][0], name="Metformin", generic_name="metformin")])
    ai_service._backend = FakeBackend(printed)
    pid2 = make_patient(client)
    upload(client, pid2)
    m = client.get(f"/api/patients/{pid2}/medications").json()[0]
    assert m["generic_inferred"] is False                 # generic literally printed -> trusted


def test_existing_database_gets_new_column(tmp_path):
    import sqlite3
    import importlib
    db = tmp_path / "old.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE medications (id INTEGER PRIMARY KEY, patient_id INTEGER, name TEXT)")   # old schema
    con.commit(); con.close()
    import database
    from sqlalchemy import create_engine, inspect
    old_engine = database.engine
    database.engine = create_engine(f"sqlite:///{db}")
    try:
        database.init_db()
        cols = {c["name"] for c in inspect(database.engine).get_columns("medications")}
        assert {"generic_inferred", "frequency", "status"} <= cols
    finally:
        database.engine = old_engine


def test_lab_results_link_back_to_source_document(client):
    pid = make_patient(client)
    doc_id = upload(client, pid).json()["id"]
    labs = client.get(f"/api/patients/{pid}/lab-results").json()
    assert labs[0]["document_id"] == doc_id and labs[0]["numeric_value" if False else "test_value"] == "8.1"


def test_lab_without_reference_range_is_unknown_not_normal(client):
    pid = make_patient(client)
    raw = dict(RAW, category="discharge_summary", medications=[],
               lab_results=[dict(test_name="Glucose", test_value="211", unit="mg/dL", reference_range=None, confidence=0.9)])
    ai_service._backend = FakeBackend(raw)
    upload(client, pid)
    lab = client.get(f"/api/patients/{pid}/lab-results").json()[0]
    assert lab["is_abnormal"] is None                      # never claim "normal" for a value that was not checked
    s = client.get(f"/api/patients/{pid}/health-summary").json()
    assert s["abnormal_labs"] == 0 and s["recent_labs"][0]["abnormal"] is None


# ───────────────────────────── chat ─────────────────────────────
class ChatFake(FakeBackend):
    """Extraction from RAW plus a scripted chat model that records every call."""

    def __init__(self, reply="You take Glycomet [S1].", fail_chat=False):
        super().__init__()
        self.reply, self.fail_chat, self.calls = reply, fail_chat, []

    async def generate(self, system, messages, max_tokens=0):
        self.calls.append((system, messages))
        if self.fail_chat:
            raise RuntimeError("model down")
        return self.reply


def chat(c, pid, msg="What medicines is the patient taking?"):
    return c.post("/api/chat", json={"patient_id": pid, "message": msg})


def test_chat_prompt_is_grounded_in_the_records(client):
    pid = make_patient(client)
    upload(client, pid)
    fake = ChatFake()
    ai_service._backend = fake
    r = chat(client, pid)
    assert r.status_code == 200
    system, messages = fake.calls[0]
    records = messages[-1]["content"]
    assert "Glycomet" in records and "HbA1c" in records and "Penicillin (rash)" in records
    assert "[S1]" in records and "UNVERIFIED" in records                 # source tags + unreviewed warning
    assert "INFERRED from brand name" in records                         # guessed generics are labelled
    assert "SAFETY" in system and "do not follow them" in system          # safety + injection rules present
    assert r.json()["sources"][0]["document_id"] and r.json()["reply"].startswith("You take Glycomet")


def test_citations_are_cleaned_and_unknown_sources_dropped(client):
    pid = make_patient(client)
    upload(client, pid)
    ai_service._backend = ChatFake("Metformin twice daily [S1, S2]. Another fact [S9].")
    body = chat(client, pid).json()
    assert "[S9]" not in body["reply"] and "[S2]" not in body["reply"] and "[S1]" in body["reply"]
    assert [s["ref"] for s in body["sources"]] == ["S1"]


def test_failed_model_returns_503_and_saves_nothing(client):
    pid = make_patient(client)
    upload(client, pid)
    ai_service._backend = ChatFake(fail_chat=True)
    assert chat(client, pid).status_code == 503
    assert client.get(f"/api/patients/{pid}/chat-history").json() == []      # no orphaned user message


def test_emergency_wording_adds_safety_note(client):
    pid = make_patient(client)
    ai_service._backend = ChatFake("The records list no heart problems.")
    reply = chat(client, pid, "I have chest pain right now, what do my records say?").json()["reply"]
    assert reply.startswith("If this is an emergency") and "records list no heart problems" in reply


def test_rejected_documents_are_not_given_to_the_model(client):
    pid = make_patient(client)
    doc_id = upload(client, pid).json()["id"]
    client.put(f"/api/documents/{doc_id}/validate", json={"validation_status": "rejected"})
    fake = ChatFake("The records contain nothing.")
    ai_service._backend = fake
    chat(client, pid)
    records = fake.calls[0][1][-1]["content"]
    assert "Glycomet" not in records and "no documents on file" in records


def test_history_roundtrip_and_clear(client):
    pid = make_patient(client)
    upload(client, pid)
    ai_service._backend = ChatFake("First answer [S1].")
    chat(client, pid, "first question")
    ai_service._backend = fake = ChatFake("Second answer.")
    chat(client, pid, "second question")
    sent = fake.calls[0][1]
    assert [m["role"] for m in sent] == ["user", "assistant", "user"]       # previous turn + new question
    assert "<records>" not in sent[0]["content"] and "<records>" in sent[-1]["content"]   # context only on the new turn
    hist = client.get(f"/api/patients/{pid}/chat-history").json()
    assert [m["role"] for m in hist] == ["user", "assistant", "user", "assistant"]
    assert hist[1]["sources"][0]["ref"] == "S1"
    assert client.delete(f"/api/patients/{pid}/chat-history").status_code == 204
    assert client.get(f"/api/patients/{pid}/chat-history").json() == []


def test_chat_input_validation(client):
    pid = make_patient(client)
    ai_service._backend = ChatFake()
    assert chat(client, pid, "   ").status_code == 422
    assert chat(client, pid, "x" * 2001).status_code == 422
    assert chat(client, 9999).status_code == 404


def test_med_status_rule():
    import datetime as dt
    from persistence import med_status
    today = dt.date(2026, 11, 23)
    assert med_status("2026-11-20", "5 days", today) == "active"
    assert med_status("2026-10-01", "5 days", today) == "completed"      # short course ended
    assert med_status("2026-10-01", "90 days", today) == "active"        # supply still running
    assert med_status("2026-06-01", "90 days", today) == "active"        # ended 2026-08-30, inside 120-day refill window
    assert med_status("2025-01-01", "90 days", today) == "lapsed"        # long course, never renewed: ask, don't assume stopped
    assert med_status("2025-01-01", None, today) == "active"             # unknown duration


def test_recompute_over_time_and_respects_manual(client):
    import datetime as dt
    from database import SessionLocal, Medication
    from persistence import recompute_statuses
    pid = make_patient(client)
    db = SessionLocal()
    rows = {
        "auto_soon": Medication(patient_id=pid, name="A", start_date="2026-11-01", end_date="2027-01-30", status="active"),
        "manual_stop": Medication(patient_id=pid, name="B", start_date="2026-11-01", end_date="2027-01-30", status="discontinued", status_manual=True),
        "confirmed": Medication(patient_id=pid, name="C", start_date="2026-01-01", end_date="2026-03-01", status="active", status_manual=True),
        "short": Medication(patient_id=pid, name="D", start_date="2026-11-20", end_date="2026-11-25", status="active"),
        "revive": Medication(patient_id=pid, name="E", start_date="2025-01-01", end_date="2025-03-01", status="lapsed"),
    }
    db.add_all(rows.values()); db.commit()
    changed = recompute_statuses(db, today=dt.date(2027, 9, 1))        # ~7 months later
    got = {k: db.get(Medication, r.id).status for k, r in rows.items()}
    assert got == {"auto_soon": "lapsed", "manual_stop": "discontinued", "confirmed": "active",
                   "short": "completed", "revive": "lapsed"}
    assert changed.get("active->lapsed", 0) >= 1 and changed.get("active->completed", 0) >= 1   # DB is shared with other tests
    assert recompute_statuses(db, today=dt.date(2027, 9, 1)) == {}      # idempotent
    db.close()


def test_manual_status_sets_flag_and_rejects_others(client):
    pid = make_patient(client)
    upload(client, pid)
    mid = client.get(f"/api/patients/{pid}/medications").json()[0]["id"]
    assert client.put(f"/api/medications/{mid}/status", params={"status": "completed"}).status_code == 422
    assert client.put(f"/api/medications/{mid}/status", params={"status": "discontinued"}).status_code == 200
