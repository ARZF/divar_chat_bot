# Plan 001: Declare test/dev dependencies and add a one-command test runner

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `advisor-plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat f5abbbc..HEAD -- requirements.txt tests/`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: dx
- **Planned at**: commit `f5abbbc`, 2026-07-23

## Why this matters

The test suite exists (`tests/test_*.py`) and runs when invoked directly, but
there is no reproducible one-command way to install the test runner and
dependencies or run all tests. `requirements.txt` declares only production
dependencies; test-only packages (`pytest`, `pytest-asyncio`, `pytest-mock`,
`httpx` TestClient support) are absent. Every test file hard-codes env-var
setup inline (12 lines of `os.environ.setdefault` repeated per file). This
blocks onboarding, CI setup, and any new test work (including plan 007). This
plan establishes a reproducible test baseline: declared test deps, a shared
test config to eliminate the inline env boilerplate, and a one-command runner.

## Assumptions

- Python 3.10+ is available (matches the async syntax in use).
- The venv/pip toolchain is used (no poetry/pipenv/conda).
- Tests use `pytest` (already imported in every test file).
- No existing `conftest.py`, `pytest.ini`, or `pyproject.toml` declares pytest
  config (verified during recon — none present).

If any assumption proves false, treat it as a STOP condition.

## Current state

**Test file pattern** (all four test files follow this):
```python
# tests/test_webhook.py:1-12 (and test_auth.py, test_divar_service.py, test_price_lookup.py)
import os

# Set test env vars before any project imports — config.py instantiates Settings at module level
os.environ.setdefault("DIVAR_API_KEY", "test_api_key")
os.environ.setdefault("DIVAR_ACCESS_TOKEN", "test_access_token")
os.environ.setdefault("DIVAR_REFRESH_TOKEN", "test_refresh_token")
os.environ.setdefault("DIVAR_WEBHOOK_SECRET", "test_webhook_secret")
os.environ.setdefault("DIVAR_IDENTIFICATION_KEY", "test_identification_key")
os.environ.setdefault("DIVAR_APP_SLUG", "test_app_slug")
os.environ.setdefault("DIVAR_CLIENT_SECRET", "test_client_secret")
os.environ.setdefault("DIVAR_REDIRECT_URI", "https://example.com/callback")
os.environ.setdefault("admin_token", "test_admin_token")
```

`test_auth.py` adds two more (lines 14-16):
```python
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("JWT_SECRET_KEY", "test_jwt_secret_key")
os.environ.setdefault("OTP_HMAC_KEY", "test_otp_hmac_key")
```

**requirements.txt** (12 lines, production only — no pytest/test deps):
```
fastapi==0.136.3
uvicorn[standard]==0.49.0
httpx==0.28.1
pydantic-settings==2.14.1
pandas==3.0.3
openpyxl==3.1.5
python-multipart==0.0.32
RapidFuzz==3.14.5
sqlalchemy[asyncio]==2.0.41
asyncpg==0.31.0
alembic==1.16.2
pyjwt==2.10.1
```

**Repository conventions**:
- All config is env-driven via `pydantic-settings` (`config.py:5-80`).
- Tests use FastAPI's `TestClient` (sync wrapper over async app).
- Async tests (`test_auth.py`) use `pytest-asyncio` fixtures + `@pytest_asyncio.fixture`.
- Tests mock via `pytest-mock` (`mocker` fixture — `test_webhook.py:44,59,77`).

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Install deps | `pip install -r requirements.txt` | exit 0 |
| Run all tests | `pytest` | exit 0, all pass |
| Run specific file | `pytest tests/test_webhook.py` | exit 0, that file's tests pass |

(After this plan completes.)

## Scope

**In scope** (the only files you should create/modify):
- `requirements.txt` — add test-dep section
- `conftest.py` (create at repo root) — shared pytest fixtures + env setup
- `pytest.ini` (create at repo root) — pytest config (asyncio mode)

**Out of scope** (do NOT touch):
- The four existing test files (`tests/test_*.py`) — they will be cleaned up
  in a follow-on refactor after this baseline is established; changing them
  now risks breaking working tests.
- `config.py`, `main.py`, any source code outside `tests/`.

## Git workflow

- Branch: `advisor/001-test-tooling` (or work directly on your current branch)
- Do NOT push or open a PR unless instructed.

## Steps

### Step 1: Add test dependencies to requirements.txt

Append a test-dependencies section to `requirements.txt`. Keep the existing
production deps unchanged; add after line 12:

```txt

# --- Test / Development Dependencies ---
pytest==8.3.4
pytest-asyncio==0.24.0
pytest-mock==3.14.0
aiosqlite==0.20.0
```

Version rationale:
- `pytest` 8.3.4: current stable as of 2026-07.
- `pytest-asyncio` 0.24.0: supports pytest 8.x + modern async fixtures.
- `pytest-mock` 3.14.0: current stable, provides the `mocker` fixture already in use.
- `aiosqlite` 0.20.0: async SQLite driver used by `test_auth.py`'s in-memory DB;
  already imported but not declared (missing transitive dep).

**Verify**: `cat requirements.txt | tail -6` → shows the four new lines.

### Step 2: Create pytest.ini with asyncio mode

Create `pytest.ini` at the repo root with this exact content:

```ini
[pytest]
testpaths = tests
python_files = test_*.py
python_classes = Test*
python_functions = test_*
asyncio_mode = auto
asyncio_default_fixture_loop_scope = function
```

