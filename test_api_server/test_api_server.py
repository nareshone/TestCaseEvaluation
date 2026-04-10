"""
test_api_server.py — Standalone CEV Rules Test API Server
==========================================================
Two POST endpoints implementing the same CEV exemption rules logic:

  POST /cev/drools/api/v1/rules          — open, no auth needed
  POST /cev/drools/api/v1/rules/secure   — bearer token is OPTIONAL
                                           (if a token is sent it must match,
                                            if no token is sent it still works)

Run:
    python test_api_server.py

Custom port / token:
    set API_PORT=9000 && set API_BEARER_TOKEN=my-secret && python test_api_server.py  (Windows)
    API_PORT=9000 API_BEARER_TOKEN=my-secret python test_api_server.py               (Mac/Linux)

Swagger UI (try it in browser):
    http://localhost:9000/docs
"""

import os
import traceback
from datetime import datetime, timedelta
from typing import Any, Dict, Optional, Tuple

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

# ── Config ───────────────────────────────────────────────────────────────────
# Render injects PORT; also support API_PORT for local dev. Fallback: 9000
API_PORT         = int(os.getenv("PORT") or os.getenv("API_PORT") or "9000")
API_HOST         = os.getenv("API_HOST", "0.0.0.0")
API_BEARER_TOKEN = os.getenv("API_BEARER_TOKEN", "test-bearer-token-123")

# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="CEV Rules — Test API Server",
    description=(
        "Standalone test server implementing CEV exemption rules.\n\n"
        "**Endpoint 1** `POST /cev/drools/api/v1/rules` — open, no auth.\n\n"
        "**Endpoint 2** `POST /cev/drools/api/v1/rules/secure` — bearer token "
        "is **optional**. If provided it must match; if omitted the request "
        "is still processed normally."
    ),
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Global exception handlers — always return JSON, never HTML ───────────────

