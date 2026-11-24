"""Email verification and password reset.

Tokens are random 256-bit values, single use, short lived, and stored only as a SHA-256 hash (like sessions), so a
database leak can't be replayed. Links carry the token in the URL *fragment* (#token=...), which browsers never send
to servers, proxies or logs.
"""
import datetime as dt
import hashlib
import os
import secrets

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import update
from sqlalchemy.orm import Session

import auth
import mailer
from database import EmailToken, User, UserSession, get_db

router = APIRouter()

FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173").rstrip("/")
VERIFY_TTL = dt.timedelta(hours=24)
RESET_TTL = dt.timedelta(minutes=30)
RESEND_COOLDOWN = dt.timedelta(seconds=60)
BAD_LINK = "This link is invalid or has expired. Request a new one."

_hash = lambda t: hashlib.sha256(t.encode()).hexdigest()


class TokenIn(BaseModel):
    token: str


class EmailIn(BaseModel):
    email: str


class ResetIn(BaseModel):
    token: str
    new_password: str


def issue_token(db: Session, user: User, purpose: str, ttl: dt.timedelta) -> str:
    """Create a fresh token; any earlier unused token for the same purpose stops working."""
    now = dt.datetime.utcnow()
    db.execute(update(EmailToken).where(EmailToken.user_id == user.id, EmailToken.purpose == purpose,
                                        EmailToken.used_at.is_(None)).values(used_at=now))
    raw = secrets.token_urlsafe(32)
    db.add(EmailToken(user_id=user.id, purpose=purpose, token_hash=_hash(raw), expires_at=now + ttl))
    db.commit()
    return raw


def find_token(db: Session, raw: str, purpose: str) -> EmailToken | None:
    row = db.query(EmailToken).filter(EmailToken.token_hash == _hash((raw or "")[:200]),
                                      EmailToken.purpose == purpose).first()
    if not row or row.used_at is not None or row.expires_at < dt.datetime.utcnow():
        return None
    return row


def consume(db: Session, row: EmailToken) -> bool:
    """Atomically mark used. False if someone else used it first (double click, replay)."""
    res = db.execute(update(EmailToken).where(EmailToken.id == row.id, EmailToken.used_at.is_(None))
                     .values(used_at=dt.datetime.utcnow()))
    db.commit()
    return res.rowcount == 1


# ── emails ────────────────────────────────────────────────────────────────────────────────────
def queue_verification(background: BackgroundTasks, db: Session, user: User) -> None:
    raw = issue_token(db, user, "verify", VERIFY_TTL)
    background.add_task(
        mailer.send, user.email, "Confirm your HealthVault email",
        f"Hi {user.name},\n\nConfirm this email address to finish setting up your HealthVault account:\n\n"
        f"{FRONTEND_URL}/verify-email#token={raw}\n\nThe link works once and expires in 24 hours. "
        f"If you didn't create this account, ignore this email.")


# ── verification ──────────────────────────────────────────────────────────────────────────────
@router.post("/api/auth/verify-email")
def verify_email(body: TokenIn, request: Request, db: Session = Depends(get_db)):
    if not auth.throttle(f"verify:{request.client.host if request.client else '?'}", 20, 600):
        raise HTTPException(429, "Too many attempts. Try again in a few minutes.")
    row = find_token(db, body.token, "verify")
    if not row or not consume(db, row):
        raise HTTPException(400, BAD_LINK)
    user = db.get(User, row.user_id)
    if user and not user.email_verified_at:
        user.email_verified_at = dt.datetime.utcnow()
        db.commit()
    auth.audit(db, request, row.user_id, None, "email_verified")
    return {"verified": True}


@router.post("/api/auth/resend-verification", status_code=202)
def resend_verification(request: Request, background: BackgroundTasks, db: Session = Depends(get_db),
                        user: User = Depends(auth.current_user)):
    if user.email_verified_at:
        return {"already_verified": True}
    last = db.query(EmailToken).filter(EmailToken.user_id == user.id, EmailToken.purpose == "verify") \
        .order_by(EmailToken.id.desc()).first()
    if (last and dt.datetime.utcnow() - last.created_at < RESEND_COOLDOWN) or not auth.throttle(f"resend:{user.id}", 5, 3600):
        raise HTTPException(429, "Please wait a minute before requesting another email.")
    queue_verification(background, db, user)
    auth.audit(db, request, user.id, None, "verification_sent")
    return {"sent": True}


# ── password reset ────────────────────────────────────────────────────────────────────────────
FORGOT_REPLY = {"message": "If an account exists for that email, a reset link is on its way. It expires in 30 minutes."}


@router.post("/api/auth/forgot-password", status_code=202)
def forgot_password(body: EmailIn, request: Request, background: BackgroundTasks, db: Session = Depends(get_db)):
    """Always the same answer, whether or not the account exists, so this can't be used to find out who has one."""
    email = body.email.strip().lower()
    ip = request.client.host if request.client else "?"
    ok_ip = auth.throttle(f"forgot-ip:{ip}", 10, 3600)
    ok_acct = auth.throttle(f"forgot:{email}", 3, 3600)
    user = db.query(User).filter(User.email == email).first() if auth.EMAIL_RE.match(email) else None
    if ok_ip and ok_acct and user and user.is_active:
        raw = issue_token(db, user, "reset", RESET_TTL)
        background.add_task(
            mailer.send, user.email, "Reset your HealthVault password",
            f"Hi {user.name},\n\nSomeone (hopefully you) asked to reset your HealthVault password. Choose a new one here:\n\n"
            f"{FRONTEND_URL}/reset-password#token={raw}\n\nThe link works once and expires in 30 minutes. "
            f"If you didn't ask for this, ignore this email - your password has not changed.")
        auth.audit(db, request, user.id, None, "password_reset_requested")
    else:
        auth.audit(db, request, user.id if user else None, None, "password_reset_requested_noop")
    return FORGOT_REPLY


@router.post("/api/auth/reset-password")
def reset_password(body: ResetIn, request: Request, background: BackgroundTasks, db: Session = Depends(get_db)):
    if not auth.throttle(f"reset:{request.client.host if request.client else '?'}", 20, 600):
        raise HTTPException(429, "Too many attempts. Try again in a few minutes.")
    row = find_token(db, body.token, "reset")
    user = db.get(User, row.user_id) if row else None
    if not row or not user or not user.is_active:
        raise HTTPException(400, BAD_LINK)
    problem = auth.validate_password(body.new_password, user.email)
    if problem:                                   # a typo must not burn the link
        raise HTTPException(422, problem)
    if not consume(db, row):
        raise HTTPException(400, BAD_LINK)
    user.password_hash = auth.hash_password(body.new_password)
    user.failed_attempts, user.locked_until = 0, None
    if not user.email_verified_at:                # they just proved they control this mailbox
        user.email_verified_at = dt.datetime.utcnow()
    db.query(UserSession).filter(UserSession.user_id == user.id).delete()      # sign out everywhere
    db.commit()
    auth.audit(db, request, user.id, None, "password_reset_done")
    background.add_task(
        mailer.send, user.email, "Your HealthVault password was changed",
        f"Hi {user.name},\n\nYour HealthVault password was just changed and you were signed out on all devices. "
        f"If this wasn't you, reset your password again right away and check who has access to your records.")
    return {"reset": True}
