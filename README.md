# HealthVault — Personal & Family Health Records Platform

AI-powered health record management demo for doctors.

## Quick Start

### Backend (FastAPI)

```bash
cd backend
pip install -r requirements.txt
cp .env.example .env        # Add your GEMINI_API_KEY
python main.py               # Runs on http://localhost:8000
```

### Frontend (React + Vite)

```bash
cd frontend
npm install --legacy-peer-deps
npm run dev                  # Runs on http://localhost:5173
```

The frontend proxies `/api` requests to the backend at `:8000`.

## Project Structure

```
health-records-demo/
├── backend/
│   ├── main.py              # FastAPI app — all API routes
│   ├── database.py          # SQLAlchemy models (SQLite)
│   ├── ai_service.py        # Gemini AI extraction + chat (TODO)
│   ├── requirements.txt
│   └── .env.example
├── frontend/
│   ├── src/
│   │   ├── App.jsx          # Router + layout
│   │   ├── App.css          # All styles
│   │   ├── components/
│   │   │   ├── Sidebar.jsx  # Navigation sidebar
│   │   │   └── Header.jsx   # Top bar
│   │   ├── pages/
│   │   │   ├── Dashboard.jsx     # Health overview
│   │   │   ├── Patients.jsx      # Family member management
│   │   │   ├── Records.jsx       # Medical records browser
│   │   │   ├── Upload.jsx        # Document upload + AI extraction
│   │   │   ├── Medications.jsx   # Medication tracker
│   │   │   ├── Analytics.jsx     # Health trends & charts
│   │   │   ├── Chat.jsx          # AI health assistant
│   │   │   ├── Appointments.jsx  # Appointments (stub)
│   │   │   ├── Reminders.jsx     # Reminders (stub)
│   │   │   └── SettingsPage.jsx  # Settings (stub)
│   │   └── services/
│   │       └── api.js       # Axios API client
│   └── vite.config.js
└── uploads/                 # Uploaded documents
```

## What's Built (Skeleton)

- ✅ Full page routing (10 pages)
- ✅ Sidebar navigation with active states
- ✅ FastAPI backend with all CRUD endpoints
- ✅ SQLAlchemy models for all entities
- ✅ Document upload endpoint with AI extraction hook
- ✅ Chat endpoint with RAG hook
- ✅ API service layer on frontend
- ✅ Upload page with file picker + extraction result display
- ✅ Chat page with message UI + suggested questions

## What to Build Next (Claude Code)

1. **AI Extraction** (`ai_service.py`) — Wire up Gemini vision API to extract structured data from medical documents
2. **AI Chat** (`ai_service.py`) — RAG pipeline: gather patient context → Gemini → grounded response
3. **Dashboard** — Fetch real health summary, wire up stat cards
4. **Records** — Document validation UI (side-by-side original + extracted)
5. **Analytics** — Chart library (Recharts/Chart.js) for lab parameter trends
6. **Medications** — Auto-populate from extraction, status management
7. **Family Management** — Add patient form, role assignment
8. **Reminders** — Medication schedule + adherence tracking
9. **Demo Data** — Seed script with sample patient + records for doctor demo
