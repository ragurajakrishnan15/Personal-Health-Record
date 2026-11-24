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
from database import (Base, MedicalDocument, Patient, PatientAccess, SessionLocal, UPLOAD_DIR, User, engine, init_db)
from persistence import persist_extraction

BLOOD = ["A+", "A-", "B+", "B-", "O+", "O-", "AB+", "AB-"]


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
        print(f"  {pat.id:2d}. {pat.name:24s} {len(recs)} documents  ({', '.join(p['conditions'])})")
    db.close()
    print(f"\nSeeded {len(profiles)} patients, {n_docs} documents into {engine.url}")
    print(f"Demo logins: owner@ / doctor@ / family@ / outsider@example.com. Password is in {creds} (git-ignored).")


if __name__ == "__main__":
    main()
