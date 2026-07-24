# Plan 006: Add a committed `.env.example` template

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `advisor-plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat f5abbbc..HEAD -- config.py .gitignore`
> If either file changed since this plan was written, compare the "Current
> state" excerpts against the live code before proceeding; on a mismatch, treat
> it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: dx
- **Planned at**: commit `f5abbbc`, 2026-07-23

## Why this matters

There is no `.env.example` in the repo. A `.env` file is required at startup
(`config.py` declares many *required*, no-default settings — several of them
secrets), but the only way to discover which vars are needed is to read
`config.py` and infer. A committed `.env.example` with placeholder (non-secret)
values documents every required and optional variable, so a new developer or a
deploy pipeline can copy it to `.env` and fill in real values. This is pure
onboarding/DX with no runtime impact.

## Assumptions

- `config.py`'s `Settings` class is the single source of truth for env vars.
- No real secret values will be placed in `.env.example` — only placeholders and
  the safe defaults already visible in `config.py`.
- `.gitignore` currently ignores `.env.*` (line 64), which would also ignore
  `.env.example` — this plan must add an explicit un-ignore for it, or the file
  cannot be committed.

If any assumption proves false, treat it as a STOP condition.

## Current state

**config.py:5-29** — required (no-default) settings that MUST be in `.env`:
```python
class Settings(BaseSettings):
    DIVAR_API_KEY: str
    DIVAR_ACCESS_TOKEN: str
    DIVAR_REFRESH_TOKEN: str
    DIVAR_WEBHOOK_SECRET: str
    DIVAR_IDENTIFICATION_KEY: str
    DIVAR_APP_SLUG: str
    DIVAR_CLIENT_SECRET: str
    DIVAR_REDIRECT_URI: str
    admin_token: str                 # NOTE: may be removed by plan 005 — see Step 2
    DATABASE_URL: str
    EXPERIMENTAL_CLIENT_ID: int | None = None
    JWT_SECRET_KEY: str
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_LIFETIME_MINUTES: int = 30
    REFRESH_TOKEN_LIFETIME_DAYS: int = 30
    OTP_LENGTH: int = 6
    OTP_LIFETIME_MINUTES: int = 5
    OTP_MAX_ATTEMPTS: int = 5
    OTP_REQUEST_COOLDOWN_SECONDS: int = 120
    OTP_HMAC_KEY: str
    SMS_PROVIDER_API_KEY: str | None = None
    SMS_PROVIDER_URL: str | None = None
```

**.gitignore:62-65** (ignores all `.env*`):
```
# Environment variables
.env
.env.*
.venv/
```

**Repository conventions**:
- `config.py:78` reads from `.env` via `SettingsConfigDict(env_file=".env", ...)`.
- Required fields = secrets or deploy-specific; optional fields already carry safe
  defaults in `config.py` and generally need not be overridden.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Confirm not-ignored | `git check-ignore .env.example` | exit 1 (NOT ignored) after Step 1 |
| Confirm trackable | `git status --porcelain .env.example` | shows the file as untracked/added |

## Scope

**In scope** (the only files you should create/modify):
- `.gitignore` — add an explicit un-ignore for `.env.example`
- `.env.example` (create) — placeholder template

**Out of scope** (do NOT touch):
- `.env` — never read, print, or commit it.
- `config.py` — do not change settings here (plan 005 handles `admin_token`).

## Git workflow

- Branch: `advisor/006-env-example`
- Do NOT push or open a PR unless instructed.

## Steps

### Step 1: Un-ignore `.env.example` in .gitignore

Because `.gitignore:64` has `.env.*`, `.env.example` would be ignored. Add an
explicit negation immediately after that block. Change:
```
# Environment variables
.env
.env.*
.venv/
```
to:
```
# Environment variables
.env
.env.*
!.env.example
.venv/
```

**Verify**: `git check-ignore .env.example` → exit code 1 (meaning NOT ignored).

### Step 2: Create `.env.example` with placeholders (NO real secrets)

Create `.env.example` at the repo root. Use obvious placeholders for secrets and
the real safe defaults for tunables. If plan 005 has already removed
`admin_token`, omit the `admin_token` line; otherwise include it.

