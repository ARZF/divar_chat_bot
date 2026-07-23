# Plan 004: Guard background-task send failures in `handle_bot_reply`

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `advisor-plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat f5abbbc..HEAD -- services/chatbot.py services/divar.py`
> If either file changed since this plan was written, compare the "Current
> state" excerpts against the live code before proceeding; on a mismatch, treat
> it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: MED
- **Depends on**: none
- **Category**: bug
- **Planned at**: commit `f5abbbc`, 2026-07-23

## Why this matters

The webhook returns `200 OK` immediately and hands work to a FastAPI
`BackgroundTask` (`api/webhook.py:42` → `handle_bot_reply`). Inside that
background task, `services/chatbot.py` calls `divar_service.send_message(...)`,
which **re-raises** on any non-2xx response (`services/divar.py:57-71`). There is
no `try/except` around these calls in `handle_bot_reply`, so:

1. A transient send failure (e.g. Divar 500/429) surfaces only as an unhandled
   exception in the background-task runner — invisible to the client (already got
   200) and easy to miss.
2. Worse: the **welcome** send (`services/chatbot.py:245-247`) runs *before* the
   actual intent reply. If the welcome send raises, the function aborts and the
   user's actual answer (price/warranty/etc.) is **never sent** at all.

Wrapping outbound sends so failures are logged (and the welcome-send failure
doesn't abort the substantive reply) makes the bot resilient to transient Divar
errors. This is a correctness fix, not a behavior change on the happy path.

## Assumptions

- `send_message` raising on failure is intentional at the service layer (the
  comments in `services/divar.py:53-56,81-83` confirm "let the error propagate").
  This plan handles that at the *caller* (`handle_bot_reply`), not by changing
  `send_message`.
- It is acceptable for a failed welcome-send to be logged and skipped while the
  intent reply still attempts to send (the welcome is a nicety; the answer is the
  point).
- There is no retry infrastructure to hook into; logging + graceful degradation
  is the intended scope (retries are a separate future improvement).

If any assumption proves false, treat it as a STOP condition.

## Current state

**services/divar.py:47-71** (`send_message` re-raises):
```python
async def send_message(conversation_id: str, text: str) -> bool:
    url = f"{BASE_URL}/v1/open-platform/chat/bot/conversations/{conversation_id}/messages"
    payload = {"type": "TEXT", "text_message": text}
    response = await client.post(url, headers=_api_key_headers(), json=payload)
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError:
        if response.status_code in (401, 403):
            logger.error("send_message auth failed — ...", extra={...})
        else:
            logger.error("send_message failed", extra={...})
        raise
    logger.debug("send_message succeeded", extra={"status_code": response.status_code})
    return True
```

**services/chatbot.py:198-272** (`handle_bot_reply` — the caller with NO guards).
Key send sites, none wrapped in try/except:
- line 227-229: unresolved-conversation send (early return path)
- line 245-247: welcome send (`if is_new:`) — runs BEFORE the intent reply
- line 265: greeting reply send (early return path)
- line 271: main intent reply send (final line)

```python
        # ---- 4. Welcome message on first-in-conversation ----
        if is_new:
            await divar_service.send_message(
                conversation_id, settings.WELCOME_MESSAGE
            )

        # ---- 5. Intent matching & response ----
        normalized_text = normalize_text(user_text)
        intent = _match_intent(normalized_text)
        # ... intent branches build `reply` ...
        await divar_service.send_message(conversation_id, reply)
        logger.info("reply sent", extra={"text": reply})
```

**Repository conventions**:
- Logging via module logger `logger = logging.getLogger("chatbot")` (line 23).
- Errors are logged with `extra={...}` structured fields (see `services/divar.py`).
- `import httpx` is already available in `services/divar.py`; `handle_bot_reply`
  imports `services.divar as divar_service` (line 21).

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Run tests | `pytest` | exit 0, all pass |
| Import check | `python -c "import services.chatbot"` | exit 0 |

(Assumes plan 001's test tooling. If not present, `pip install pytest pytest-asyncio pytest-mock aiosqlite` first.)

## Scope

**In scope** (the only file you should modify):
- `services/chatbot.py` — add a small internal safe-send helper and route the
  outbound sends in `handle_bot_reply` through it

**Out of scope** (do NOT touch):
- `services/divar.py` — `send_message` keeps re-raising by design.
- `api/webhook.py` — the background-task handoff is correct as-is.
- Retry/backoff logic — explicitly deferred (see maintenance notes).

## Git workflow

- Branch: `advisor/004-safe-send`
- Do NOT push or open a PR unless instructed.

## Steps

### Step 1: Add a `_safe_send` helper in services/chatbot.py

Add a module-level async helper (place it just above `handle_bot_reply`, after
the intent helpers around line 195). Target shape:

```python
async def _safe_send(conversation_id: str, text: str) -> bool:
    """Send a message, logging and swallowing send failures.

    handle_bot_reply runs in a FastAPI BackgroundTask after the webhook already
    returned 200, so a raised send error would only surface as an unhandled
    background-task exception. We log it and return False instead, so one failed
    send (e.g. the welcome) never aborts a later, more important send (the reply).
    """
    try:
        await divar_service.send_message(conversation_id, text)
        return True
    except Exception:
        logger.exception(
            "send_message failed in background task",
            extra={"conversation_id": conversation_id},
        )
        return False
```

Note: `logger.exception` records the traceback; do not put the message `text` in
`extra` here (avoid duplicating message-text logging beyond the existing
sanctioned line).

**Verify**: `python -c "import services.chatbot"` → exit 0.

### Step 2: Route the welcome send through `_safe_send` (non-aborting)

Replace the welcome-send block (`services/chatbot.py:244-247`):
```python
        if is_new:
            await divar_service.send_message(
                conversation_id, settings.WELCOME_MESSAGE
            )
```
with:
```python
        if is_new:
            await _safe_send(conversation_id, settings.WELCOME_MESSAGE)
```

This is the key correctness fix: a failed welcome no longer aborts the intent
reply that follows.

**Verify**: `grep -n "send_message(\s*$\|send_message($" services/chatbot.py` —
manual read: confirm the welcome block now calls `_safe_send`.

### Step 3: Route the remaining send sites through `_safe_send`

Replace the other three `await divar_service.send_message(...)` calls in
`handle_bot_reply` with `await _safe_send(...)`, preserving arguments:

1. Unresolved-conversation send (around line 227-229):
   ```python
   await _safe_send(conversation_id, settings.UNRESOLVED_CLIENT_MESSAGE)
   ```
2. Greeting reply send (around line 265):
   ```python
   await _safe_send(conversation_id, reply)
   ```
3. Final intent reply send (around line 271):
   ```python
   await _safe_send(conversation_id, reply)
   ```

Do NOT change the `logger.info("reply sent", ...)` lines — leave them as-is
(they now log intent, which is acceptable; optionally they could be gated on the
return value, but that is not required by this plan).

**Verify**: `grep -c "divar_service.send_message" services/chatbot.py` → `0`
(all direct calls in this file now go through `_safe_send`). Note: `_safe_send`
itself calls `divar_service.send_message`, so if the helper is in this file the
count is `1`. Confirm the only remaining occurrence is inside `_safe_send`.

### Step 4: Run the test suite

```bash
pytest
```

**Verify**: Exit code 0. Existing webhook tests mock `handle_bot_reply` entirely
(`tests/test_webhook.py:60`), so they are unaffected. If plan 007's chatbot tests
exist, they must still pass.

## Test plan

- Add a unit test (in `tests/test_chatbot.py` if it exists from plan 007, else a
  new file `tests/test_chatbot_safe_send.py`) covering:
  - **Welcome-send failure does not abort the reply**: patch
    `services.chatbot.divar_service.send_message` to raise on the first call
    (welcome) and succeed on the second (reply); assert the second call still
    happened. Model DB/session mocking after `tests/test_auth.py`'s async
    in-memory SQLite fixture pattern (`tests/test_auth.py:74-90`).
  - **`_safe_send` returns False and logs on exception**: patch `send_message`
    to raise; assert `_safe_send` returns `False` and does not propagate.
- Verification: `pytest tests/test_chatbot*.py` → all pass, new tests included.

## Done criteria

- [ ] `_safe_send` helper exists in `services/chatbot.py`
- [ ] The welcome send uses `_safe_send` (failed welcome no longer aborts reply)
- [ ] All four outbound sends in `handle_bot_reply` route through `_safe_send`
- [ ] The only remaining `divar_service.send_message(` call in the file is inside `_safe_send`
- [ ] `python -c "import services.chatbot"` exits 0
- [ ] `pytest` exits 0, all existing tests pass
- [ ] New test(s) added and passing (if plan 007 tooling/pattern available)
- [ ] No files outside `services/chatbot.py` (+ its test file) modified (`git status`)
- [ ] `advisor-plans/README.md` row 004 status updated

## STOP conditions

Stop and report back if:

- `handle_bot_reply` or `send_message` no longer matches the "Current state"
  excerpts (drift).
- Making the welcome non-aborting conflicts with an existing test that asserts
  the function raises on welcome failure (report; the test may encode a
  deliberate contract).
- You find `send_message` is also called from other modules that would benefit
  from the same guard — report (do not expand scope; this plan is scoped to
  `handle_bot_reply`).

## Maintenance notes

- Deferred: automatic retry with backoff for transient Divar errors (429/5xx).
  When added, `_safe_send` is the natural seam — wrap the retry there.
- If a dead-letter/alerting mechanism is introduced, `_safe_send`'s except branch
  is where a failed send should be enqueued.
- A reviewer should confirm the welcome-vs-reply ordering fix: the whole point is
  that a failed welcome must not prevent the substantive answer from sending.
