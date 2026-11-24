"""Authentication, authorization and hardening. (fixtures: conftest.py)"""
import datetime as dt
import re

import pytest
from fastapi.routing import APIRoute

import ai_service
import auth
from conftest import PASSWORD, register
from database import AuditLog, SessionLocal, User, UserSession
from main import app

RAW = dict(
    category="prescription", document_date="2026-11-10", doctor="Dr. Jane Roe", hospital="Maple Clinic",
    diagnoses=["Type 2 diabetes mellitus"], allergies=[dict(allergen="Penicillin", reaction="rash")],
    medications=[dict(name="Glycomet", generic_name="Metformin", strength="500 mg", frequency="twice daily",
                      duration="30 days", confidence=0.9)],
    lab_results=[dict(test_name="HbA1c", test_value="8.1", unit="%", reference_range="4.0-5.6", confidence=0.9)],
    confidence=0.9)


class Model:
    async def extract(self, paths):
        return dict(RAW)

    async def generate(self, system, messages, max_tokens=0):
        return "Metformin twice daily [S1]."


@pytest.fixture(autouse=True)
def _model():
    ai_service._backend = Model()
    yield


def mk_patient(c, name="Pat"):
    r = c.post("/api/patients", json={"name": name, "age": 40})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def upload(c, pid):
    return c.post(f"/api/patients/{pid}/documents", files={"file": ("rx.pdf", b"%PDF-1.4 x", "application/pdf")})


def seeded(c):
    """Patient with one processed document, medication, lab and allergy owned by client `c`."""
    pid = mk_patient(c)
    doc_id = upload(c, pid).json()["id"]
    med_id = c.get(f"/api/patients/{pid}/medications").json()[0]["id"]
    return pid, doc_id, med_id


def db_scalar(fn):
    db = SessionLocal()
    try:
        return fn(db)
    finally:
        db.close()


# ═══════════════════════════ accounts & sessions ═══════════════════════════

def test_register_login_logout_cycle(anon):
    email = register(anon)
    assert anon.get("/api/auth/me").json()["email"] == email                 # registering signs you in
    assert anon.post("/api/auth/logout").status_code == 204
    assert anon.get("/api/auth/me").status_code == 401
    assert anon.post("/api/auth/login", json={"email": email.upper(), "password": PASSWORD}).status_code == 200
    assert anon.get("/api/auth/me").status_code == 200                       # email is case-insensitive


def test_failed_logins_do_not_reveal_whether_the_account_exists(anon):
    email = register(anon)
    anon.post("/api/auth/logout")
    wrong_pw = anon.post("/api/auth/login", json={"email": email, "password": "not the password at all"})
    unknown = anon.post("/api/auth/login", json={"email": "nobody-here@example.com", "password": "not the password at all"})
    assert wrong_pw.status_code == unknown.status_code == 401
    assert wrong_pw.json() == unknown.json()


@pytest.mark.parametrize("password,fragment", [("short", "at least 10"), ("password123", "too easy"),
                                               ("aaaaaaaaaaaa", "too easy"), ("x" * 129, "at most 128")])
def test_password_policy(anon, password, fragment):
    r = anon.post("/api/auth/register", json={"email": "p@example.com", "name": "P", "password": password})
    assert r.status_code == 422 and fragment in r.json()["detail"]


def test_password_may_not_contain_email_name(anon):
    r = anon.post("/api/auth/register", json={"email": "zebrafish@example.com", "name": "Z", "password": "my-zebrafish-1234"})
    assert r.status_code == 422


def test_duplicate_email_and_bad_email_rejected(anon):
    email = register(anon)
    assert anon.post("/api/auth/register", json={"email": email, "name": "X", "password": PASSWORD}).status_code == 409
    assert anon.post("/api/auth/register", json={"email": "not-an-email", "name": "X", "password": PASSWORD}).status_code == 422


def test_secrets_are_not_stored_in_plain_text(anon):
    email = register(anon)
    token = anon.cookies.get(auth.COOKIE_NAME)
    user = db_scalar(lambda db: db.query(User).filter(User.email == email).one())
    assert user.password_hash.startswith("scrypt$") and PASSWORD not in user.password_hash
    hashes = [s.token_hash for s in db_scalar(lambda db: db.query(UserSession).filter(UserSession.user_id == user.id).all())]
    assert token and token not in hashes and len(hashes) == 1                # only a hash of the cookie is kept


