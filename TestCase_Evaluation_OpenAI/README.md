# CEV Rules Test Portal v2 — FastAPI + HTML

## Quick Start

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. Configure `.env`
```env
OPENAI_API_KEY=sk-your-real-key-here
OPENAI_MODEL=gpt-4o-mini          # or gpt-4o, gpt-3.5-turbo
HOST=0.0.0.0
PORT=8000
FAISS_STORE_PATH=data/faiss_store  # per-session subdirs created here
CLEAR_DB_ON_STARTUP=true           # wipes all FAISS data on server restart
```

### 3. Run the server
```bash
python main.py
# or
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

### 4. Open browser
```
http://localhost:8000
```

---

## Session & Vector DB Lifecycle

| Event | What happens |
|---|---|
| Server startup | All FAISS data cleared (if `CLEAR_DB_ON_STARTUP=true`) |
| "New Session" button | New UUID session created, fresh FAISS store allocated |
| "Index Rules" button | **Replaces** existing FAISS content for that session |
| Browser tab close | Session and FAISS data cleaned up via `beforeunload` beacon |
| `/api/session/{id}` DELETE | Explicitly destroys session + FAISS store |

---

## API Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/` | Serves the HTML frontend |
| GET | `/api/config` | Returns model name, API key status |
| POST | `/api/session/new` | Creates new session, clears FAISS |
| DELETE | `/api/session/{id}` | Destroys session + FAISS store |
| POST | `/api/rules/index` | Indexes rules text into FAISS |
| GET | `/api/rules/search` | Semantic search over indexed rules |
| GET | `/api/rules/status` | Returns whether rules are indexed |
| POST | `/api/execute` | Manual single-request API test |
| POST | `/api/pipeline/start` | Starts CrewAI pipeline in background |
| GET | `/api/pipeline/stream/{id}` | SSE stream of pipeline logs |
| GET | `/api/pipeline/status/{id}` | Pipeline status + progress % |
| GET | `/api/results/{id}` | Full results + summary stats |
| GET | `/api/results/{id}/download` | Download Excel report |

---

## File Structure
```
portal_v2/
├── main.py              # FastAPI app, all API routes
├── config.py            # .env loader, settings object
├── agents.py            # CrewAI agents (reads key/model from config)
├── vector_store.py      # FAISS vector store
├── mock_api.py          # Rule-based mock API executor
├── excel_reporter.py    # 3-sheet Excel report generator
├── .env                 # ← Edit this with your keys
├── requirements.txt
├── templates/
│   └── index.html       # Full single-page HTML application
├── static/              # (reserved for future static assets)
├── data/faiss_store/    # Per-session FAISS indices
└── outputs/             # Generated Excel reports
```
