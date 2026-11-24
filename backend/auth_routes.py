"""Account and sharing endpoints. Access to everything else is enforced by auth.guard."""
import datetime as dt

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

import account_routes
import auth
from database import PatientAccess, User, UserSession, get_db

router = APIRouter()


class RegisterIn(BaseModel):
    email: str
    name: str
    password: str


class LoginIn(BaseModel):
    email: str
    password: str


class PasswordIn(BaseModel):
    current_password: str
    new_password: str


class AccessIn(BaseModel):
    email: str
    role: str


class RoleIn(BaseModel):
    role: str


def me_out(user: User) -> dict:
    return {"id": user.id, "email": user.email, "name": user.name, "email_verified": bool(user.email_verified_at)}


@router.get("/api/health")
def health():
    return {"status": "ok"}


@router.post("/api/auth/register")
def register(body: RegisterIn, request: Request, response: Response, background: BackgroundTasks,
             db: Session = Depends(get_db)):
    if not auth.ALLOW_REGISTRATION:
        raise HTTPException(403, "Registration is disabled on this server")
    if not auth.throttle(f"register:{request.client.host if request.client else '?'}", 10, 3600):
        raise HTTPException(429, "Too many sign-up attempts. Try again later.")
    email = body.email.strip().lower()
    name = body.name.strip()
    if not auth.EMAIL_RE.match(email):
        raise HTTPException(422, "Enter a valid email address.")
    if not (1 <= len(name) <= 100):
        raise HTTPException(422, "Enter your name (up to 100 characters).")
    problem = auth.validate_password(body.password, email)
    if problem:
        raise HTTPException(422, problem)
    if db.query(User).filter(User.email == email).first():
        raise HTTPException(409, "An account with this email already exists.")
    user = User(email=email, name=name, password_hash=auth.hash_password(body.password))
    db.add(user)
    db.commit()
    db.refresh(user)
    auth.start_session(db, response, user, request)
    auth.audit(db, request, user.id, None, "register")
    account_routes.queue_verification(background, db, user)
    return me_out(user)


@router.post("/api/auth/login")
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    email = body.email.strip().lower()
    ip = request.client.host if request.client else "?"
    if not auth.throttle(f"ip:{ip}", 30, 600) or not auth.throttle(f"acct:{email}", 10, 600):
        raise HTTPException(429, "Too many attempts. Try again in a few minutes.")
    user = db.query(User).filter(User.email == email).first()
    now = dt.datetime.utcnow()

    # Always run one scrypt verification so unknown accounts, wrong passwords and locked accounts take similar time.
    password_ok = auth.verify_password(body.password, user.password_hash if user else auth._DUMMY_HASH)
    if user and user.locked_until and user.locked_until > now:
        auth.audit(db, request, user.id, None, "login_blocked_locked")
        raise HTTPException(429, "Too many attempts. Try again in a few minutes.")
    if not (user and user.is_active and password_ok):
        if user:
            user.failed_attempts = (user.failed_attempts or 0) + 1
            if user.failed_attempts >= auth.MAX_FAILED:
                user.locked_until = now + dt.timedelta(minutes=auth.LOCK_MINUTES)
                user.failed_attempts = 0
            db.commit()
        auth.audit(db, request, user.id if user else None, None, "login_failed")
        raise HTTPException(401, "Incorrect email or password.")      # same message for every failure

    user.failed_attempts, user.locked_until = 0, None
    db.commit()
    auth.start_session(db, response, user, request)
    auth.audit(db, request, user.id, None, "login")
    return me_out(user)


@router.post("/api/auth/logout", status_code=204)
def logout(request: Request, response: Response, db: Session = Depends(get_db), user: User = Depends(auth.current_user)):
    auth.audit(db, request, user.id, None, "logout")
    auth.end_session(db, request, response)


@router.get("/api/auth/me")
def me(user: User = Depends(auth.current_user)):
    return me_out(user)


