# Plan 003: Remove resolution debug/fallback scaffolding

> **Completion note (2026-07-28): DONE.** After auditing the original scope,
> the maintainer approved expanding execution beyond the debug log. The
> undocumented `EXPERIMENTAL_CLIENT_ID` bypass, its operational warning, its
> `config.py` setting, and its `.env.example` entry were also removed. Real
> `Client` + `Post` fixtures and `/start MY_POST` / `DEMAND_POST` resolution
> tests were added first, so tests now exercise the tenant-safe production path.
> The original plan below remains as historical pre-execution context.

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `advisor-plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat f5abbbc..HEAD -- services/chatbot.py`
> If `services/chatbot.py` changed since this plan was written, compare the
> "Current state" excerpt against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Execution status**: DONE (expanded with maintainer approval)
- **Priority**: P2
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: tech-debt
- **Planned at**: commit `f5abbbc`, 2026-07-23

## Why this matters

`services/chatbot.py` contains a leftover development debug log inside
`_resolve_new_conversation`: `logger.warning("RESOLVE DEBUG", extra={...})`.
It fires at **WARNING** level on a hot path — every unresolved conversation and
every experimental-fallback message re-runs this function (unresolved
conversations are stateless per the project's `plans/PHASE2.md` §2.1 design, so
every message re-enters here). This pollutes production warning logs with an
all-caps "RESOLVE DEBUG" marker and dumps `user_text`, the parse result, and a
config value on every call. It is not part of the project's sanctioned
structured-logging setup (task 1.B3 in `plans/PHASE1.md`, which added
`logger.info("incoming message", extra={"text": user_text})` in
`api/webhook.py` — a distinct INFO line). This is clearly leftover debug cruft
and should be removed.

## Assumptions

- The `RESOLVE DEBUG` line is debug scaffolding, not a deliberate audit log
  (confirmed: it is WARNING-level, all-caps "DEBUG"-named, and not referenced in
  any plans/ task; the project's real logging is INFO-level and lives elsewhere).
- Removing it changes only log output, not control flow — the surrounding
  `if parsed is None:` logic is independent of the log call.

If any assumption proves false, treat it as a STOP condition.

## Current state

**services/chatbot.py:89-98** (inside `_resolve_new_conversation`):
```python
    parsed = parse_start_message(user_text)

    logger.warning(
        "RESOLVE DEBUG",
        extra={
            "user_text": repr(user_text),
            "parsed": parsed,
            "experimental_client": settings.EXPERIMENTAL_CLIENT_ID,
        },
    )

    if parsed is None:
```

The function continues from `if parsed is None:` — that branch and everything
after it does NOT depend on the log call.

**Repository conventions**:
- Structured logging via the stdlib `logging` module; each module has its own
  logger (`logger = logging.getLogger("chatbot")` at `services/chatbot.py:23`).
- Legitimate operational logs use INFO for normal events and WARNING only for
  genuine anomalies (e.g. `api/webhook.py:23` `logger.warning("webhook auth failed")`).

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Run tests | `pytest` | exit 0, all pass |
| Import check | `python -c "import services.chatbot"` | exit 0, no error |

(Assumes plan 001's test tooling. If not present, `pip install pytest pytest-asyncio pytest-mock aiosqlite` first.)

## Scope

**In scope** (the only file you should modify):
- `services/chatbot.py` — remove the `RESOLVE DEBUG` `logger.warning(...)` call

**Out of scope** (do NOT touch):
- Any other log statement in the file (the `logger.warning("Using experimental
  fallback without /start", ...)` at lines 119-126 is a separate, intentional
  operational log — leave it).
- The `logger.info("incoming message", ...)` in `api/webhook.py` — that is the
  sanctioned 1.B3 log, out of scope here.
- Control flow — only the log statement is removed.

## Git workflow

- Branch: `advisor/003-remove-debug-log`
- Do NOT push or open a PR unless instructed.

## Steps

### Step 1: Delete the RESOLVE DEBUG log statement

In `services/chatbot.py`, remove the entire `logger.warning("RESOLVE DEBUG", ...)`
call (the 9-line block shown in "Current state"), leaving the surrounding code:

After the change, the region reads:
```python
    parsed = parse_start_message(user_text)

    if parsed is None:
```

Do not alter the blank line spacing conventions of the file (keep one blank line
between `parsed = ...` and `if parsed is None:`).

**Verify**: `grep -n "RESOLVE DEBUG" services/chatbot.py` → no matches (exit code 1).

### Step 2: Confirm the module still imports and parses

**Verify**: `python -c "import services.chatbot"` → exit 0, no SyntaxError.

### Step 3: Run the test suite

```bash
pytest
```

**Verify**: Exit code 0, all existing tests pass (no test asserts on this log
line, so nothing should break).

## Test plan

- No new test required — this removes debug output with no behavioral change.
- If plan 007 (chatbot intent-router tests) has already landed, re-run those to
  confirm resolution behavior is unchanged: `pytest tests/test_chatbot.py`.
- Verification: `pytest` → all pass.

## Done criteria

- [x] `grep -n "RESOLVE DEBUG" services/chatbot.py` returns no matches
- [x] Approved expanded scope removes the experimental fallback branch and its
      `logger.warning("Using experimental fallback without /start", ...)` log
- [x] `python -c "import services.chatbot"` exits 0
- [x] `pytest` exits 0: 93 tests passed, including 7 focused resolution tests
- [x] Approved expanded-scope files are limited to chatbot resolution tests,
      fallback code/config, and related advisor-plan bookkeeping
- [x] `advisor-plans/README.md` row 003 status updated

## STOP conditions

Stop and report back if:

- The `RESOLVE DEBUG` block no longer matches the "Current state" excerpt (drift).
- Removing the log breaks a test (indicates something asserts on it — investigate
  before deleting).
- You find additional `logger.warning(... "DEBUG" ...)` or obvious debug-marker
  logs elsewhere in `services/chatbot.py` — report them (do not expand scope to
  remove them without confirmation).

## Maintenance notes

- For future debugging, prefer `logger.debug(...)` (filtered out of production by
  log level) over `logger.warning(...)`, and remove temporary debug logs before
  merging.
- Note the broader context: per `plans/CHECKLISTS.md`, logging message *text* is
  under a temporary, dated override (approved for early development) and must be
  suppressed before real seller traffic. That is a separate, larger task
  (tracked in CHECKLISTS.md) — this plan only removes the one leftover debug line.
