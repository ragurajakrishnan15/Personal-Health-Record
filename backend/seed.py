#!/usr/bin/env python
"""Load demo data: synthetic patients + their documents, run through the same
postprocess + persistence code the live upload pipeline uses (no AI calls, no API keys needed).

    python ../tools/synth/generate.py --count 60 --seed 42 --out ../tools/synth/output --clean   # once
    python seed.py --reset
Options: --synth DIR, --reset (drop all tables first), --patients N, --pending-ratio 0.3
"""
import argparse
import copy
import datetime as dt
import json
import os
import os as _os
import random
import secrets
import shutil
import uuid

import auth
from ai_service import postprocess
from database import (Appointment, Base, Consultation, Expense, MedicalDocument, Medication, Patient, PatientAccess, Reminder,
                      SessionLocal, UPLOAD_DIR, User, engine, init_db)
from persistence import persist_extraction

BLOOD = ["A+", "A-", "B+", "B-", "O+", "O-", "AB+", "AB-"]


def seed_schedule(db, pat, creator, rng):
    """Sample appointments and reminders, dated relative to today so the 'Upcoming' and 'Active' tabs are never empty."""
    today = dt.date.today()
    day = lambda n: (today + dt.timedelta(days=n)).isoformat()
    last = (db.query(Consultation).filter(Consultation.patient_id == pat.id)
            .order_by(Consultation.consultation_date.desc()).first())
    doctor = (last.doctor_name if last and last.doctor_name else None) or "Dr. Demo"
    place = (last.hospital if last and last.hospital else None) or "City Medical Clinic"
    appts = [
        dict(title="Follow-up visit", doctor=doctor, location=place, appt_date=day(rng.randint(3, 14)),
             appt_time=rng.choice(["09:30", "11:00", "14:15", "16:00"]), notes="Bring recent lab reports.", status="scheduled"),
        dict(title="Blood tests (fasting)", doctor=None, location="Pathology lab", appt_date=day(rng.randint(20, 45)),
             appt_time="08:00", notes="Fast for 10-12 hours; water is fine.", status="scheduled"),
        dict(title="Routine check-up", doctor=doctor, location=place, appt_date=day(-rng.randint(25, 60)),
             appt_time="10:00", notes="Blood pressure and weight checked.", status="done"),
    ]
    for a in appts:
        db.add(Appointment(patient_id=pat.id, created_by=creator.id, **a))
    meds = (db.query(Medication).filter(Medication.patient_id == pat.id, Medication.status.in_(("active", "lapsed")))
            .order_by(Medication.start_date.desc()).limit(2).all())
    rems = [dict(title="Check blood pressure at home", notes="Write the reading in your diary.", due_date=day(1),
                 due_time="08:00", repeat="daily", medication_id=None),
            dict(title="Book next eye / dental check", notes=None, due_date=day(rng.randint(5, 20)), due_time=None,
                 repeat="none", medication_id=None)]
    for m in meds[:1]:
        rems.append(dict(title=f"Refill {m.name}", notes="Ask the pharmacy about a refill.", due_date=day(rng.randint(2, 10)),
                         due_time="18:00", repeat="monthly", medication_id=m.id))
    for r in rems:
        db.add(Reminder(patient_id=pat.id, created_by=creator.id, status="active", **r))
    db.commit()
    return len(appts), len(rems)


