"""Email verification and password reset."""
import datetime as dt

import mailer
from conftest import PASSWORD, register, token_from_mail
from database import EmailToken, SessionLocal, User

NEW_PW = "a brand new passphrase 42"


def count_mail(to, kind):
    return sum(1 for m in mailer.sent if m["to"] == to and f"/{kind}#token=" in m["body"])


def forgot(c, email):
    return c.post("/api/auth/forgot-password", json={"email": email})


def set_user(email, **fields):
    db = SessionLocal()
    db.query(User).filter(User.email == email).update(fields)
    db.commit()
    db.close()


def set_tokens(**fields):
    db = SessionLocal()
    db.query(EmailToken).update(fields)
    db.commit()
    db.close()


# ── verification ──────────────────────────────────────────────────────────────────────────────
def test_register_sends_link_and_verifying_works_once(anon):
    email = register(anon, verify=False)
    assert anon.get("/api/auth/me").json()["email_verified"] is False
    tok = token_from_mail(email)
    assert anon.post("/api/auth/verify-email", json={"token": tok}).json() == {"verified": True}
    assert anon.get("/api/auth/me").json()["email_verified"] is True
    assert anon.post("/api/auth/verify-email", json={"token": tok}).status_code == 400      # single use


def test_bad_and_expired_verification_links(anon):
    email = register(anon, verify=False)
    assert anon.post("/api/auth/verify-email", json={"token": "nonsense"}).status_code == 400
    tok = token_from_mail(email)
    set_tokens(expires_at=dt.datetime.utcnow() - dt.timedelta(minutes=1))
    assert anon.post("/api/auth/verify-email", json={"token": tok}).status_code == 400


def test_resend_has_cooldown_and_replaces_old_link(anon):
    email = register(anon, verify=False)
    old = token_from_mail(email)
    assert anon.post("/api/auth/resend-verification").status_code == 429               # too soon after sign-up
    set_tokens(created_at=dt.datetime.utcnow() - dt.timedelta(minutes=5))
    assert anon.post("/api/auth/resend-verification").status_code == 202
    assert anon.post("/api/auth/verify-email", json={"token": old}).status_code == 400  # superseded
    assert anon.post("/api/auth/verify-email", json={"token": token_from_mail(email)}).status_code == 200
    assert anon.post("/api/auth/resend-verification").json() == {"already_verified": True}


def test_tokens_are_stored_hashed(anon):
    email = register(anon, verify=False)
    tok = token_from_mail(email)
    db = SessionLocal()
    assert all(tok not in r.token_hash and len(r.token_hash) == 64 for r in db.query(EmailToken))
    db.close()


def test_cannot_share_with_unverified_account(client, make_client):
    _, other_email = make_client()
    pid = client.post("/api/patients", json={"name": "P"}).json()["id"]
    set_user(other_email, email_verified_at=None)
    r = client.post(f"/api/patients/{pid}/access", json={"email": other_email, "role": "viewer"})
    assert r.status_code == 409 and "confirmed" in r.json()["detail"]
    set_user(other_email, email_verified_at=dt.datetime.utcnow())
    assert client.post(f"/api/patients/{pid}/access", json={"email": other_email, "role": "viewer"}).status_code == 200


# ── password reset ────────────────────────────────────────────────────────────────────────────
def test_forgot_password_answer_is_identical_for_known_and_unknown(anon, make_client):
    _, known = make_client()
    a, b = forgot(anon, known), forgot(anon, "nobody-here@example.com")
    assert a.status_code == b.status_code == 202 and a.json() == b.json()
    assert count_mail(known, "reset-password") == 1
    assert not [m for m in mailer.sent if m["to"] == "nobody-here@example.com"]


def test_reset_flow_changes_password_and_signs_out_everywhere(anon, make_client):
    other, email = make_client()
    assert other.get("/api/auth/me").status_code == 200
    forgot(anon, email)
    tok = token_from_mail(email, "reset-password")
    assert anon.post("/api/auth/reset-password", json={"token": tok, "new_password": NEW_PW}).status_code == 200
    assert other.get("/api/auth/me").status_code == 401                                      # old session revoked
    assert anon.post("/api/auth/login", json={"email": email, "password": PASSWORD}).status_code == 401
    assert anon.post("/api/auth/login", json={"email": email, "password": NEW_PW}).status_code == 200
    assert anon.post("/api/auth/reset-password", json={"token": tok, "new_password": NEW_PW + "x"}).status_code == 400   # single use
    assert any("password was changed" in m["subject"] for m in mailer.sent if m["to"] == email)


def test_weak_password_does_not_burn_the_link(anon, make_client):
    _, email = make_client()
    forgot(anon, email)
    tok = token_from_mail(email, "reset-password")
    assert anon.post("/api/auth/reset-password", json={"token": tok, "new_password": "short"}).status_code == 422
    assert anon.post("/api/auth/reset-password", json={"token": tok, "new_password": NEW_PW}).status_code == 200


def test_newer_reset_link_replaces_older_and_expiry_enforced(anon, make_client):
    _, email = make_client()
    forgot(anon, email)
    old = token_from_mail(email, "reset-password")
    forgot(anon, email)
    new = token_from_mail(email, "reset-password")
    assert old != new
    assert anon.post("/api/auth/reset-password", json={"token": old, "new_password": NEW_PW}).status_code == 400
    set_tokens(expires_at=dt.datetime.utcnow() - dt.timedelta(seconds=1))
    assert anon.post("/api/auth/reset-password", json={"token": new, "new_password": NEW_PW}).status_code == 400


def test_reset_clears_lockout_and_verifies_email(anon):
    email = register(anon, verify=False)
    set_user(email, locked_until=dt.datetime.utcnow() + dt.timedelta(minutes=10))
    forgot(anon, email)
    anon.post("/api/auth/reset-password", json={"token": token_from_mail(email, "reset-password"), "new_password": NEW_PW})
    r = anon.post("/api/auth/login", json={"email": email, "password": NEW_PW})
    assert r.status_code == 200 and r.json()["email_verified"] is True


def test_forgot_password_is_rate_limited_silently(anon, make_client):
    _, email = make_client()
    for _ in range(6):
        assert forgot(anon, email).status_code == 202
    assert count_mail(email, "reset-password") == 3                                          # 4th+ request sends nothing


def test_reset_token_cannot_verify_and_deactivated_user_gets_nothing(anon, make_client):
    _, email = make_client()
    forgot(anon, email)
    tok = token_from_mail(email, "reset-password")
    assert anon.post("/api/auth/verify-email", json={"token": tok}).status_code == 400       # purposes don't mix
    set_user(email, is_active=False)
    before = len(mailer.sent)
    forgot(anon, email)
    assert len(mailer.sent) == before
    assert anon.post("/api/auth/reset-password", json={"token": tok, "new_password": NEW_PW}).status_code == 400