def test_session_cookie_flags(anon):
    r = anon.post("/api/auth/register", json={"email": "flags@example.com", "name": "F", "password": PASSWORD})
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie and "path=/" in cookie


def test_account_locks_after_repeated_failures(anon):
    email = register(anon)
    anon.post("/api/auth/logout")
    for _ in range(auth.MAX_FAILED):
        assert anon.post("/api/auth/login", json={"email": email, "password": "wrong password here"}).status_code == 401
    r = anon.post("/api/auth/login", json={"email": email, "password": PASSWORD})      # even the right password
    assert r.status_code == 429


def test_login_attempts_are_rate_limited(anon):
    codes = [anon.post("/api/auth/login", json={"email": "x@example.com", "password": "wrong password here"}).status_code
             for _ in range(12)]
    assert codes[0] == 401 and 429 in codes


def test_logout_revokes_a_stolen_cookie(anon):
    register(anon)
    stolen = anon.cookies.get(auth.COOKIE_NAME)
    anon.post("/api/auth/logout")
    anon.cookies.set(auth.COOKIE_NAME, stolen)
    assert anon.get("/api/auth/me").status_code == 401


def test_expired_session_is_rejected(anon):
    email = register(anon)

    def expire(db):
        uid = db.query(User).filter(User.email == email).one().id
        db.query(UserSession).filter(UserSession.user_id == uid).update({"expires_at": dt.datetime.utcnow() - dt.timedelta(minutes=1)})
        db.commit()
    db_scalar(expire)
    assert anon.get("/api/auth/me").status_code == 401


def test_deactivated_user_cannot_use_existing_session(anon):
    email = register(anon)

    def deactivate(db):
        db.query(User).filter(User.email == email).update({"is_active": False})
        db.commit()
    db_scalar(deactivate)
    assert anon.get("/api/auth/me").status_code == 401


def test_changing_password_signs_out_other_devices(make_client, anon):
    c1, email = make_client("Phone")
    c2 = anon
    c2.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    assert c2.get("/api/auth/me").status_code == 200
    new = "an entirely different passphrase"
    assert c1.post("/api/auth/password", json={"current_password": "wrong", "new_password": new}).status_code == 403
    assert c1.post("/api/auth/password", json={"current_password": PASSWORD, "new_password": new}).status_code == 204
    assert c1.get("/api/auth/me").status_code == 200            # this device stays signed in
    assert c2.get("/api/auth/me").status_code == 401            # the other one is signed out
    c2.cookies.clear()
    assert c2.post("/api/auth/login", json={"email": email, "password": PASSWORD}).status_code == 401
    assert c2.post("/api/auth/login", json={"email": email, "password": new}).status_code == 200


def test_registration_can_be_disabled(anon, monkeypatch):
    monkeypatch.setattr(auth, "ALLOW_REGISTRATION", False)
    r = anon.post("/api/auth/register", json={"email": "late@example.com", "name": "L", "password": PASSWORD})
    assert r.status_code == 403


# ═══════════════════════════ default deny ═══════════════════════════

def _routes():
    for r in app.routes:
        if isinstance(r, APIRoute):
            for m in sorted(r.methods - {"HEAD", "OPTIONS"}):
                yield m, r.path


def test_every_route_requires_a_session_except_the_public_ones(anon):
    """Guards against forgetting to protect a new endpoint: it will fail here until it is."""
    checked = 0
    for method, path in _routes():
        if (method, path) in auth.PUBLIC:
            continue
        url = re.sub(r"\{[^}]+\}", "1", path)
        if method == "POST" and path.endswith("/documents"):
            r = anon.request(method, url, files={"file": ("x.pdf", b"x", "application/pdf")})
        else:
            r = anon.request(method, url, json={})
        assert r.status_code == 401, f"{method} {path} answered {r.status_code} without a session"
        checked += 1
    assert checked >= 15       # sanity: the sweep really visited the routes
    assert {p for _, p in auth.PUBLIC} == {"/api/auth/login", "/api/auth/register", "/api/health", "/api/auth/verify-email",
                                          "/api/auth/forgot-password", "/api/auth/reset-password"}


def test_public_health_endpoint_leaks_nothing(anon):
    assert anon.get("/api/health").json() == {"status": "ok"}


def test_uploads_directory_is_not_served_statically(anon):
    assert anon.get("/uploads/anything.pdf").status_code == 404


# ═══════════════════════════ isolation between users ═══════════════════════════

