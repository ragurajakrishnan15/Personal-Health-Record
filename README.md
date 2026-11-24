# HealthVault — Personal & Family Health Records Platform

AI-powered personal and family health records: upload documents, get structured data, medication and lab trends, appointments, reminders and a grounded AI chat.

See `HANDOFF.md` for the current state, design decisions and known limits.

## Quick Start

### Backend (FastAPI)

```bash
cd backend
pip install -r requirements.txt
cp .env.example .env        # Add GEMINI_API_KEY / GROQ_API_KEY
python -m uvicorn main:app --port 8000   # http://localhost:8000 (localhost only)
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
│   ├── ai_service.py        # Gemini/Groq extraction
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
│   │   │   ├── Appointments.jsx  # Appointments + follow-up suggestions
│   │   │   ├── Reminders.jsx     # Reminders (one-off or repeating)
│   │   │   └── SettingsPage.jsx  # Settings (stub)
│   │   └── services/
│   │       └── api.js       # Axios API client
│   └── vite.config.js
└── uploads/                 # Uploaded documents
```
