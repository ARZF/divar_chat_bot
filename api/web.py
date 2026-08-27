"""Server-rendered HTML routes (section 3.5).

This router renders Jinja2 templates only. Business logic stays in
`services/` and the JSON APIs — HTML routes must not duplicate it, and no
secrets may be passed into a template context or a static asset.

`templates` is defined here (not in `main.py`) so every HTML route resolves
templates through one configured environment.

Protected-route convention (phase 3 step 12): HTML routes have no server-side
auth dependency. The refresh cookie is scoped to path=/auth (api/auth.py), so
a plain browser GET of a protected page never carries it and a server-side
cookie check cannot distinguish anonymous from logged-in visitors — it would
redirect everyone to /login. Protected pages are therefore gated by the shared
client-side module `static/js/session.js` (loaded by `templates/base.html`):
data is fetched only through `DivarSession.authFetch()`, which attaches the
in-memory access token, on 401 calls POST /auth/refresh exactly once, retries
the request once, and redirects to /login when that fails. Real enforcement
stays with `get_current_client_id` on the JSON APIs; the cookie is never
accepted as authentication for API endpoints.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

# Resolved from this file so the app works regardless of the process CWD
# (uvicorn locally, Docker `WORKDIR /app`).
BASE_DIR = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

router = APIRouter()
logger = logging.getLogger("web")


@router.get("/", response_class=HTMLResponse)
async def home(request: Request) -> HTMLResponse:
    """Render the anonymous public home page."""
    return templates.TemplateResponse(request, "public/home.html")


@router.get("/pricing", response_class=HTMLResponse)
async def pricing(request: Request) -> HTMLResponse:
    """Render the public package availability page."""
    return templates.TemplateResponse(request, "public/pricing.html")


@router.get("/login", response_class=HTMLResponse)
async def login(request: Request) -> HTMLResponse:
    """Render the login form before browser API integration is added."""
    return templates.TemplateResponse(request, "auth/login.html")


@router.get("/login/otp", response_class=HTMLResponse)
async def login_otp(request: Request) -> HTMLResponse:
    """Render the OTP form before browser API integration is added."""
    return templates.TemplateResponse(request, "auth/otp.html")


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request) -> HTMLResponse:
    """Render the seller dashboard shell (§3.6).

    First protected page under the step 12 convention: no server-side auth or
    DB access here — the shell renders anonymously with loading placeholders,
    and static/js/dashboard.js restores the session and loads the real,
    tenant-scoped data via the JSON summary API.
    """
    return templates.TemplateResponse(request, "dashboard/dashboard.html")