Explanation:
- `asyncio_mode = auto`: pytest-asyncio automatically detects async test functions
  and fixtures; no manual `@pytest.mark.asyncio` needed (already absent from
  `test_auth.py`'s async tests — they rely on auto-mode).
- `asyncio_default_fixture_loop_scope = function`: each async fixture gets its
  own event loop (matches `test_auth.py`'s current fixture pattern).

**Verify**: `cat pytest.ini` → file exists, 7 lines.

### Step 3: Create conftest.py with shared env-var setup

Create `conftest.py` at the repo root (pytest auto-loads this before running
tests, so all test modules inherit its setup). Content:

```python
"""Shared pytest configuration — auto-loaded before every test run.

Sets required env vars before config.py instantiation so tests don't need
inline os.environ.setdefault blocks.
"""
import os

# Set test env vars BEFORE any project imports — config.py instantiates
# Settings at module level, so these must be in place first.
os.environ.setdefault("DIVAR_API_KEY", "test_api_key")
os.environ.setdefault("DIVAR_ACCESS_TOKEN", "test_access_token")
os.environ.setdefault("DIVAR_REFRESH_TOKEN", "test_refresh_token")
os.environ.setdefault("DIVAR_WEBHOOK_SECRET", "test_webhook_secret")
os.environ.setdefault("DIVAR_IDENTIFICATION_KEY", "test_identification_key")
os.environ.setdefault("DIVAR_APP_SLUG", "test_app_slug")
os.environ.setdefault("DIVAR_CLIENT_SECRET", "test_client_secret")
os.environ.setdefault("DIVAR_REDIRECT_URI", "https://example.com/callback")
os.environ.setdefault("admin_token", "test_admin_token")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("JWT_SECRET_KEY", "test_jwt_secret_key")
os.environ.setdefault("OTP_HMAC_KEY", "test_otp_hmac_key")
```

This consolidates the 12-line inline setup from all test files into one shared
location. All 12 vars are included (the union of what `test_auth.py` needs and
what the other three need), so every test file will have them available.

**Verify**: `cat conftest.py | wc -l` → 23 lines.

### Step 4: Install the new dependencies

```bash
pip install -r requirements.txt
```

**Verify**: `pip show pytest pytest-asyncio pytest-mock aiosqlite` → all four
packages installed, versions match.

### Step 5: Run the test suite to confirm baseline works

```bash
pytest
```

**Verify**: Exit code 0, all existing tests pass (approximately 50+ tests across
4 files). Output summary line should show something like `passed in X.XXs`.

If any test fails, this is a STOP condition — the env-var setup or deps are
wrong. Do not proceed.

### Step 6: Verify specific-file invocation works

```bash
pytest tests/test_webhook.py
```

**Verify**: Exit code 0, only `test_webhook.py`'s tests run (~6 tests).

## Test plan

No new tests in this plan — it establishes the test infrastructure. Verification
is that the *existing* test suite runs successfully with the new setup.

## Done criteria

- [x] `requirements.txt` declares `pytest`, `pytest-asyncio`, `pytest-mock`, `aiosqlite`
- [x] `pytest.ini` exists with `asyncio_mode = auto`
- [x] `conftest.py` exists with all 12 env vars set
- [x] `pytest` (no args) exits 0 and all existing tests pass
- [x] `pytest tests/test_auth.py` exits 0 (verifies async fixtures work)
- [x] No files outside the in-scope list are modified (`git status`)
- [x] `advisor-plans/README.md` row 001 status updated to DONE

## Execution record (2026-07-28)

Completed. Deviations from the plan as written, all deliberate:

- **Versions pinned higher than planned**: `pytest==9.1.1`, `pytest-asyncio==1.4.0`,
  `pytest-mock==3.15.1` (plan proposed 8.3.4 / 0.24.0 / 3.14.0). `aiosqlite==0.20.0`
  as planned. All 95 tests pass on these versions, and they also eliminate ~5000
  `asyncio.get_event_loop_policy` DeprecationWarnings emitted by pytest-asyncio 0.24.
- **conftest.py env-var list adjusted for drift**: `admin_token` was dropped
  (plan 005 removed the setting) and `CORS_ALLOWED_ORIGINS` added (plan 002), so
  conftest sets the 12 vars `config.py` actually requires today — not the plan's list.
- **Test suite grew**: `tests/test_chatbot.py` and `tests/test_oauth.py` were added
  after this plan was written, so the baseline is 95 tests across 6 files, not
  "~50+ across 4".
- **Interpreter**: deps installed into the project `.venv`, not global Python
  (the global 3.14 install lacks httpx/sqlalchemy/pandas). Run tests via
  `.venv\Scripts\python.exe -m pytest`.

## STOP conditions

Stop and report back if:

- The existing test suite fails after step 4 (indicates wrong env vars or deps).
- `pytest.ini` or `conftest.py` already exist with conflicting content (codebase
  drift since this plan was written).
- Installing the test deps triggers a dependency conflict with production deps.
- Any of the four test files have been refactored to no longer use the inline
  `os.environ.setdefault` pattern (drift — the plan's premise is invalidated).

## Maintenance notes

**For the next person touching tests**:
- The inline `os.environ.setdefault` blocks in the four test files are now
  redundant (conftest.py handles it), but they're left in place for now to avoid
  touching working tests. A follow-on refactor can remove them.
- When adding a new required setting to `config.py`, also add a corresponding
  test default to `conftest.py` so new tests don't break on import.
- If any test needs a *different* value for one of these vars (e.g. to test
  behavior under a missing API key), use `monkeypatch.setenv` or `mocker.patch`
  within that specific test — don't modify the shared conftest.py defaults.