def seed_expenses(db, pat, creator, rng):
    """Made-up sample costs so the Expenses page has something to total in the demo."""
    india = (pat.phone or "").startswith("+91")
    currency, scale = ("INR", 1) if india else ("USD", 0.05)
    for days_ago, category, text, base in ((12, "consultation", "Doctor consultation", 800),
                                           (40, "lab_test", "Blood tests", 1500),
                                           (45, "medicine", "Pharmacy purchase", 1200)):
        db.add(Expense(patient_id=pat.id, created_by=creator.id, category=category, description=text, currency=currency,
                       expense_date=(dt.date.today() - dt.timedelta(days=days_ago)).isoformat(),
                       amount_minor=round(base * scale * rng.uniform(0.8, 1.5)) * 100))
    db.commit()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--synth", default=os.path.join(os.path.dirname(__file__), "..", "tools", "synth", "output"))
    ap.add_argument("--reset", action="store_true")
    ap.add_argument("--patients", type=int, help="only seed the first N patients")
    ap.add_argument("--pending-ratio", type=float, default=0.3, help="share of documents left 'pending_review'")
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()

    root = os.path.abspath(a.synth)
    if not os.path.exists(os.path.join(root, "patients.json")):
        raise SystemExit(f"No synthetic data in {root}. Run tools/synth/generate.py first.")
    if a.reset:
        Base.metadata.drop_all(bind=engine)
    init_db()
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    rng = random.Random(a.seed)

    db = SessionLocal()
    if db.query(Patient).count() and not a.reset:
        raise SystemExit("Database already has patients. Use --reset to replace them.")

    # ── demo accounts ─────────────────────────────────────────────────────────────────────────
    # One shared random password, written to a git-ignored file (never printed or committed).
    # Override with DEMO_PASSWORD. Layout shows every role and isolation between accounts:
    #   owner@   owns patients 1-16        doctor@  read-only on 1-3        family@  can edit 1-2
    #   outsider@ owns 17-20 and sees nothing of the others
    password = _os.getenv("DEMO_PASSWORD") or "-".join(secrets.token_urlsafe(6) for _ in range(3))
    users = {}
    for key, name in (("owner", "Demo Owner"), ("doctor", "Dr. Demo"), ("family", "Demo Family"), ("outsider", "Demo Outsider")):
        u = User(email=f"{key}@example.com", name=name, password_hash=auth.hash_password(password),
                 email_verified_at=dt.datetime.utcnow())
        db.add(u)
        users[key] = u
    db.commit()
    creds = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), ".demo_credentials")
    with open(creds, "w", encoding="utf-8") as f:
        f.write("Demo accounts (local development only). All use the same password.\n")
        f.write("\n".join(u.email for u in users.values()) + f"\npassword: {password}\n")

    def grant(user_key, patient_id, role):
        db.add(PatientAccess(user_id=users[user_key].id, patient_id=patient_id, role=role))

    profiles = json.load(open(os.path.join(root, "patients.json"), encoding="utf-8"))
    if a.patients:
        profiles = profiles[: a.patients]
    n_docs = 0
    for p in profiles:
        first = p["name"].split()[0].lower()
        last = p["name"].split()[-1].lower()
        pat = Patient(name=p["name"], age=p["age"], gender="Male" if p["sex"] == "M" else "Female",
                      blood_group=rng.choice(BLOOD), phone=p["phone"], email=f"{first}.{last}@example.com")
        db.add(pat)
        db.commit()
        db.refresh(pat)
        grant("outsider" if pat.id >= 17 else "owner", pat.id, "owner")
        if pat.id <= 3:
            grant("doctor", pat.id, "viewer")
        if pat.id <= 2:
            grant("family", pat.id, "editor")
        db.commit()
        # chronological so newer prescriptions supersede older ones
        recs = [json.load(open(os.path.join(root, "truth", f"{d}.json"), encoding="utf-8")) for d in p["documents"]]
        for rec in sorted(recs, key=lambda r: r["expected"]["document_date"]):
            raw = copy.deepcopy(rec["expected"])
            raw["confidence"] = round(rng.uniform(0.82, 0.97), 2)
            for row in raw["medications"] + raw["lab_results"]:
                row["confidence"] = round(rng.uniform(0.8, 0.99), 2)
            extracted = postprocess(raw)

            src = os.path.join(root, "documents", rec["files"][0])
            ext = os.path.splitext(src)[1]
            dest = os.path.join(UPLOAD_DIR, f"{uuid.uuid4().hex}{ext}")
            shutil.copy(src, dest)

            pending = extracted["needs_review"] or rng.random() < a.pending_ratio
            doc = MedicalDocument(
                patient_id=pat.id, filename=rec["files"][0], file_path=dest, category=extracted["category"],
                document_date=extracted["document_date"], hospital=extracted["hospital"], doctor=extracted["doctor"],
                upload_date=dt.datetime.fromisoformat(extracted["document_date"]) + dt.timedelta(hours=10),
                extracted_data=extracted, validation_status="pending_review" if pending else "verified",
                processing_status="done")
            db.add(doc)
            db.commit()
            db.refresh(doc)
            persist_extraction(db, doc, extracted)
            n_docs += 1
        n_appt, n_rem = seed_schedule(db, pat, users["owner"] if pat.id < 17 else users["outsider"], rng)
        seed_expenses(db, pat, users["owner"] if pat.id < 17 else users["outsider"], rng)
        print(f"  {pat.id:2d}. {pat.name:24s} {len(recs)} documents, {n_appt} appointments, {n_rem} reminders"
              f"  ({', '.join(p['conditions'])})")
    db.close()
    print(f"\nSeeded {len(profiles)} patients, {n_docs} documents into {engine.url}")
    print(f"Demo logins: owner@ / doctor@ / family@ / outsider@example.com. Password is in {creds} (git-ignored).")


if __name__ == "__main__":
    main()
