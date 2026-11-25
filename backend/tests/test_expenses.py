"""Medical expenses: totals, validation, bills read from documents, access control, export/delete."""
import io
import json
import zipfile

import pytest

import ai_service
from conftest import PASSWORD
from database import Expense, SessionLocal
from test_pipeline import FakeBackend, make_patient, upload
from test_schedule import mk_patient, share


@pytest.fixture(autouse=True)
def _fake_model():
    ai_service._backend = FakeBackend()


def add(c, pid, **kw):
    body = {"expense_date": "2026-01-15", "description": "Visit", "amount": "100", "currency": "INR", **kw}
    return c.post(f"/api/patients/{pid}/expenses", json=body)


def totals(c, pid):
    return {t["currency"]: t["total"] for t in c.get(f"/api/patients/{pid}/expenses").json()["totals"]}


def test_totals_are_exact_and_never_mix_currencies(client):
    pid = mk_patient(client)
    for amount in ("0.10", "0.20", "100"):
        assert add(client, pid, amount=amount).status_code == 201
    add(client, pid, amount="25.50", currency="USD")
    assert totals(client, pid) == {"INR": 100.3, "USD": 25.5}
    summary = client.get(f"/api/patients/{pid}/health-summary").json()["expense_totals"]
    assert [(t["currency"], t["total"], t["count"]) for t in summary] == [("INR", 100.3, 3), ("USD", 25.5, 1)]


def test_delete_updates_total(client):
    pid = mk_patient(client)
    first = add(client, pid, amount="10").json()["id"]
    add(client, pid, amount="5")
    assert client.delete(f"/api/expenses/{first}").status_code == 204
    assert totals(client, pid) == {"INR": 5}


@pytest.mark.parametrize("bad", [
    {"amount": "0"}, {"amount": "-5"}, {"amount": "1.005"}, {"amount": "1000000000"}, {"amount": "abc"},
    {"currency": "XYZ"}, {"category": "yacht"}, {"expense_date": "yesterday"}, {"description": "   "},
])
def test_validation(client, bad):
    assert add(client, mk_patient(client), **bad).status_code == 422


def test_access_control(client, make_client):
    pid = mk_patient(client)
    eid = add(client, pid).json()["id"]
    stranger, _ = make_client()
    assert stranger.get(f"/api/patients/{pid}/expenses").status_code == 404
    assert add(stranger, pid).status_code == 404
    assert stranger.delete(f"/api/expenses/{eid}").status_code == 404
    viewer, email = make_client()
    share(client, pid, email, "viewer")
    assert viewer.get(f"/api/patients/{pid}/expenses").status_code == 200
    assert add(viewer, pid).status_code == 403
    assert viewer.delete(f"/api/expenses/{eid}").status_code == 403
    assert totals(client, pid) == {"INR": 100}


def bill(total, currency):
    return {"category": "insurance_or_bill", "document_date": "2026-02-01", "hospital": "City Clinic",
            "medications": [], "lab_results": [], "bill_total": total, "bill_currency": currency, "confidence": 0.95}


def test_postprocess_keeps_only_usable_totals():
    ok = ai_service.postprocess(bill(1234.5, "inr"))
    assert (ok["bill_total"], ok["bill_currency"], ok["needs_review"]) == (1234.5, "INR", False)
    for total, currency in ((500, None), (500, "ZZZ"), (-1, "INR"), (0, "INR")):
        out = ai_service.postprocess(bill(total, currency))
        assert out["bill_total"] is None and any("bill total" in i for i in out["validation_issues"])


def test_uploaded_bill_is_counted_flagged_and_removed_on_reject(client):
    class BillBackend:
        async def extract(self, paths):
            return bill(750, "INR")

    ai_service._backend = BillBackend()
    pid = mk_patient(client)
    doc_id = upload(client, pid).json()["id"]
    data = client.get(f"/api/patients/{pid}/expenses").json()
    assert data["totals"] == [{"currency": "INR", "total": 750, "unverified": 750, "count": 1}]
    assert data["items"][0]["document_id"] == doc_id

    client.put(f"/api/documents/{doc_id}/validate", json={"validation_status": "verified"})
    assert client.get(f"/api/patients/{pid}/expenses").json()["totals"][0]["unverified"] == 0

    client.post(f"/api/documents/{doc_id}/reprocess")                        # re-reading must not count it twice
    assert totals(client, pid) == {"INR": 750}

    client.put(f"/api/documents/{doc_id}/validate", json={"validation_status": "rejected"})
    assert totals(client, pid) == {}


def test_export_and_patient_delete_include_expenses(client):
    r = client.post("/api/patients", json={"name": "Money Pat"})
    pid = r.json()["id"]
    add(client, pid, description="=HYPERLINK(1)", amount="12.30")
    z = zipfile.ZipFile(io.BytesIO(client.get(f"/api/patients/{pid}/export").content))
    assert json.loads(z.read("patient.json"))["expenses"][0]["amount"] == "12.30"
    assert "'=HYPERLINK(1)" in z.read("expenses.csv").decode()
    assert client.request("DELETE", f"/api/patients/{pid}",
                          json={"confirm_name": "Money Pat", "password": PASSWORD}).status_code == 200
    db = SessionLocal()
    try:
        assert db.query(Expense).filter(Expense.patient_id == pid).count() == 0
    finally:
        db.close()
