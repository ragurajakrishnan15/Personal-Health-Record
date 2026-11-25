#!/usr/bin/env python
"""Account administration from the command line.

    python manage.py create-user --email a@example.com --name "Ada"     # prompts for the password (not echoed)
    python manage.py list-users
    python manage.py grant --email a@example.com --patient 3 --role owner  # owner | editor | viewer
    python manage.py revoke --email a@example.com --patient 3
    python manage.py claim-orphans --email a@example.com                # give an owner to patients nobody can see
                                                                        # (e.g. data created before logins existed)
    python manage.py deactivate --email a@example.com                   # blocks login and existing sessions
    python manage.py verify-user --email a@example.com                  # mark an email as confirmed without the link
    python manage.py recompute-meds                                     # re-apply the medication status rule now
    python manage.py repair-records                                     # rebuild replaced medicines and allergy lists
"""
import argparse
import datetime as dt
import getpass
import sys

import auth
from database import PatientAccess, Patient, SessionLocal, User, UserSession, init_db


def user_by_email(db, email):
    u = db.query(User).filter(User.email == email.strip().lower()).first()
    if not u:
        sys.exit(f"No user with email {email}")
    return u


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("create-user", "grant", "revoke", "claim-orphans", "deactivate"):
        p = sub.add_parser(name)
        p.add_argument("--email", required=True)
        if name == "create-user":
            p.add_argument("--name", required=True)
        if name in ("grant", "revoke"):
            p.add_argument("--patient", type=int, required=True)
        if name == "grant":
            p.add_argument("--role", choices=auth.ROLES, required=True)
    sub.add_parser("list-users")
    sub.add_parser("recompute-meds")
    sub.add_parser("repair-records")
    sub.add_parser("verify-user").add_argument("--email", required=True)
    a = ap.parse_args()

    init_db()
    db = SessionLocal()
    if a.cmd == "create-user":
        email = a.email.strip().lower()
        if not auth.EMAIL_RE.match(email):
            sys.exit("Invalid email")
        if db.query(User).filter(User.email == email).first():
            sys.exit("A user with that email already exists")
        pw = getpass.getpass("Password: ")
        problem = auth.validate_password(pw, email)
        if problem:
            sys.exit(problem)
        if getpass.getpass("Repeat password: ") != pw:
            sys.exit("Passwords do not match")
        db.add(User(email=email, name=a.name.strip(), password_hash=auth.hash_password(pw),
                    email_verified_at=dt.datetime.utcnow()))      # created by an admin: trusted
        db.commit()
        print(f"Created {email}")
    elif a.cmd == "list-users":
        for u in db.query(User).order_by(User.id):
            n = db.query(PatientAccess).filter(PatientAccess.user_id == u.id).count()
            print(f"{u.id:3d}  {u.email:32s} {u.name:24s} {'active' if u.is_active else 'DISABLED':8s} {n} patient(s)")
    elif a.cmd == "grant":
        u = user_by_email(db, a.email)
        if not db.get(Patient, a.patient):
            sys.exit(f"No patient {a.patient}")
        row = db.query(PatientAccess).filter(PatientAccess.user_id == u.id, PatientAccess.patient_id == a.patient).first()
        if row:
            row.role = a.role
        else:
            db.add(PatientAccess(user_id=u.id, patient_id=a.patient, role=a.role))
        db.commit()
        print(f"{u.email} is now {a.role} of patient {a.patient}")
    elif a.cmd == "revoke":
        u = user_by_email(db, a.email)
        n = db.query(PatientAccess).filter(PatientAccess.user_id == u.id, PatientAccess.patient_id == a.patient).delete()
        db.commit()
        print("Revoked" if n else "That user had no access")
    elif a.cmd == "claim-orphans":
        u = user_by_email(db, a.email)
        with_access = {r[0] for r in db.query(PatientAccess.patient_id).distinct()}
        orphans = [p for p in db.query(Patient) if p.id not in with_access]
        for p in orphans:
            db.add(PatientAccess(user_id=u.id, patient_id=p.id, role="owner"))
        db.commit()
        print(f"{u.email} now owns {len(orphans)} previously unowned patient(s)")
    elif a.cmd == "verify-user":
        u = user_by_email(db, a.email)
        u.email_verified_at = u.email_verified_at or dt.datetime.utcnow()
        db.commit()
        print(f"Marked {u.email} as verified")
    elif a.cmd == "recompute-meds":
        from persistence import recompute_statuses
        print(recompute_statuses(db) or "no changes")
    elif a.cmd == "repair-records":
        from persistence import refresh_patient
        ids = [pid for (pid,) in db.query(Patient.id)]
        for pid in ids:
            refresh_patient(db, pid)
        db.commit()
        print(f"Rebuilt replaced-medicine statuses and allergy lists for {len(ids)} patient(s)")
    elif a.cmd == "deactivate":
        u = user_by_email(db, a.email)
        u.is_active = False
        db.query(UserSession).filter(UserSession.user_id == u.id).delete()
        db.commit()
        print(f"Deactivated {u.email} and ended their sessions")


if __name__ == "__main__":
    main()
