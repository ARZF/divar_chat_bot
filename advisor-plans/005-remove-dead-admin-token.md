# Plan 005: Remove the dead `admin_token` setting

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `advisor-plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat f5abbbc..HEAD -- config.py tests/`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none (but coordinate with plan 001 — both touch test env setup)
- **Category**: tech-debt
- **Planned at**: commit `f5abbbc`, 2026-07-23

## Why this matters

The `admin_token` setting in `config.py` is dead. As of section 2.7 (dated
2026-07-21 in `plans/CHECKLISTS.md`), no source code references
`settings.admin_token` — seller-facing endpoints now authenticate via
`get_current_client_id()` (JWT) instead of the old global admin token. The
field lingers only as: (a) a required `Settings` field in `config.py:14`,
(b) doc prose, and (c) `os.environ.setdefault("admin_token", ...)` lines in the
test files that exist solely to satisfy the required field at import time. The
project's own `plans/CHECKLISTS.md:99-104` explicitly calls for its removal.
Removing it deletes a misleading required secret and its test boilerplate.

## Assumptions

- No source code (outside config/tests/docs) reads `settings.admin_token`
  (this plan's Step 1 verifies this before any deletion — if a live reference is
  found, STOP).
- The `.env` file (untracked, local) may still contain an `admin_token=...` line;
  removing the config field means `extra="ignore"` in `config.py:78` will simply
  ignore it, so no runtime break. (Do not read or modify `.env`.)

If any assumption proves false, treat it as a STOP condition.

## Current state

**config.py:14** (the dead field):
```python
    admin_token: str
```
(It is a *required* field — no default — declared among the Divar secrets in the
`Settings` class, `config.py:5-16`.)

**config.py:78** (extra keys are ignored, so a leftover .env line is harmless):
```python
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")
```

**Test files** each set it at import time, e.g. `tests/test_webhook.py:12`,
`tests/test_price_lookup.py:12`, `tests/test_auth.py:13`,
`tests/test_divar_service.py` (same pattern):
```python
os.environ.setdefault("admin_token", "test_admin_token")
```

**Project directive** — `plans/CHECKLISTS.md:99-104`:
> Remove the now-dead `admin_token` field from `Settings` (`config.py`) and from
> `.env`. As of 2.7 (2026-07-21) no source code references `settings.admin_token`
> ... Drop the field and update the test env-var setup in the same cleanup pass.

**Repository conventions**:
- Settings are env-driven; required fields have no default, optional fields do.
- Tests set required-field env vars before importing project code.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Find references | `grep -rn "admin_token" --include=*.py .` | (see steps) |
| Run tests | `pytest` | exit 0, all pass |
| Import check | `python -c "import config"` | exit 0 |

(Assumes plan 001's test tooling. If not present, `pip install pytest pytest-asyncio pytest-mock aiosqlite` first.)

## Scope

**In scope** (the only files you should modify):
- `config.py` — remove the `admin_token: str` field
- `tests/test_webhook.py`, `tests/test_price_lookup.py`, `tests/test_auth.py`,
  `tests/test_divar_service.py` — remove the `os.environ.setdefault("admin_token", ...)` line
- If plan 001's `conftest.py` exists, remove its `admin_token` line too

**Out of scope** (do NOT touch):
- `.env` — never read or modify it (it is untracked; `extra="ignore"` handles a
  leftover line).
- Any source code that turns out to reference `admin_token` — if Step 1 finds a
  live reference, STOP (the field is not actually dead).
- `plans/CHECKLISTS.md` prose — leave the directive; it documents the decision.

## Git workflow

- Branch: `advisor/005-remove-admin-token`
- Do NOT push or open a PR unless instructed.

## Steps

### Step 1: Confirm the field is truly unused in source code

```bash
grep -rn "admin_token" --include=*.py . | grep -v "/tests/" | grep -v "conftest.py"
```

**Verify**: The ONLY match is `config.py:14` (`admin_token: str`). If any *other*
source file references `admin_token` or `settings.admin_token`, **STOP** — the
field is live, and this plan's premise is wrong.

### Step 2: Remove the field from config.py

Delete line 14 (`    admin_token: str`) from the `Settings` class in `config.py`.

**Verify**: `grep -n "admin_token" config.py` → no matches (exit code 1).
`python -c "import config"` → exit 0.

### Step 3: Remove the test env-var lines

In each of the four test files (and `conftest.py` if plan 001 created it), delete
the line:
```python
os.environ.setdefault("admin_token", "test_admin_token")
```

**Verify**: `grep -rn "admin_token" --include=*.py .` → no matches at all (exit
code 1).

### Step 4: Run the test suite

```bash
pytest
```

**Verify**: Exit code 0, all tests pass. Removing a required setting means
`Settings()` no longer demands `admin_token`; tests still construct `settings`
successfully without setting it.

## Test plan

- No new tests — this is a removal. The existing suite passing without the
  `admin_token` env var *is* the verification that the field was dead.
- Verification: `pytest` → all pass; `python -c "import config"` → exit 0.

## Done criteria

- [ ] Step 1 confirmed no source reference outside `config.py:14`
- [ ] `admin_token` field removed from `config.py`
- [ ] `os.environ.setdefault("admin_token", ...)` removed from all four test files
      (and `conftest.py` if present)
- [ ] `grep -rn "admin_token" --include=*.py .` returns no matches
- [ ] `python -c "import config"` exits 0
- [ ] `pytest` exits 0, all tests pass
- [ ] No files outside the in-scope list modified (`git status`)
- [ ] `advisor-plans/README.md` row 005 status updated

## STOP conditions

Stop and report back if:

- Step 1 finds any `admin_token` reference in source code outside `config.py:14`
  (the field is not dead — do not remove it).
- `config.py`'s `Settings` no longer contains `admin_token: str` (already removed
  — mark the plan DONE/REJECTED accordingly and note it).
- Any test fails after removal in a way that references `admin_token` (indicates
  a missed reference).

## Maintenance notes

- The operator should also remove the `admin_token=...` line from their local and
  deployment `.env` files during the next config review (this plan cannot touch
  `.env`). It is harmless if left (`extra="ignore"`), just noise.
- If plan 001 and plan 005 are executed close together, coordinate the
  `conftest.py` edit so one doesn't re-add what the other removes.
