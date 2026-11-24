# HealthVault - project handoff

Written at the end of a long working session so the next session can start from facts, not memory.
**Rule for the next session: verify anything below against the code before relying on it** (commands in section 9).
Where something was *not* tested, this file says so.

Project root: `D:\phr-extract\health-records-demo` (not a git repository - there is no history to fall back on).
Platform: Windows 11. Python 3.11 (system, no venv). Node + Vite.

---------------------------------------------------------------------------------------------------------------

## 1. What this is

A personal/family health-records app. Upload medical documents (prescriptions, lab reports, discharge summaries) ->
AI reads them into structured data -> medication list, lab trends, timeline, and a grounded AI chat about the records.
The starting point was a skeleton cloned from `github.com/ragurajakrishnan15/Personal-Health-Record`; almost everything
below was built on top of it in this session.

Stack: FastAPI + SQLAlchemy 2 + SQLite (`backend/health_records.db`) | React 19 + Vite (+ Recharts, axios, lucide-react).
AI: Gemini (google-genai) and Groq only. Decision made: **no NVIDIA / no local model** for now.

## 2. What exists (built and tested)

| Area | State | Main files |
|---|---|---|
| Synthetic document generator (US + India formats, with noise/degradation, answer keys) | done | `tools/synth/` |
| AI extraction (vision -> JSON), Gemini first, fallback models, then Groq | done | `backend/ai_service.py` |
| Extraction evaluator (scores vs answer keys) | done | `backend/evaluate.py` |
| Persistence into relational rows, background processing, seed | done | `backend/persistence.py`, `main.py`, `seed.py` |
| UI wired to real API (records, upload, medications, dashboard) | done | `frontend/src/pages/*` |
| Generic-name safety (printed vs inferred, "verify" tag, confidence cap 0.75) | done | `ai_service.py`, `GenericTag.jsx` |
| Analytics charts for lab trends | done | `Analytics.jsx`, `TrendChart.jsx`, `lib/labs.js` |
| AI chat (RAG over the DB, `[S#]` citations, safety rules) + chat eval | done | `chat_context.py`, `chat_service.py`, `chat_eval.py`, `Chat.jsx` |
| Auth + access control (roles, sessions, lockout, audit, CSRF/CORS/headers, sharing UI) | done | `auth.py`, `auth_routes.py`, `Login.jsx`, `Patients.jsx` |
| Medication status rule fix (`lapsed`) + nightly recompute | done | `persistence.py`, `main.py` |
| Email verification + password reset | done (API tested; UI not browser-tested) | `account_routes.py`, `mailer.py`, `AccountLinks.jsx`, `VerifyBanner.jsx` |
| Patient export (ZIP) + permanent deletion | done (API tested live; UI not browser-tested) | `patient_data.py`, `Patients.jsx` |

**Tests: 74 passing** (`backend/tests/`: `test_pipeline.py`, `test_auth.py`, `test_account.py`, `test_patient_data.py`).
Frontend build passes (`npx vite build`). Several security tests were "mutation checked": the protection was removed on
purpose and tests were confirmed to fail, then the code restored.

### Not tested in a real browser (only API/tests/build)
These were verified by tests and HTTP calls, but nobody has clicked through them yet:
- Forgot-password form on the sign-in page, the `/reset-password` page, the `/verify-email` page, the verification banner.
- Export / Delete buttons and the delete panel on the Family page.
- The "To confirm" (lapsed) tab on the Medications page.
Earlier UI work (login, role-aware UI, sharing panel, charts, chat) *was* checked in the browser.

## 3. How to run it

Backend (from `backend/`), port 8000:
```
python -m uvicorn main:app --port 8000          # binds 127.0.0.1 only
```
NOTE: `python main.py` runs uvicorn with `host="0.0.0.0", reload=True` (listens on ALL interfaces). Prefer the line above.

Frontend (from `frontend/`), port 5173 (proxies `/api` -> 8000):
```
npx vite
```
Tests (from `backend/`):  `python -m pytest tests -q`   (pytest is not listed in `requirements.txt`; it is installed locally)
Build check (from `frontend/`):  `npx vite build`

At the time of writing, **both servers were still running** (started by me). Stop only those two processes
(find the PID with `netstat -ano | findstr :8000` and `:5173`). Do NOT use `taskkill /IM node.exe` (a broad kill was
denied earlier and should not be worked around).

### Demo data and accounts
- Seed: `python seed.py --reset --synth ../tools/synth/output_demo` (from `backend/`). It wipes and rebuilds the DB:
  20 patients, 160 documents, 4 demo users.
- Demo users: `owner@example.com` (owns patients 1-16), `doctor@example.com` (viewer on 1-3),
  `family@example.com` (editor on 1-2), `outsider@example.com` (owns 17-20). All have the same random password,
  written to `backend/.demo_credentials` (git-ignored). Read it from that file; it is not repeated here.
- If you re-seed, the medication statuses are recomputed by the seed/persist code; the earlier one-off conversion of
  "completed" -> "lapsed" rows was done directly on the DB and is not needed after a fresh seed.
