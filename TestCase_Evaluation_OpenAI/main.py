"""
main.py — FastAPI backend for CEV Rules Test Portal
"""
import asyncio
import json
import os
import shutil
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional

from fastapi import FastAPI, Request, UploadFile, File, Form, HTTPException
from fastapi.responses import (
    HTMLResponse, JSONResponse, FileResponse, StreamingResponse
)
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from config import settings
from vector_store import RulesVectorStore
from mock_api import execute_request
from excel_reporter import generate_excel_report, compute_summary_stats

# ── Startup: clear vector DB if configured ──
settings.ensure_dirs()
if settings.CLEAR_DB_ON_STARTUP:
    settings.clear_vector_store()

app = FastAPI(title="CEV Rules Test Portal", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="static"), name="static")

# ── In-memory session store ──
# Each session_id maps to: { vector_store, results, excel_path, status, logs }
_sessions: Dict[str, Dict[str, Any]] = {}
_pipeline_threads: Dict[str, threading.Thread] = {}


def get_or_create_session(session_id: str) -> Dict[str, Any]:
    if session_id not in _sessions:
        _sessions[session_id] = {
            "vector_store": None,
            "rules_indexed": False,
            "results": None,
            "excel_path": None,
            "pipeline_status": "idle",   # idle | running | done | error
            "pipeline_logs": [],
            "pipeline_pct": 0,
            "sample_request": None,
            "sample_response": None,
        }
    return _sessions[session_id]


def clear_session_vector_store(session_id: str):
    """Wipe FAISS data for a session and rebuild a fresh store instance."""
    sess = get_or_create_session(session_id)
    store_path = f"{settings.FAISS_STORE_PATH}/{session_id}"
    if Path(store_path).exists():
        shutil.rmtree(store_path)
    Path(store_path).mkdir(parents=True, exist_ok=True)
    sess["vector_store"] = RulesVectorStore(store_path=store_path)
    sess["rules_indexed"] = False


# ──────────────────────────────────────────────
# HTML Page
# ──────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index():
    html_path = Path("templates/index.html")
    return HTMLResponse(html_path.read_text(encoding="utf-8"))


# ──────────────────────────────────────────────
# Session endpoints
# ──────────────────────────────────────────────

@app.post("/api/session/new")
async def new_session():
    """Create a new session — clears any prior FAISS data for that ID."""
    session_id = str(uuid.uuid4())
    clear_session_vector_store(session_id)
    return {"session_id": session_id}


@app.delete("/api/session/{session_id}")
async def close_session(session_id: str):
    """Clean up session data and FAISS store."""
    store_path = f"{settings.FAISS_STORE_PATH}/{session_id}"
    if Path(store_path).exists():
        shutil.rmtree(store_path)
    _sessions.pop(session_id, None)
    return {"status": "cleared"}


# ──────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────

@app.get("/api/config")
async def get_config():
    """Return non-sensitive config values to the UI."""
    return {
        "model": settings.OPENAI_MODEL,
        "api_key_set": bool(settings.OPENAI_API_KEY and not settings.OPENAI_API_KEY.startswith("sk-your")),
        "clear_db_on_startup": settings.CLEAR_DB_ON_STARTUP,
    }


# ──────────────────────────────────────────────
# Rules / Vector Store
# ──────────────────────────────────────────────

@app.post("/api/rules/index")
async def index_rules(request: Request):
    body = await request.json()
    session_id = body.get("session_id")
    rules_text = body.get("rules_text", "").strip()
    sample_request = body.get("sample_request")
    sample_response = body.get("sample_response")

    if not session_id:
        raise HTTPException(400, "session_id required")
    if not rules_text:
        raise HTTPException(400, "rules_text required")

    sess = get_or_create_session(session_id)

    # Always clear and rebuild — replaces old content
    clear_session_vector_store(session_id)
    sess["sample_request"] = sample_request
    sess["sample_response"] = sample_response

    vs = sess["vector_store"]
    count = vs.build_index(rules_text)
    sess["rules_indexed"] = True

    return {"status": "indexed", "chunks": count, "message": f"Indexed {count} rule chunks into FAISS"}


@app.get("/api/rules/search")
async def search_rules(session_id: str, query: str, top_k: int = 3):
    sess = get_or_create_session(session_id)
    vs = sess.get("vector_store")
    if not vs or not vs.is_ready():
        raise HTTPException(400, "Rules not indexed yet")
    results = vs.search(query, top_k=top_k)
    return {"results": results}


@app.get("/api/rules/status")
async def rules_status(session_id: str):
    sess = get_or_create_session(session_id)
    return {"indexed": sess.get("rules_indexed", False)}


