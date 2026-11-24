"""Shared test setup: one temporary database/upload dir for the whole run, and logged-in clients."""
import os
import sys
import tempfile
import uuid

_tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}/test.db"
os.environ["UPLOAD_DIR"] = f"{_tmp}/uploads"
os.environ["STATUS_RECOMPUTE_HOURS"] = "0"
os.environ["MAIL_BACKEND"] = "memory"
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest
from fastapi.testclient import TestClient

import ai_service
import auth
from main import app

PASSWORD = "correct horse battery staple"


class _NoRealModel:
    async def extract(self, paths):
        raise AssertionError("a test reached the real model backend")

    async def generate(self, *a, **k):
        raise AssertionError("a test reached the real model backend")


ai_service._backend = _NoRealModel()


def token_from_mail(to: str, kind: str = "verify-email") -> str:
    """Token from the newest message sent to `to` that links to /<kind>."""
    import mailer
    for m in reversed(mailer.sent):
        if m["to"] == to and f"/{kind}#token=" in m["body"]:
            return m["body"].split(f"/{kind}#token=")[1].split()[0]
    raise AssertionError(f"no {kind} email sent to {to}")


def register(c: TestClient, email: str | None = None, name: str = "Test User", password: str = PASSWORD, verify: bool = True):
    email = email or f"user-{uuid.uuid4().hex[:10]}@example.com"
    r = c.post("/api/auth/register", json={"email": email, "name": name, "password": password})
    assert r.status_code == 200, r.text
    if verify:                                   # go through the real link flow
        c.post("/api/auth/verify-email", json={"token": token_from_mail(email)})
    return email


@pytest.fixture(autouse=True)
def _fresh_throttle():
    auth.reset_throttle()
    yield
    auth.reset_throttle()


@pytest.fixture()
def client():
    """A client already signed in as a brand-new user."""
    with TestClient(app) as c:
        register(c)
        yield c


@pytest.fixture()
def anon():
    """A client with no session."""
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def make_client():
    """Factory for additional signed-in users: returns (client, email). Closes them at teardown."""
    made = []

    def factory(name="Other User"):
        ctx = TestClient(app)
        ctx.__enter__()
        made.append(ctx)
        return ctx, register(ctx, name=name)

    yield factory
    for c in made:
        c.__exit__(None, None, None)
