"""Server-rendered HTML routes (section 3.5).

This router renders Jinja2 templates only. Business logic stays in
`services/` and the JSON APIs — HTML routes must not duplicate it, and no
secrets may be passed into a template context or a static asset.

`templates` is defined here (not in `main.py`) so every HTML route resolves
templates through one configured environment.
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


@router.get("/web/probe", response_class=HTMLResponse)
async def probe(request: Request) -> HTMLResponse:
    """Foundation probe: proves template rendering and static asset wiring.

    Temporary scaffold for Phase 3 step 2 — replaced by the real pages in the
    public-website slice.
    """
    return templates.TemplateResponse(request, "probe.html")