def test_other_users_cannot_see_or_touch_a_patient(client, make_client):
    pid, doc_id, med_id = seeded(client)
    mallory, _ = make_client("Mallory")
    missing = mallory.get("/api/patients/999999").json()                 # what "does not exist" looks like

    reads = [f"/api/patients/{pid}", f"/api/patients/{pid}/documents", f"/api/patients/{pid}/medications",
             f"/api/patients/{pid}/lab-results", f"/api/patients/{pid}/allergies", f"/api/patients/{pid}/timeline",
             f"/api/patients/{pid}/health-summary", f"/api/patients/{pid}/chat-history",
             f"/api/documents/{doc_id}", f"/api/documents/{doc_id}/file"]
    for url in reads:
        r = mallory.get(url)
        assert r.status_code == 404, f"GET {url} -> {r.status_code}"
        assert r.json() == missing or r.json() == {"detail": "Not found"}      # no hint that the record exists

    writes = [("POST", f"/api/patients/{pid}/documents"), ("POST", f"/api/documents/{doc_id}/reprocess"),
              ("PUT", f"/api/documents/{doc_id}/validate"), ("PUT", f"/api/medications/{med_id}/status?status=active"),
              ("DELETE", f"/api/patients/{pid}/chat-history"), ("GET", f"/api/patients/{pid}/access")]
    for method, url in writes:
        kwargs = {"files": {"file": ("x.pdf", b"x", "application/pdf")}} if url.endswith("/documents") else {"json": {"validation_status": "verified"}}
        assert mallory.request(method, url, **kwargs).status_code == 404, f"{method} {url}"
    assert mallory.post("/api/chat", json={"patient_id": pid, "message": "what meds?"}).status_code == 404
    assert mallory.get("/api/patients").json() == []                     # not even listed

    # the owner's data is untouched by the attempts
    assert client.get(f"/api/documents/{doc_id}").json()["validation_status"] == "pending_review"
    assert client.get(f"/api/patients/{pid}/medications").json()[0]["status"] != "discontinued"


def test_denied_attempts_are_audited(client, make_client):
    pid, _, _ = seeded(client)
    mallory, email = make_client("Mallory")
    mallory.get(f"/api/patients/{pid}/medications")
    rows = db_scalar(lambda db: [(r.action, r.patient_id) for r in db.query(AuditLog).filter(AuditLog.patient_id == pid)])
    assert ("access_denied", pid) in rows


def test_audit_log_never_contains_secrets_or_message_text(client):
    pid, _, _ = seeded(client)
    client.post("/api/chat", json={"patient_id": pid, "message": "my secret question about metformin"})
    dump = " ".join(db_scalar(lambda db: [f"{r.action} {r.detail}" for r in db.query(AuditLog).all()]))
    assert "secret question" not in dump and PASSWORD not in dump


# ═══════════════════════════ roles & sharing ═══════════════════════════

def share(owner, pid, email, role):
    return owner.post(f"/api/patients/{pid}/access", json={"email": email, "role": role})


def test_viewer_can_read_and_chat_but_not_change_anything(client, make_client):
    pid, doc_id, med_id = seeded(client)
    doctor, email = make_client("Dr Viewer")
    assert share(client, pid, email, "viewer").status_code == 200

    assert doctor.get(f"/api/patients/{pid}").json()["role"] == "viewer"
    for url in (f"/api/patients/{pid}/documents", f"/api/patients/{pid}/medications", f"/api/patients/{pid}/lab-results",
                f"/api/documents/{doc_id}/file", f"/api/patients/{pid}/health-summary"):
        assert doctor.get(url).status_code == 200, url
    assert doctor.post("/api/chat", json={"patient_id": pid, "message": "meds?"}).status_code == 200

    forbidden = [("POST", f"/api/documents/{doc_id}/reprocess", {}),
                 ("PUT", f"/api/documents/{doc_id}/validate", {"json": {"validation_status": "verified"}}),
                 ("PUT", f"/api/medications/{med_id}/status?status=discontinued", {}),
                 ("GET", f"/api/patients/{pid}/access", {}),
                 ("POST", f"/api/patients/{pid}/access", {"json": {"email": email, "role": "owner"}})]
    for method, url, kw in forbidden:
        assert doctor.request(method, url, **kw).status_code == 403, f"{method} {url}"
    assert upload(doctor, pid).status_code == 403
    assert client.get(f"/api/patients/{pid}/medications").json()[0]["status"] != "discontinued"


