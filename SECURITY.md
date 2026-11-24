# Security notes

## What is enforced
- **Login required everywhere.** `auth.guard` is a global dependency: every API route needs a session except
  `POST /api/auth/login`, `POST /api/auth/register` and `GET /api/health`. A test sweeps all routes and fails if a new
  one is left open.
- **Per-patient roles** (`viewer` < `editor` < `owner`) from the URL (`patient_id`, `doc_id`, `med_id`) or the chat
  request body. A patient you cannot access answers **404**, the same as one that does not exist.
- **Passwords:** scrypt with per-user salt; minimum 10 characters; common/short passwords rejected.
- **Sessions:** random token in an `HttpOnly`, `SameSite=Lax` cookie (`Secure` when `COOKIE_SECURE=true`); only a SHA-256 of
  it is stored; sliding 7-day idle expiry, 30-day maximum; revoked on logout and on password change.
- **Brute force:** per-IP and per-account throttling, and a 15-minute lock after 5 failures. Failures all return the
  same message, and unknown accounts cost the same time as wrong passwords.
- **Web:** cross-site writes are rejected (Origin check on top of SameSite), CORS limited to `CORS_ORIGINS`,
  `nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, `Cache-Control: no-store` on `/api`.
- **Files:** uploads get random names and are only served through an authorised endpoint (never statically).
- **Audit log** of logins, failures, denied access, uploads, views, reviews and sharing changes. It stores no record
  contents, chat text, passwords or tokens.
- **Privacy of conversations:** chat history is private to each user, even on a shared patient.

## Email verification and password reset
- One-time links: 256-bit random token, stored only as a SHA-256 hash, single use (atomic), newer link replaces older,
  verify expires in 24 h, reset in 30 min. Tokens travel in the URL fragment, so servers and logs never see them.
- "Forgot password" answers identically for known and unknown emails and is rate limited per IP and per address.
- A reset signs out every device, clears any lockout, marks the email verified, and sends a "password changed" notice.
  A too-weak new password does not consume the link.
- Unverified accounts can sign in, but owners cannot share records with them (stops someone registering another
  person's address to receive shared records).
- Mail: set `SMTP_HOST` (+ `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `MAIL_FROM`, `FRONTEND_URL`) to deliver. Without
  `SMTP_HOST`, messages are written to `backend/.outbox/` (git-ignored) and nothing is sent.

## Export and deletion
- Owner only (viewers and editors get 403, people without access get 404). Export is rate limited (5/hour).
- Export = one ZIP: `patient.json`, CSVs (formula-injection neutralised), the original files, and only the requester's
  own chat. No server paths and no patient name in the download filename.
- Deletion is permanent: requires the exact patient name and the owner's password (throttled, failures audited),
  refuses while a document is still being processed, removes all rows and uploaded files (only ever inside the upload
  folder), and revokes everyone's access. The audit log keeps ids and counts only.
- Not covered: backups/snapshots of the database or disk (purge them per your retention policy), copies a user already
  downloaded, and text already sent to the AI provider.

## Production checklist (not done by the code alone)
- Configure SMTP and `FRONTEND_URL` (the host used in emailed links), otherwise reset/verify emails stay in the dev outbox.
- Serve over HTTPS and set `COOKIE_SECURE=true`, `CORS_ORIGINS=<your site>`; consider `ALLOW_REGISTRATION=false`.
- The login throttle is in-memory (per process). Behind several workers use a shared limiter (Redis / the platform).
- Encrypt the database and uploaded files at rest (disk or object-store encryption); the app does not do this itself.
- Questions and record summaries are sent to the configured AI provider (Gemini / Groq). Use a paid tier with a
  no-training policy, or a local model, before real patient data.
- Not implemented yet: two-factor authentication, time-limited share links,
  audit-log viewing UI, account (user) deletion, per-user rate limits on uploads.
- Compliance (HIPAA, India DPDP, GDPR) needs a legal review; this code is a technical foundation, not a certification.