# ──────────────────────────────────────────────
# Manual API Tester
# ──────────────────────────────────────────────

@app.post("/api/execute")
async def manual_execute(request: Request):
    body = await request.json()
    req_payload = body.get("request", {})
    response = execute_request(req_payload)
    return {"request": req_payload, "response": response}


# ──────────────────────────────────────────────
# Pipeline — background thread + SSE stream
# ──────────────────────────────────────────────

def _run_pipeline_thread(session_id: str):
    """Background thread: runs the full CrewAI pipeline."""
    sess = _sessions[session_id]
    sess["pipeline_status"] = "running"
    sess["pipeline_logs"] = []
    sess["pipeline_pct"] = 0
    sess["results"] = None
    sess["excel_path"] = None

    def log(msg: str, pct: int):
        ts = datetime.now().strftime("%H:%M:%S")
        sess["pipeline_logs"].append({"ts": ts, "msg": msg, "pct": pct})
        sess["pipeline_pct"] = pct

    try:
        # Validate config
        errors = settings.validate()
        if errors:
            raise ValueError(f"Config errors: {'; '.join(errors)}")

        vs = sess.get("vector_store")
        if not vs or not vs.is_ready():
            raise ValueError("Rules must be indexed before running pipeline")

        sample_req = sess.get("sample_request", {})
        sample_resp = sess.get("sample_response", {})

        from agents import run_test_pipeline
        results = run_test_pipeline(
            vector_store=vs,
            sample_request=sample_req,
            sample_response=sample_resp,
            progress_callback=log,
        )

        # Generate Excel
        log("Generating Excel report...", 97)
        Path(settings.OUTPUT_DIR).mkdir(parents=True, exist_ok=True)
        fname = f"test_report_{session_id[:8]}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        excel_path = str(Path(settings.OUTPUT_DIR) / fname)
        generate_excel_report(results, excel_path)

        sess["results"] = results
        sess["excel_path"] = excel_path
        log(f"Pipeline complete — {len(results)} test cases", 100)
        sess["pipeline_status"] = "done"

    except Exception as e:
        sess["pipeline_logs"].append({"ts": datetime.now().strftime("%H:%M:%S"), "msg": f"ERROR: {e}", "pct": 0})
        sess["pipeline_status"] = "error"


@app.post("/api/pipeline/start")
async def start_pipeline(request: Request):
    body = await request.json()
    session_id = body.get("session_id")
    if not session_id:
        raise HTTPException(400, "session_id required")

    sess = get_or_create_session(session_id)
    if sess["pipeline_status"] == "running":
        raise HTTPException(409, "Pipeline already running")

    sess["pipeline_status"] = "running"
    t = threading.Thread(target=_run_pipeline_thread, args=(session_id,), daemon=True)
    _pipeline_threads[session_id] = t
    t.start()
    return {"status": "started"}


@app.get("/api/pipeline/stream/{session_id}")
async def pipeline_stream(session_id: str):
    """SSE endpoint — streams logs and progress to the browser."""
    async def event_generator():
        sent = 0
        while True:
            sess = _sessions.get(session_id)
            if not sess:
                yield f"data: {json.dumps({'error': 'session not found'})}\n\n"
                break

            logs = sess.get("pipeline_logs", [])
            # Send any new log entries
            while sent < len(logs):
                entry = logs[sent]
                yield f"data: {json.dumps(entry)}\n\n"
                sent += 1

            status = sess.get("pipeline_status", "idle")
            if status in ("done", "error"):
                yield f"data: {json.dumps({'done': True, 'status': status})}\n\n"
                break

            await asyncio.sleep(0.5)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.get("/api/pipeline/status/{session_id}")
async def pipeline_status(session_id: str):
    sess = get_or_create_session(session_id)
    return {
        "status": sess["pipeline_status"],
        "pct": sess["pipeline_pct"],
        "has_results": sess["results"] is not None,
    }


# ──────────────────────────────────────────────
# Results
# ──────────────────────────────────────────────

@app.get("/api/results/{session_id}")
async def get_results(session_id: str):
    sess = get_or_create_session(session_id)
    results = sess.get("results")
    if results is None:
        raise HTTPException(404, "No results yet")

    stats = compute_summary_stats(results)
    return {"results": results, "stats": stats}


@app.get("/api/results/{session_id}/download")
async def download_excel(session_id: str):
    sess = get_or_create_session(session_id)
    excel_path = sess.get("excel_path")
    if not excel_path or not Path(excel_path).exists():
        raise HTTPException(404, "Excel report not found")
    fname = Path(excel_path).name
    return FileResponse(
        excel_path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=fname,
    )


# ──────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=settings.HOST, port=settings.PORT, reload=True)