def test_editor_can_work_with_records_but_not_manage_sharing(client, make_client):
    pid, doc_id, med_id = seeded(client)
    helper, email = make_client("Family Editor")
    share(client, pid, email, "editor")
    assert upload(helper, pid).status_code == 202
    assert helper.put(f"/api/documents/{doc_id}/validate", json={"validation_status": "verified"}).status_code == 200
    assert helper.put(f"/api/medications/{med_id}/status?status=discontinued").status_code == 200
    assert helper.get(f"/api/patients/{pid}/access").status_code == 403
    assert share(helper, pid, email, "owner").status_code == 403


def test_owner_manages_access_and_revocation_takes_effect_immediately(client, make_client):
    pid, _, _ = seeded(client)
    other, email = make_client("Guest")
    assert other.get(f"/api/patients/{pid}").status_code == 404
    share(client, pid, email, "viewer")
    assert other.get(f"/api/patients/{pid}").status_code == 200
    assert [a["role"] for a in client.get(f"/api/patients/{pid}/access").json()].count("viewer") == 1
    uid = [a for a in client.get(f"/api/patients/{pid}/access").json() if a["email"] == email][0]["user_id"]
    assert client.put(f"/api/patients/{pid}/access/{uid}", json={"role": "editor"}).status_code == 200
    assert other.post(f"/api/patients/{pid}/documents", files={"file": ("x.pdf", b"x", "application/pdf")}).status_code == 202
    assert client.delete(f"/api/patients/{pid}/access/{uid}").status_code == 204
    assert other.get(f"/api/patients/{pid}").status_code == 404             # no waiting for a session to expire
    assert other.get("/api/patients").json() == []


def test_sharing_validation_and_last_owner_protection(client, make_client):
    pid = mk_patient(client)
    me = client.get("/api/auth/me").json()
    assert share(client, pid, "nobody@example.com", "viewer").status_code == 404
    assert share(client, pid, me["email"], "admin").status_code == 422
    assert share(client, pid, me["email"], "viewer").status_code == 409     # would leave no owner
    assert client.delete(f"/api/patients/{pid}/access/{me['id']}").status_code == 409
    assert client.put(f"/api/patients/{pid}/access/{me['id']}", json={"role": "viewer"}).status_code == 409


def test_creator_is_owner_and_sees_only_own_patients(client, make_client):
    mine = mk_patient(client, "Mine")
    other, _ = make_client()
    theirs = mk_patient(other, "Theirs")
    ids = {p["id"] for p in client.get("/api/patients").json()}
    assert mine in ids and theirs not in ids
    assert client.get(f"/api/patients/{mine}").json()["role"] == "owner"


def test_chat_history_is_private_to_each_user(client, make_client):
    pid, _, _ = seeded(client)
    doctor, email = make_client("Doctor")
    share(client, pid, email, "viewer")
    client.post("/api/chat", json={"patient_id": pid, "message": "owner question"})
    doctor.post("/api/chat", json={"patient_id": pid, "message": "doctor question"})
    mine = [m["content"] for m in client.get(f"/api/patients/{pid}/chat-history").json() if m["role"] == "user"]
    theirs = [m["content"] for m in doctor.get(f"/api/patients/{pid}/chat-history").json() if m["role"] == "user"]
    assert mine == ["owner question"] and theirs == ["doctor question"]
    doctor.delete(f"/api/patients/{pid}/chat-history")
    assert len(client.get(f"/api/patients/{pid}/chat-history").json()) == 2     # owner's chat survives


# ═══════════════════════════ web hardening ═══════════════════════════

def test_cross_site_writes_are_blocked_even_with_a_valid_cookie(client):
    evil = {"Origin": "https://evil.example"}
    assert client.post("/api/patients", json={"name": "X"}, headers=evil).status_code == 403
    assert client.post("/api/auth/logout", headers=evil).status_code == 403
    ok = {"Origin": "http://localhost:5173"}
    assert client.post("/api/patients", json={"name": "X"}, headers=ok).status_code == 200


def test_cors_does_not_allow_foreign_origins(anon):
    r = anon.options("/api/patients", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"})
    assert "access-control-allow-origin" not in r.headers
    good = anon.options("/api/patients", headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"})
    assert good.headers.get("access-control-allow-origin") == "http://localhost:5173"
    assert good.headers.get("access-control-allow-credentials") == "true"


def test_security_headers_and_no_store(client):
    r = client.get("/api/patients")
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["x-frame-options"] == "DENY"
    assert r.headers["referrer-policy"] == "no-referrer" and r.headers["cache-control"] == "no-store"
