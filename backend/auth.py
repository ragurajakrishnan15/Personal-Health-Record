"""Authentication and access control.

Design:
  * Passwords: scrypt (stdlib) with a per-user salt. Login failures are throttled and lock the account briefly.
  * Sessions: random 256-bit token in an HttpOnly, SameSite=Lax cookie; only its SHA-256 is stored server-side,
    so sessions can be revoked and a database leak can't be replayed.
  * Default deny: `guard` is a GLOBAL dependency. Every route needs a valid session unless listed in PUBLIC, and any
    route with a patient_id / doc_id / med_id / appt_id / rem_id / expense_id in its path is checked against the user's role on that patient.
  * No existence leaks: a patient you cannot access answers 404, exactly like one that does not exist.
  * Roles: viewer (read) < editor (upload, validate, change medications) < owner (manage who has access).
"""
import base64
import datetime as dt
import hashlib
import hmac
import os
import re
import secrets
import time
from collections import defaultdict, deque

from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from database import Appointment, AuditLog, Expense, MedicalDocument, Reminder, Medication, PatientAccess, User, UserSession, get_db

COOKIE_NAME = "phr_session"
SESSION_IDLE_DAYS = int(os.getenv("SESSION_IDLE_DAYS", "7"))
SESSION_MAX_DAYS = int(os.getenv("SESSION_MAX_DAYS", "30"))
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "false").lower() == "true"      # set true behind HTTPS
ALLOW_REGISTRATION = os.getenv("ALLOW_REGISTRATION", "true").lower() == "true"
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",")
                if o.strip()]
MAX_FAILED = 5
LOCK_MINUTES = 15

ROLE_RANK = {"viewer": 1, "editor": 2, "owner": 3}
ROLES = tuple(ROLE_RANK)
PUBLIC = {("POST", "/api/auth/login"), ("POST", "/api/auth/register"), ("GET", "/api/health"),
          ("POST", "/api/auth/verify-email"), ("POST", "/api/auth/forgot-password"), ("POST", "/api/auth/reset-password")}
# Routes needing more (or less) than the default for their HTTP method. Default: GET -> viewer, writes -> editor.
NEED_OVERRIDES = {
    ("DELETE", "/api/patients/{patient_id}/chat-history"): "viewer",    # clears only the caller's own messages
    ("GET", "/api/patients/{patient_id}/export"): "owner",
    ("DELETE", "/api/patients/{patient_id}"): "owner",
    ("GET", "/api/patients/{patient_id}/access"): "owner",
    ("POST", "/api/patients/{patient_id}/access"): "owner",
    ("PUT", "/api/patients/{patient_id}/access/{user_id}"): "owner",
    ("DELETE", "/api/patients/{patient_id}/access/{user_id}"): "owner",
}
DEFAULT_NEED = {"GET": "viewer", "HEAD": "viewer", "POST": "editor", "PUT": "editor", "PATCH": "editor", "DELETE": "editor"}

# ── passwords ───────────────────────────────────────────────────────────────────────────────
_N, _R, _P = 2 ** 14, 8, 1
_b64 = lambda b: base64.b64encode(b).decode()


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    h = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, maxmem=64 * 1024 * 1024)
    return f"scrypt${_N}${_R}${_P}${_b64(salt)}${_b64(h)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, n, r, p, salt, expected = stored.split("$")
        h = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p),
                           maxmem=64 * 1024 * 1024)
        return hmac.compare_digest(h, base64.b64decode(expected))
    except Exception:
        return False


_DUMMY_HASH = hash_password("timing-equaliser-not-a-real-password")      # so unknown emails cost the same as wrong passwords
_COMMON = {"password12", "password123", "1234567890", "qwerty12345", "letmein1234", "welcome1234", "iloveyou123",
           "admin12345", "changeme123", "passw0rd123"}


def validate_password(password: str, email: str = "") -> str | None:
    """Return a human-readable problem, or None if acceptable."""
    if len(password) < 10:
        return "Password must be at least 10 characters."
    if len(password) > 128:
        return "Password must be at most 128 characters."
    if password.lower() in _COMMON or len(set(password)) < 4:
        return "That password is too easy to guess."
    local = email.split("@")[0].lower()
    if local and len(local) >= 4 and local in password.lower():
        return "Password must not contain your email name."
    return None


EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,255}\.[^@\s]{2,}$")

# ── throttling (in-memory: per process; use Redis or the platform's limiter when running several workers) ──────
_hits: dict[str, deque] = defaultdict(deque)


def throttle(key: str, limit: int, window_s: int) -> bool:
    """True if allowed. Records the attempt."""
    now = time.monotonic()
    q = _hits[key]
    while q and now - q[0] > window_s:
        q.popleft()
    if len(q) >= limit:
        return False
    q.append(now)
    return True


def reset_throttle() -> None:          # used by tests
    _hits.clear()


