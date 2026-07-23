# Plan 002: Fix CORS wildcard origin combined with credentials

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `advisor-plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat f5abbbc..HEAD -- main.py config.py`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: MED
- **Depends on**: none
- **Category**: security
- **Planned at**: commit `f5abbbc`, 2026-07-23

## Why this matters

`main.py` configures CORS with `allow_origins=["*"]` **together with**
`allow_credentials=True`. This is an invalid and unsafe combination: the CORS
spec forbids the wildcard origin when credentials are allowed, and Starlette
handles this by reflecting the request's `Origin` back — effectively allowing
*any* website to make credentialed cross-origin requests. This project issues a
refresh-token as an HTTP-only cookie (`api/auth.py:159-167`, path `/auth`), so a
malicious site could drive credentialed requests against the seller auth API
from a victim's browser. Replacing the wildcard with an explicit, configurable
allow-list closes this while keeping legitimate front-end origins working.

## Assumptions

- The seller-facing front-end runs on one or more known origins (to be supplied
  via config). If no browser front-end consumes these APIs at all, an even
  stricter empty list is acceptable — but confirm before assuming that.
- The webhook (`/api/v1/webhook`) is a server-to-server call from Divar and does
  not rely on browser CORS, so tightening CORS does not affect it.
- `pydantic-settings` is the config mechanism (`config.py`), and list-typed
  settings can be provided via env as JSON or comma-separated per pydantic rules.

If any assumption proves false, treat it as a STOP condition.

## Current state

**main.py:1-33** (the CORS block):
```python
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from api.webhook import router as webhook_router
# ... other router imports ...

# ... lifespan ...

app = FastAPI(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)
app.include_router(webhook_router)
# ... other routers ...
```

**config.py:5-16** (Settings class head — where a new setting is added):
```python
class Settings(BaseSettings):
    DIVAR_API_KEY: str
    DIVAR_ACCESS_TOKEN: str
    # ... more required fields ...
    DATABASE_URL: str
    EXPERIMENTAL_CLIENT_ID: int | None = None
```

**config.py:78** (the model config, showing env handling):
```python
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")
```

**Repository conventions**:
- All tunables live in `config.py`'s `Settings` and are read via
  `from config import settings` (see `main.py`, `api/webhook.py:5`).
- `FrozenSet`/`Dict` typed settings already exist (`config.py:44,72`), so a
  `List[str]` setting fits the existing style.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Run tests | `pytest` | exit 0, all pass |
| Import check | `python -c "import main"` | exit 0, no error |

(Assumes plan 001 has established the test tooling. If not, run
`pip install pytest pytest-asyncio pytest-mock aiosqlite` first.)

## Scope

**In scope** (the only files you should modify):
- `config.py` — add a `CORS_ALLOWED_ORIGINS` setting
- `main.py` — use the setting instead of `["*"]`

**Out of scope** (do NOT touch):
- Any router or endpoint file — this is purely middleware config.
- The webhook auth logic — unrelated to CORS.

## Git workflow

- Branch: `advisor/002-cors`
- Do NOT push or open a PR unless instructed.

## Steps

### Step 1: Add a configurable allowed-origins setting to config.py

In `config.py`, add a typed setting to the `Settings` class. Place it near the
other new-config constants (after `EXPERIMENTAL_CLIENT_ID` on line 16 is a good
spot). Add the `List` import to the existing `typing` import on line 1.

Change line 1 from:
```python
from typing import FrozenSet, Dict
```
to:
```python
from typing import FrozenSet, Dict, List
```

Add the setting (after line 16):
```python
    # CORS: explicit allow-list of browser origins permitted to send credentialed
    # requests. NEVER combine "*" with allow_credentials=True. Provide via .env as a
    # JSON array, e.g. CORS_ALLOWED_ORIGINS=["https://panel.example.com"].
    # Empty list = no cross-origin browser access (safe default).
    CORS_ALLOWED_ORIGINS: List[str] = []
```

**Verify**: `python -c "from config import settings; print(settings.CORS_ALLOWED_ORIGINS)"`
→ prints `[]` (with the test/real env set).

### Step 2: Use the setting in main.py

In `main.py`, add `from config import settings` if not already imported at the
top (check the existing imports first — it may already be imported transitively,
but add an explicit import to be safe). Then replace the CORS middleware block:

Replace:
```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)
```
with:
```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ALLOWED_ORIGINS,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
    allow_credentials=True,
)
```

Rationale for the narrowed methods/headers: the app only exposes GET and POST
routes (see the route list — `/oauth/*` GET, `/api/v1/webhook` POST,
`/admin/upload-prices` POST, `/auth/*` POST/GET, `/seller/posts` POST); OPTIONS
is needed for preflight. `Authorization` and `Content-Type` are the only headers
clients send. If a future endpoint needs another method/header, extend these lists.

**Verify**: `python -c "import main"` → exit 0, no error.

### Step 3: Confirm the wildcard is gone

**Verify**: `grep -n 'allow_origins=\["\*"\]' main.py` → returns nothing (exit code 1).

### Step 4: Run the test suite

```bash
pytest
```

**Verify**: Exit code 0, all existing tests pass. (The webhook tests do not
exercise CORS, so they must still pass unchanged.)

## Test plan

- No new automated test is strictly required (CORS is middleware config), but if
  you want a regression guard, add a test in `tests/test_webhook.py` (or a new
  `tests/test_cors.py`) that sends an `OPTIONS` preflight with
  `Origin: https://evil.example.com` and asserts the response does **not**
  reflect that origin in `access-control-allow-origin`. Model it after the
  existing `TestClient` usage in `tests/test_webhook.py:48-73`.
- Verification: `pytest` → all pass.

## Done criteria

- [ ] `config.py` defines `CORS_ALLOWED_ORIGINS: List[str] = []`
- [ ] `main.py` passes `settings.CORS_ALLOWED_ORIGINS` to the CORS middleware
- [ ] `grep -n 'allow_origins=\["\*"\]' main.py` returns no matches
- [ ] `allow_credentials=True` is retained (cookie flow still works for allowed origins)
- [ ] `python -c "import main"` exits 0
- [ ] `pytest` exits 0, all existing tests pass
- [ ] No files outside the in-scope list modified (`git status`)
- [ ] `advisor-plans/README.md` row 002 status updated

## STOP conditions

Stop and report back if:

- `main.py`'s CORS block no longer matches the "Current state" excerpt (drift).
- Removing the wildcard breaks a test that depended on it (indicates a browser
  client the plan didn't account for — report so the origin can be added to
  the allow-list explicitly).
- You discover a front-end origin is required but its value is unknown — do NOT
  guess or re-add `"*"`; report and ask for the origin(s).

## Maintenance notes

- Production deployment must set `CORS_ALLOWED_ORIGINS` in `.env` to the real
  seller-panel origin(s), e.g. `CORS_ALLOWED_ORIGINS=["https://panel.example.com"]`.
  The empty-list default is deliberately safe (no cross-origin browser access).
- Never revert to `allow_origins=["*"]` while `allow_credentials=True`; the two
  are mutually exclusive per the CORS spec and Starlette reflects the origin,
  defeating the protection.
- If plan 006 (`.env.example`) is also executed, add `CORS_ALLOWED_ORIGINS` to
  that template.