- `backend/.outbox/` is where "emails" go in development (see section 6). It is git-ignored and does not exist until the first email is sent.

### Environment variables (names only - values live in `backend/.env`, never commit it)
`GEMINI_API_KEY`, `GROQ_API_KEY`, `GEMINI_MODEL`, `GROQ_MODEL`, `GEMINI_RPM`, `GROQ_RPM`, `LLM_CALL_TIMEOUT`,
`DATABASE_URL`, `UPLOAD_DIR`, `COOKIE_SECURE`, `ALLOW_REGISTRATION`, `CORS_ORIGINS`, `SESSION_IDLE_DAYS`,
`SESSION_MAX_DAYS`, `STATUS_RECOMPUTE_HOURS` (0 = off), `FRONTEND_URL`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`,
`SMTP_PASSWORD`, `SMTP_SSL`, `MAIL_FROM`, `MAIL_BACKEND` (`memory` = tests).
API keys for Gemini and Groq are in `backend/.env` (the user supplied them). `.env.example` is a key-less template.

## 4. Key design decisions (so you don't re-litigate them)

**AI**
- Models in use when last checked: Gemini default `gemini-3.5-flash-lite`, fallbacks `gemini-3.5-flash`,
  `gemini-3.1-flash-lite`; Groq `qwen/qwen3.8-27b` (vision-capable). Model availability changes - if a call 404s,
  the model was probably retired; re-check rather than assume.
- Chain: Gemini -> other Gemini models -> Groq, with rate limiting, 429/503-aware backoff, 90 s per-call timeout.
- Extraction output goes through `postprocess()` (normalises dates/frequency/route/generic name/dosage, computes abnormal
  flags from the printed range, sets `needs_review`). Extraction never raises; failures are recorded on the document.
- **Generic-name safety:** if the generic drug name was inferred from a brand (not printed), it is flagged
  `generic_inferred`, confidence capped at 0.75, and the UI shows a "verify" tag.
- **Unknown vs normal:** `LabResult.is_abnormal` is nullable. `None` = no reference range printed ("No reference
  range" in the UI), never silently "normal".
- Chat: answers only from the patient's records with `[S#]` citations; no diagnosis/dosing advice; resists prompt
  injection; emergency note; each user's chat history is private even on a shared patient.

**Medication status (rewritten this session)**
- `active`: supply not finished (courses >= 28 days get a 120-day refill window).
- `completed`: a short course that ended.
- `lapsed` (UI label "To confirm"): long-term course whose supply ran out, with no newer prescription on file.
  Deliberately NOT "completed" - we can't know it was stopped.
- `superseded`: replaced by a newer prescription of the same drug. `discontinued`: user pressed Stop.
- `status_manual` flag: set when a person presses Stop / "Still taking"; the nightly job leaves those alone.
- Nightly job: runs at server start then every `STATUS_RECOMPUTE_HOURS` (default 24) inside the app process;
  `python manage.py recompute-meds` runs it on demand. The status API accepts only `active` or `discontinued`.

**Auth / access**
- Passwords: scrypt. Sessions: random token in an HttpOnly SameSite=Lax cookie; only its SHA-256 is stored.
- `auth.guard` is a GLOBAL dependency = default deny. Public routes are exactly: login, register, health,
  verify-email, forgot-password, reset-password (a test pins this list on purpose).
- Roles per patient: viewer < editor < owner. A patient you can't access returns **404** (same as "doesn't exist").
- Lockout: 5 failures -> 15 min. Throttles are **in memory** (per process).
- Origin-check CSRF defence, CORS limited to `CORS_ORIGINS`, security headers, `no-store` on API responses.
- Audit log stores ids/actions only - never record text, chat text, passwords or tokens.
- Sharing: owner adds by email; target must already have an account **and a verified email**.
- Email tokens: 256-bit, hashed, single-use (atomic), verify 24 h / reset 30 min, carried in the URL `#fragment`.
- Reset signs out all devices, clears lockout, marks the email verified, and sends a "password changed" notice.
- Export/Delete: owner only. Delete needs exact patient name + password, is throttled/audited, refuses while a
  document is processing, and only deletes files inside the uploads folder.

## 5. Measured quality (as last measured - re-run before quoting)

- Extraction (Gemini): 100% on all scored fields for the 30 tuned documents; 30/30 on a fresh held-out batch
  (seed 7). Groq was clearly weaker (wrong brand->generic guesses). These are **synthetic** documents - real-world
  scans, handwriting and unfamiliar layouts have **not** been tested. Treat the numbers as a regression baseline,
  not as proof of real-world accuracy.
- Chat eval (rule-based checks): 33/33 on the tuned patients, 31/33 on the held-out ones; all safety checks passed.
- Datasets: `tools/synth/output` (seed 42, dev, 60 docs), `output_heldout` (seed 7), `output_demo`
  (seed 42 + 5 extra lab PDFs per patient = 160 docs; used for seeding). These folders are git-ignored/regenerable:
  `python tools/synth/generate.py --count N --seed S --out DIR [--region] [--mix] [--extra-labs N] [--clean]`.
- Eval cache lives in `backend/.eval_cache` (keeps repeated runs from re-spending API quota).

## 6. Things that behave in ways you might not expect

- **No real email is sent.** Without `SMTP_HOST`, messages are written to `backend/.outbox/*.txt`. To test the reset or
  verification flow by hand: trigger it in the UI, open the newest file in `.outbox`, copy the link.
  Links point at `FRONTEND_URL` (default `http://localhost:5173`).
- Existing demo users were marked verified. New sign-ups start unverified (banner shown; they can't be shared with).
  `python manage.py verify-user --email ...` verifies one by hand.
- Patients created before logins existed have no owner: `python manage.py claim-orphans --email <you>`.
- `manage.py` commands: create-user, list-users, grant, revoke, claim-orphans, deactivate, verify-user, recompute-meds.
- DB schema changes are applied by a tiny auto-migration (`_add_missing_columns` in `database.py`): it only adds simple
  columns. There is **no Alembic**. Renaming/removing columns or changing types will not work through it.
- Statuses are recomputed nightly only while the server is running and `STATUS_RECOMPUTE_HOURS > 0`.
- Tests use a temp DB and a guard that fails any test that would reach a real model, so `pytest` never spends quota.
- Recharts needed `react-is`, installed with `--legacy-peer-deps`; keep that flag if reinstalling.

## 7. Known limits / NOT done (be honest about these when planning)

Security / privacy
- **Record summaries go to Gemini/Groq on every chat question and during extraction.** Free tiers may train on data.
  Needs a paid no-training tier or a local model before any real patient data. Biggest privacy gap.
- No encryption at rest (DB or uploads). No HTTPS in dev (`COOKIE_SECURE` must be true behind HTTPS).
- Login/reset throttles are in-memory: with several workers they need Redis or a platform limiter.
- No two-factor authentication. No time-limited doctor share links. No audit-log viewer UI.
- No account (user) deletion - only patient deletion. No email change.
- Deletion cannot reach backups, already-downloaded exports, or text already sent to the AI provider.
- HIPAA / India DPDP / GDPR need a legal review; this is a technical foundation, not a certification.

Product
- Appointments, Reminders and Settings pages exist in the frontend as small stub pages (about 26 lines each); there are no backend models for appointments or reminders.
- No side-by-side review editor (reviewing is verify/reject only).
- Real-world robustness untested (see section 5).
- No Docker / Postgres / deploy setup / CI. `requirements.txt` does not include pytest.

Housekeeping
- Not a git repo. Consider `git init` and a first commit before further changes.
- `main.py` still uses deprecated `@app.on_event` (works; shows warnings).

## 8. Suggested next steps (none started; the user decides)

1. Browser-test the screens listed in section 2 ("Not tested in a real browser") and fix anything visual.
2. Account deletion + email change; time-limited doctor share links; two-factor sign-in; audit-log screen for owners.
3. Move to a no-training AI tier or a local model; try real (user-provided, consented) documents.
4. Appointments/reminders (follow-up dates are already extracted: `upcoming_followups` exists in health-summary).
5. Side-by-side review editor.
6. Deployment: HTTPS, Postgres + Alembic, Docker, shared rate limiter, encrypted storage, backups with retention.

An unexplained message "-+" arrived mid-session earlier and was never answered/clarified; ignore unless the user raises it.

## 9. Start-of-session verification checklist (run these before trusting anything above)

```
cd D:\phr-extract\health-records-demo\backend
python -m pytest tests -q                  # expect: 74 passed
cd ..\frontend && npx vite build           # expect: built
netstat -ano | findstr ":8000 :5173"       # are the servers still up?
curl http://localhost:8000/api/health      # {"status":"ok"}
```
Then confirm file layout: `backend/` has `account_routes.py auth.py auth_routes.py chat_context.py chat_service.py
database.py mailer.py main.py manage.py patient_data.py persistence.py seed.py evaluate.py chat_eval.py ai_service.py`.
If a count or file differs from this document, trust the code, and update this file.

## 10. Working tips for the assistant (learned the hard way)

- In the Bash tool, long heredocs containing apostrophes/quotes sometimes fail to parse and nothing runs. Write files with
  the Write/Edit tools, or put scripts in the scratchpad, instead of inline heredocs.
- Bash `/tmp` and Windows Python paths differ: a file written to `/tmp` by curl is not visible to `python -c` as
  `/tmp/...`. Use `unzip`/shell tools or real Windows paths.
- Use `python -m uvicorn main:app --port 8000` (localhost only) rather than `python main.py`.
- Never print the demo password or API keys into chat or docs; read them from `.demo_credentials` / `.env`.
- Do not mass-kill processes; stop only the PIDs you started.
- Prefer small, verified steps: run the tests and, for security rules, a mutation check (break the rule, see tests fail).