# ── audit ─────────────────────────────────────────────────────────────────────────────────────
def audit(db: Session, request: Request | None, user_id: int | None, patient_id: int | None, action: str,
          detail: str | None = None) -> None:
    ip = request.client.host if request is not None and request.client else None
    db.add(AuditLog(user_id=user_id, patient_id=patient_id, action=action, detail=(detail or "")[:200] or None, ip=ip))
    db.commit()


# ── sessions ──────────────────────────────────────────────────────────────────────────────────
_hash_token = lambda t: hashlib.sha256(t.encode()).hexdigest()


def start_session(db: Session, response: Response, user: User, request: Request) -> None:
    token = secrets.token_urlsafe(32)
    now = dt.datetime.utcnow()
    db.add(UserSession(user_id=user.id, token_hash=_hash_token(token), created_at=now, last_used=now,
                       expires_at=now + dt.timedelta(days=SESSION_IDLE_DAYS),
                       user_agent=(request.headers.get("user-agent") or "")[:200]))
    db.commit()
    response.set_cookie(COOKIE_NAME, token, httponly=True, samesite="lax", secure=COOKIE_SECURE,
                        max_age=SESSION_IDLE_DAYS * 86400, path="/")


def end_session(db: Session, request: Request, response: Response) -> None:
    token = request.cookies.get(COOKIE_NAME)
    if token:
        db.query(UserSession).filter(UserSession.token_hash == _hash_token(token)).delete()
        db.commit()
    response.delete_cookie(COOKIE_NAME, path="/")


def user_from_request(request: Request, db: Session) -> User | None:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    sess = db.query(UserSession).filter(UserSession.token_hash == _hash_token(token)).first()
    now = dt.datetime.utcnow()
    if not sess or sess.expires_at < now or sess.created_at + dt.timedelta(days=SESSION_MAX_DAYS) < now:
        if sess:
            db.delete(sess)
            db.commit()
        return None
    user = db.get(User, sess.user_id)
    if not user or not user.is_active:
        return None
    if now - sess.last_used > dt.timedelta(minutes=10):       # sliding idle expiry, written at most every 10 minutes
        sess.last_used = now
        sess.expires_at = now + dt.timedelta(days=SESSION_IDLE_DAYS)
        db.commit()
    return user


# ── access control ──────────────────────────────────────────────────────────────────────────────
def get_role(db: Session, user_id: int, patient_id: int) -> str | None:
    row = db.query(PatientAccess).filter(PatientAccess.user_id == user_id, PatientAccess.patient_id == patient_id).first()
    return row.role if row else None


def authorize(db: Session, request: Request, user: User, patient_id: int, need: str = "viewer") -> str:
    """Return the user's role on the patient, or raise 404 (no access) / 403 (role too low)."""
    role = get_role(db, user.id, patient_id)
    if role is None:
        audit(db, request, user.id, patient_id, "access_denied", f"{request.method} {request.url.path}")
        raise HTTPException(404, "Not found")
    if ROLE_RANK[role] < ROLE_RANK[need]:
        audit(db, request, user.id, patient_id, "forbidden", f"{request.method} {request.url.path} needs {need}")
        raise HTTPException(403, f"This action needs the '{need}' role on this patient")
    return role


def guard(request: Request, db: Session = Depends(get_db)) -> None:
    """GLOBAL dependency: require a session on every route and enforce per-patient roles from the URL."""
    route = request.scope.get("route")
    template = getattr(route, "path", request.url.path)
    method = request.method.upper()
    if (method, template) in PUBLIC:
        return
    user = user_from_request(request, db)
    if user is None:
        raise HTTPException(401, "Not signed in")
    request.state.user = user

    params = request.path_params
    patient_id = params.get("patient_id")
    if patient_id is None and "doc_id" in params:
        doc = db.get(MedicalDocument, params["doc_id"])
        patient_id = doc.patient_id if doc else None
        if doc is None:
            raise HTTPException(404, "Not found")
    if patient_id is None and "med_id" in params:
        med = db.get(Medication, params["med_id"])
        patient_id = med.patient_id if med else None
        if med is None:
            raise HTTPException(404, "Not found")
    if patient_id is None:
        for param, model in (("appt_id", Appointment), ("rem_id", Reminder), ("expense_id", Expense)):
            if param in params:
                item = db.get(model, params[param])
                if item is None:
                    raise HTTPException(404, "Not found")
                patient_id = item.patient_id
    if patient_id is not None:
        need = NEED_OVERRIDES.get((method, template)) or DEFAULT_NEED.get(method, "editor")
        request.state.role = authorize(db, request, user, int(patient_id), need)


def current_user(request: Request) -> User:
    """Route dependency: the authenticated user (set by `guard`)."""
    user = getattr(request.state, "user", None)
    if user is None:
        raise HTTPException(401, "Not signed in")
    return user
