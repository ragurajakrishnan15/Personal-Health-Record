# HealthVault deployment plan

Status: plan only. Nothing here has been run. Verify each step against the code.

## 0. Gate: do not put real patient data online until these are done
1. **AI provider privacy.** Record text goes to Gemini/Groq. Move to a paid, no-training tier (or a local model) and get that in writing.
2. **Encryption at rest** for the database and uploaded files (managed Postgres + encrypted disk/object store).
3. **HTTPS only** and `COOKIE_SECURE=true`.
4. **Legal review** (HIPAA / India DPDP / GDPR as applicable). The code is a foundation, not a certification.
Until then, deploy only the synthetic demo data (a staging/demo environment).

## 1. Target architecture (recommended)
| Piece | Choice | Why |
|---|---|---|
| Frontend | Static site (Vite build `frontend/dist`) on Vercel, Render Static, or Netlify | Cheap, CDN, HTTPS free |
| Backend | FastAPI in Docker, 1 web service, `uvicorn main:app --host 0.0.0.0 --port $PORT` (no `--reload`) | `python main.py` has `reload=True`; do not use it |
| Database | Managed **Postgres** (replace SQLite) | SQLite on an ephemeral container disk loses data |
| Files | Object storage (S3/R2) or a persistent disk | `uploads/` must survive redeploys |
| Email | SMTP provider (Resend, SES, etc.) | Without `SMTP_HOST` mail only goes to `.outbox/` |
| Domain | One domain, e.g. `app.example.com` (frontend) + `api.example.com` or same-origin `/api` proxy | Cookies are SameSite=Lax, so same-site is required |

Simplest path: a single Render project (web service + Postgres + persistent disk + static site). Cheapest path: one VPS with Docker Compose + Caddy (auto HTTPS).

## 2. Code changes needed first
1. **Postgres support.** `DATABASE_URL` already exists. Add `psycopg[binary]` to requirements and test on Postgres.
2. **Alembic.** Replace the `_add_missing_columns` auto-migration in `database.py` (adds columns only).
3. **Dockerfile** for the backend (python 3.11-slim, non-root user, `pip install -r requirements.txt`).
4. **Frontend API base.** `vite.config.js` proxies `/api` in dev only. In production either serve both behind one domain with `/api` reverse proxy, or add a `VITE_API_URL` and set CORS.
5. **Shared rate limiter.** Login/reset throttles are in memory. Run one worker, or move to Redis.
6. **Background jobs.** The nightly medication recompute runs inside the app process; with several instances it runs on each. Use one instance, or a cron (`python manage.py recompute-meds`).
7. **Upload storage abstraction** if moving to S3 (currently local paths under `UPLOAD_DIR`).
8. Fix `main.py:535` (`0.0.0.0`, `reload=True`) or remove that block.
9. CI: run `pytest` and `vite build` on every push.

## 3. Environment variables (production)
`DATABASE_URL`, `UPLOAD_DIR`, `GEMINI_API_KEY`, `GROQ_API_KEY`, `GEMINI_MODEL`, `GROQ_MODEL`,
`COOKIE_SECURE=true`, `CORS_ORIGINS=https://app.example.com`, `ALLOW_REGISTRATION=false` (or true if public),
`FRONTEND_URL=https://app.example.com`, `SMTP_HOST/PORT/USER/PASSWORD/SSL`, `MAIL_FROM`,
`SESSION_IDLE_DAYS`, `SESSION_MAX_DAYS`, `STATUS_RECOMPUTE_HOURS`.
Store these in the host's secret manager. Never commit `.env`. Rotate the API keys if they have ever been shared or pasted anywhere.

## 4. Data migration (current local data -> production)
Backup already taken: `D:\phr-extract\backups\healthvault-2026-11-24(.zip)` (SQLite DB + 661 uploads).
Contents are **synthetic demo data** (21 patients, 161 documents, 95 medications, 935 lab results, 5 users).
- For a demo environment: re-run `python seed.py --reset --synth ../tools/synth/output_demo` against the new database. That is simpler than migrating SQLite rows.
- For real data later: write a one-off script (SQLAlchemy read from SQLite, write to Postgres), copy `uploads/` to the new store, then check row counts and a few documents by eye.
- Do not seed demo users with the shared demo password in a public environment. Create real accounts with `manage.py create-user`.

## 5. Rollout steps
1. Create Postgres + persistent storage + secrets.
2. Build/push the Docker image; deploy the backend; run migrations.
3. Deploy the frontend; point DNS; confirm HTTPS.
4. Smoke test: `/api/health`, register, verify email, login, upload a sample, view timeline/medications, chat, export, delete.
5. Create the first owner account; disable open registration if private.
6. Turn on monitoring (uptime check on `/api/health`, error alerts) and daily DB backups with a retention rule.

## 6. Operations
- Backups: daily DB dump + object-store versioning; test a restore once.
- Logs: never log record text or tokens (the audit log already stores ids only).
- Updates: dependency scan, rebuild monthly.
- Cost watch: AI calls are per upload and per chat message; set provider spend limits.

## 7. Open decisions for you
1. Demo only, or real family data? (decides how strict section 0 is)
2. Host: Render all-in-one, Vercel + Render, or a VPS?
3. Keep Gemini/Groq on a paid tier, or move to a local model?