```dotenv
# ---- Divar platform credentials (obtain from the Kenar panel) ----
DIVAR_API_KEY=your-divar-api-key
DIVAR_ACCESS_TOKEN=your-divar-access-token
DIVAR_REFRESH_TOKEN=your-divar-refresh-token
DIVAR_WEBHOOK_SECRET=your-divar-webhook-secret
DIVAR_IDENTIFICATION_KEY=your-divar-identification-key
DIVAR_APP_SLUG=your-app-slug
DIVAR_CLIENT_SECRET=your-divar-client-secret
DIVAR_REDIRECT_URI=https://your-domain.example.com/oauth/callback

# ---- Admin (only if not yet removed per advisor-plan 005) ----
admin_token=change-me

# ---- Database ----
DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/divar_chat_bot

# ---- Optional: experimental single-tenant fallback (leave unset in prod) ----
# EXPERIMENTAL_CLIENT_ID=1

# ---- Seller auth / JWT (section 2.8) ----
JWT_SECRET_KEY=generate-a-long-random-string
JWT_ALGORITHM=HS256
ACCESS_TOKEN_LIFETIME_MINUTES=30
REFRESH_TOKEN_LIFETIME_DAYS=30

# ---- OTP ----
OTP_LENGTH=6
OTP_LIFETIME_MINUTES=5
OTP_MAX_ATTEMPTS=5
OTP_REQUEST_COOLDOWN_SECONDS=120
OTP_HMAC_KEY=generate-a-long-random-string

# ---- SMS provider (no provider chosen yet — optional) ----
# SMS_PROVIDER_API_KEY=
# SMS_PROVIDER_URL=

# ---- CORS (only if advisor-plan 002 landed) ----
# CORS_ALLOWED_ORIGINS=["https://panel.example.com"]
```

Notes:
- All secret values are obvious placeholders — no real credential appears.
- Optional settings with defaults are shown commented where overriding is rare.
- The `CORS_ALLOWED_ORIGINS` line is commented and marked conditional on plan 002.

**Verify**: `git status --porcelain .env.example` → shows `?? .env.example`
(untracked, ready to add).

### Step 3: Sanity-check completeness against config.py

Cross-check that every *required* (no-default) field in `config.py`'s `Settings`
appears in `.env.example`. Required fields are those without `= <default>`:
`DIVAR_API_KEY`, `DIVAR_ACCESS_TOKEN`, `DIVAR_REFRESH_TOKEN`,
`DIVAR_WEBHOOK_SECRET`, `DIVAR_IDENTIFICATION_KEY`, `DIVAR_APP_SLUG`,
`DIVAR_CLIENT_SECRET`, `DIVAR_REDIRECT_URI`, `admin_token` (unless removed),
`DATABASE_URL`, `JWT_SECRET_KEY`, `OTP_HMAC_KEY`.

**Verify**: For each required name, `grep -c "^<NAME>=" .env.example` → `1`.

## Test plan

- No automated test — this is documentation. Optional manual check: copy
  `.env.example` to a scratch `.env.test`, fill placeholders, and confirm
  `python -c "import config"` succeeds (do NOT commit `.env.test`).
- Verification: Step 2/3 verify commands pass.

## Done criteria

- [x] `.gitignore` contains `!.env.example`
- [x] `git check-ignore .env.example` returns exit code 1 (not ignored)
- [x] `.env.example` exists and contains every required `config.py` setting
- [x] No real secret values appear in `.env.example` (placeholders only)
- [x] `git status` shows `.env.example` as trackable
- [x] No files outside the in-scope list modified (`git status`)
- [x] `advisor-plans/README.md` row 006 status updated

## STOP conditions

Stop and report back if:

- `.gitignore` no longer contains `.env.*` (drift — the negation may be
  unnecessary or need adjustment).
- You are about to write a value that looks like a real credential (from `.env`
  or anywhere) — STOP; use a placeholder only.
- `config.py`'s `Settings` fields differ materially from the "Current state"
  excerpt (drift — re-derive the required-field list before writing the template).

## Maintenance notes

- Keep `.env.example` in sync when adding/removing a setting in `config.py`.
  A reviewer should reject a `config.py` settings change that doesn't update this
  template.
- If plan 002 (CORS) or plan 005 (`admin_token`) land after this, update the
  corresponding lines here accordingly.