@router.post("/api/auth/password", status_code=204)
def change_password(body: PasswordIn, request: Request, response: Response, db: Session = Depends(get_db),
                    user: User = Depends(auth.current_user)):
    if not auth.throttle(f"pw:{user.id}", 10, 600):
        raise HTTPException(429, "Too many attempts. Try again in a few minutes.")
    if not auth.verify_password(body.current_password, user.password_hash):
        raise HTTPException(403, "Current password is incorrect.")
    problem = auth.validate_password(body.new_password, user.email)
    if problem:
        raise HTTPException(422, problem)
    user.password_hash = auth.hash_password(body.new_password)
    db.query(UserSession).filter(UserSession.user_id == user.id).delete()      # sign out everywhere
    db.commit()
    auth.start_session(db, response, user, request)                             # ...then keep this device signed in
    auth.audit(db, request, user.id, None, "password_changed")


# ── sharing (owner only; enforced by auth.NEED_OVERRIDES) ─────────────────────────────────────

def _owner_count(db: Session, patient_id: int) -> int:
    return db.query(PatientAccess).filter(PatientAccess.patient_id == patient_id, PatientAccess.role == "owner").count()


def _check_role(role: str) -> None:
    if role not in auth.ROLES:
        raise HTTPException(422, f"Role must be one of: {', '.join(auth.ROLES)}")


@router.get("/api/patients/{patient_id}/access")
def list_access(patient_id: int, db: Session = Depends(get_db)):
    rows = db.query(PatientAccess, User).join(User, User.id == PatientAccess.user_id) \
        .filter(PatientAccess.patient_id == patient_id).order_by(PatientAccess.id).all()
    return [{"user_id": u.id, "email": u.email, "name": u.name, "role": a.role} for a, u in rows]


@router.post("/api/patients/{patient_id}/access")
def grant_access(patient_id: int, body: AccessIn, request: Request, db: Session = Depends(get_db),
                 user: User = Depends(auth.current_user)):
    _check_role(body.role)
    if not auth.throttle(f"share:{user.id}", 30, 3600):
        raise HTTPException(429, "Too many sharing changes. Try again later.")
    target = db.query(User).filter(User.email == body.email.strip().lower()).first()
    if not target or not target.is_active:
        raise HTTPException(404, "No account with that email. Ask them to register first, then share again.")
    if not target.email_verified_at:
        raise HTTPException(409, "That person hasn't confirmed their email yet. Ask them to open the link we sent, then share again.")
    row = db.query(PatientAccess).filter(PatientAccess.user_id == target.id, PatientAccess.patient_id == patient_id).first()
    if row:
        if row.role == "owner" and body.role != "owner" and _owner_count(db, patient_id) <= 1:
            raise HTTPException(409, "A patient must keep at least one owner.")
        row.role = body.role
    else:
        db.add(PatientAccess(user_id=target.id, patient_id=patient_id, role=body.role))
    db.commit()
    auth.audit(db, request, user.id, patient_id, "share_granted", f"user {target.id} as {body.role}")
    return {"user_id": target.id, "email": target.email, "name": target.name, "role": body.role}


@router.put("/api/patients/{patient_id}/access/{user_id}")
def change_access(patient_id: int, user_id: int, body: RoleIn, request: Request, db: Session = Depends(get_db),
                  user: User = Depends(auth.current_user)):
    _check_role(body.role)
    row = db.query(PatientAccess).filter(PatientAccess.user_id == user_id, PatientAccess.patient_id == patient_id).first()
    if not row:
        raise HTTPException(404, "Not found")
    if row.role == "owner" and body.role != "owner" and _owner_count(db, patient_id) <= 1:
        raise HTTPException(409, "A patient must keep at least one owner.")
    row.role = body.role
    db.commit()
    auth.audit(db, request, user.id, patient_id, "share_changed", f"user {user_id} to {body.role}")
    return {"user_id": user_id, "role": body.role}


@router.delete("/api/patients/{patient_id}/access/{user_id}", status_code=204)
def revoke_access(patient_id: int, user_id: int, request: Request, db: Session = Depends(get_db),
                  user: User = Depends(auth.current_user)):
    row = db.query(PatientAccess).filter(PatientAccess.user_id == user_id, PatientAccess.patient_id == patient_id).first()
    if not row:
        raise HTTPException(404, "Not found")
    if row.role == "owner" and _owner_count(db, patient_id) <= 1:
        raise HTTPException(409, "A patient must keep at least one owner.")
    db.delete(row)
    db.commit()
    auth.audit(db, request, user.id, patient_id, "share_revoked", f"user {user_id}")