@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "timestamp": datetime.now().isoformat(),
            "status": "ERROR",
            "exemptionStatus": None,
            "exemptionReason": str(exc.detail),
            "ruleFired": None,
        },
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={
            "timestamp": datetime.now().isoformat(),
            "status": "INVALID_DATA",
            "exemptionStatus": None,
            "exemptionReason": f"Request validation error: {exc}",
            "ruleFired": None,
        },
    )


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    traceback.print_exc()
    return JSONResponse(
        status_code=500,
        content={
            "timestamp": datetime.now().isoformat(),
            "status": "ERROR",
            "exemptionStatus": None,
            "exemptionReason": f"Internal server error: {str(exc)}",
            "ruleFired": None,
        },
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _ts() -> str:
    return datetime.now().isoformat()


def _error_response(reason: str, status: str = "ERROR") -> dict:
    return {
        "timestamp": _ts(),
        "status": status,
        "exemptionStatus": None,
        "exemptionReason": reason,
        "ruleFired": None,
    }


def _validate(body: dict) -> Optional[dict]:
    """Validate field types. Returns error dict if invalid, None if OK."""

    age = body.get("age")
    if age is not None and not isinstance(age, (int, float)):
        return _error_response(
            f"Invalid data type for age: expected number, "
            f"got {type(age).__name__} ({age!r})",
            "INVALID_DATA",
        )
    if isinstance(age, (int, float)) and age < 0:
        return _error_response(
            "Invalid value for age: age cannot be negative",
            "INVALID_DATA",
        )

    bool_fields = [
        "tanf", "snap", "caretakerOfChildUnder13",
        "incarcerationStatus", "formerInmate",
        "caretakerOfDisabledIndividualFlag",
    ]
    for field in bool_fields:
        val = body.get(field)
        if val is not None and not isinstance(val, bool):
            return _error_response(
                f"Invalid data type for {field}: expected boolean, "
                f"got {type(val).__name__} ({val!r})",
                "INVALID_DATA",
            )

    return None


def _apply_rules(body: dict) -> dict:
    """Apply CEV exemption rules in priority order."""
    ts  = _ts()
    age = body.get("age")

    # Rule 1 — TANF
    if body.get("tanf") is True:
        return {"timestamp": ts, "status": "SUCCESS",
                "exemptionStatus": "Exempt",
                "exemptionReason": "TANF Work Requirements Compliance",
                "ruleFired": "Rule 1: TANF"}

    # Rule 2 — SNAP
    if body.get("snap") is True:
        return {"timestamp": ts, "status": "SUCCESS",
                "exemptionStatus": "Exempt",
                "exemptionReason": "SNAP Household",
                "ruleFired": "Rule 2: SNAP"}

    # Rule 3 — Under 19
    if isinstance(age, (int, float)) and age < 19:
        return {"timestamp": ts, "status": "SUCCESS",
                "exemptionStatus": "Exempt",
                "exemptionReason": "Under 19",
                "ruleFired": "Rule 3: Under 19 Individual"}

    # Rule 4 — Former Inmate 3-month grace period
    if body.get("formerInmate") is True:
        release_str = body.get("releaseDate")
        det_str     = body.get("determinationDate")
        if release_str and det_str:
            try:
                release_dt   = datetime.fromisoformat(release_str)
                det_dt       = datetime.fromisoformat(det_str)
                window_start = det_dt - timedelta(days=90)
                if window_start <= release_dt <= det_dt:
                    return {"timestamp": ts, "status": "SUCCESS",
                            "exemptionStatus": "Exempt",
                            "exemptionReason": "Former Inmate - 3-month grace period",
                            "ruleFired": "Rule 4: Former Inmate Grace Period"}
            except ValueError:
                pass

    # Rule 5 — Child Caregiver
    if body.get("caretakerOfChildUnder13") is True:
        return {"timestamp": ts, "status": "SUCCESS",
                "exemptionStatus": "Exempt",
                "exemptionReason": "Child Caregiver",
                "ruleFired": "Rule 5: Child Caregiver"}

    # Rule 6 — Disabled Individual Caregiver
    if body.get("caretakerOfDisabledIndividualFlag") is True:
        return {"timestamp": ts, "status": "SUCCESS",
                "exemptionStatus": "Exempt",
                "exemptionReason": "Disabled Individual Caregiver",
                "ruleFired": "Rule 6: Disabled Individual Caregiver"}

    # No rule matched
    return {"timestamp": ts, "status": "SUCCESS",
            "exemptionStatus": "Not Exempt",
            "exemptionReason": "No exemption criteria met",
            "ruleFired": "None"}


def _process(body: dict) -> JSONResponse:
    """Validate + apply rules, always returns a JSONResponse."""
    error = _validate(body)
    if error:
        return JSONResponse(status_code=200, content=error)
    return JSONResponse(status_code=200, content=_apply_rules(body))


async def _parse_body(request: Request) -> Tuple[Optional[dict], Optional[JSONResponse]]:
    """
    Safely parse the JSON request body.
    Returns (body_dict, None) on success, or (None, error_response) on failure.
    """
    try:
        body = await request.json()
    except Exception:
        return None, JSONResponse(
            status_code=200,
            content=_error_response("Request body must be valid JSON", "ERROR"),
        )

    if not isinstance(body, dict):
        return None, JSONResponse(
            status_code=200,
            content=_error_response("Request body must be a JSON object {}", "ERROR"),
        )

    if "id" not in body:
        return None, JSONResponse(
            status_code=200,
            content=_error_response("Missing required field: id", "ERROR"),
        )

    return body, None


def _check_token(authorization: Optional[str]) -> Optional[JSONResponse]:
    """
    Validate bearer token if one was provided.
    - No Authorization header  →  OK  (token is optional)
    - Header present, wrong format  →  401
    - Header present, wrong token   →  403
    - Header present, correct token →  OK
    Returns None if allowed, or a JSONResponse error if rejected.
    """
    if not authorization:
        return None  # no token — allowed

    parts = authorization.strip().split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return JSONResponse(
            status_code=401,
            content=_error_response(
                "Invalid Authorization format. Expected: Bearer <token>", "ERROR"
            ),
        )

    if parts[1].strip() != API_BEARER_TOKEN:
        return JSONResponse(
            status_code=403,
            content=_error_response("Invalid or expired bearer token", "ERROR"),
        )

    return None  # token matches — allowed


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.post(
    "/cev/drools/api/v1/rules",
    summary="CEV Exemption Rules — Open (no auth required)",
    tags=["Open Endpoint"],
)
async def rules_open(request: Request):
    """
    Evaluate CEV exemption rules.
    **No authentication required.**
    """
    body, err = await _parse_body(request)
    if err:
        return err
    return _process(body)


@app.post(
    "/cev/drools/api/v1/rules/secure",
    summary="CEV Exemption Rules — Secure (Bearer token optional)",
    tags=["Secure Endpoint"],
)
async def rules_secure(request: Request):
    """
    Evaluate CEV exemption rules.

    **Bearer token is optional:**
    - No `Authorization` header → request processed normally ✅
    - `Authorization: Bearer <correct-token>` → processed normally ✅
    - `Authorization: Bearer <wrong-token>` → 403 Forbidden ❌
    """
    # Read header manually so a missing header never causes a FastAPI 422
    authorization = request.headers.get("authorization") or request.headers.get("Authorization")

    token_err = _check_token(authorization)
    if token_err:
        return token_err

    body, err = await _parse_body(request)
    if err:
        return err
    return _process(body)


# ── Health / Info ─────────────────────────────────────────────────────────────

@app.get("/health", tags=["Info"], summary="Health check")
async def health():
    return JSONResponse(content={
        "status": "ok",
        "timestamp": _ts(),
        "endpoints": {
            "open":   "POST /cev/drools/api/v1/rules",
            "secure": "POST /cev/drools/api/v1/rules/secure",
        },
    })


@app.get("/", tags=["Info"], summary="Service info")
async def root():
    return JSONResponse(content={
        "service": "CEV Rules Test API Server",
        "version": "1.0.0",
        "swagger_ui": "/docs",
        "endpoints": {
            "open_endpoint": {
                "method": "POST",
                "url": "/cev/drools/api/v1/rules",
                "auth": "None",
            },
            "secure_endpoint": {
                "method": "POST",
                "url": "/cev/drools/api/v1/rules/secure",
                "auth": "Optional Bearer token",
                "configured_token": API_BEARER_TOKEN,
            },
        },
    })


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 62)
    print("  CEV Rules — Test API Server")
    print("=" * 62)
    print(f"  URL   : http://localhost:{API_PORT}")
    print(f"  Docs  : http://localhost:{API_PORT}/docs")
    print()
    print("  Endpoints:")
    print(f"  [OPEN]   POST http://localhost:{API_PORT}/cev/drools/api/v1/rules")
    print(f"  [SECURE] POST http://localhost:{API_PORT}/cev/drools/api/v1/rules/secure")
    print()
    print(f"  Bearer token (optional) : {API_BEARER_TOKEN}")
    print(f"  Change: set API_BEARER_TOKEN=your-token  (Windows cmd)")
    print(f"          API_BEARER_TOKEN=your-token       (Mac/Linux)")
    print("=" * 62)

    uvicorn.run(app, host=API_HOST, port=API_PORT)
