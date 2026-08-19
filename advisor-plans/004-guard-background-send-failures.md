# Plan 004: Guard background-task send failures in `handle_bot_reply`

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `advisor-plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat f5abbbc..HEAD -- services/chatbot.py services/chatbot_conversation.py services/divar.py`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: MED
- **Depends on**: none
- **Category**: bug
- **Planned at**: commit `f5abbbc`, 2026-07-23
- **Retargeted**: 2026-08-20 — the 2026-08-19 module split turned
  `services/chatbot.py` into a re-export shim. The real implementation of
  `handle_bot_reply` now lives in `services/chatbot_conversation.py`. This
  revision updates every file/line reference accordingly; **no change to the
  original diagnosis or fix**. See "Retargeting note" below.

## Retargeting note (read first)

This plan was originally written against `services/chatbot.py` at commit
`f5abbbc`. On 2026-08-19, that file was split into
`services/chatbot_engine.py`, `services/chatbot_conversation.py`,
`services/post_conversation.py`, and `services/oauth_refresh.py`, with
`services/chatbot.py` reduced to a backward-compatible re-export shim
(docstring + re-exports only — see `CHANGELOG.md` 2026-08-19 and
`plans/REFERENCE.md`'s `services/chatbot.py` entry).

**Consequence for this plan:** `handle_bot_reply` now lives in
`services/chatbot_conversation.py`, not `services/chatbot.py`. All edits in
this plan target that file. Per the changelog's explicit caveat, a
`from X import y` re-export binds a *value*, not a live alias — a moved
function resolves its globals against its *own* module. So:

- **Do not** add or patch `_safe_send` on the shim (`services/chatbot.py`) and
  expect it to affect `handle_bot_reply`'s behavior — it won't. The helper
  must be defined in `services/chatbot_conversation.py`, next to
  `handle_bot_reply` itself.
- Any test that monkeypatches `chatbot.divar_service` (the module-object
  re-export) still works, since that one *is* a shared module reference — but
  a test patching a *function* name on the shim (e.g.
  `chatbot._safe_send`) would silently no-op, exactly like the
  `pg_insert`/`AsyncSessionLocal` patch-target issue documented in
  `tests/test_chatbot.py`'s `_patch_session_local` comment. Patch
  `chatbot_conversation._safe_send` if a test ever needs to override it.
- `services/chatbot.py` itself requires **no edit** for this plan — it already
  re-exports `handle_bot_reply` by reference to the (now-fixed) function in
  `services/chatbot_conversation.py`, so `api/webhook.py` needs no changes.

Everything else in the original diagnosis — the ordering bug, the fix shape,
the test plan — is unchanged; only file/line targets moved.

## Why this matters

The webhook returns `200 OK` immediately and hands work to a FastAPI
`BackgroundTask` (`api/webhook.py` → `handle_bot_reply`). Inside that
background task, `services/chatbot_conversation.py` calls
`divar_service.send_message(...)`, which **re-raises** on any non-2xx response
(`services/divar.py`, `send_message`). There is no `try/except` around these
calls in `handle_bot_reply`, so:

1. A transient send failure (e.g. Divar 500/429) surfaces only as an unhandled
   exception in the background-task runner — invisible to the client (already
   got 200) and easy to miss.
2. Worse: the **welcome** send runs *before* the actual intent reply, and
   *before* the state transition is even applied to `conv.current_state` in
   some branches. If the welcome send raises, the function aborts and the
   user's actual answer (price/warranty/etc.) is **never sent**, and — in the
   current code — the state-changing `db.commit()` that follows it never runs
   either, since the exception propagates out before that point.

Wrapping outbound sends so failures are logged (and a welcome-send failure
doesn't abort the substantive reply or the state commit) makes the bot
resilient to transient Divar errors. This is a correctness fix, not a
behavior change on the happy path.

## Assumptions

- `send_message` raising on failure is intentional at the service layer (see
  the comments in `services/divar.py` around `send_message`: "let the error
  propagate"). This plan handles that at the *caller*
  (`handle_bot_reply` in `services/chatbot_conversation.py`), not by changing
  `send_message`.
- It is acceptable for a failed welcome-send to be logged and skipped while
  the intent reply still attempts to send (the welcome is a nicety; the
  answer is the point).
- There is no retry infrastructure to hook into; logging + graceful
  degradation is the intended scope (retries are a separate future
  improvement — note `services/divar.py::send_supplier_message` already has
  its own retry/backoff for the *other* orchestrator, `send_message` does
  not, and this plan does not add one).

If any assumption proves false, treat it as a STOP condition.

## Current state

**`services/divar.py`, `send_message` (re-raises on failure):**
```python
async def send_message(conversation_id: str, text: str) -> bool:
    url = f"{BASE_URL}/v1/open-platform/chat/bot/conversations/{conversation_id}/messages"
    payload = {"type": "TEXT", "text_message": text}

    response = await client.post(url, headers=_api_key_headers(), json=payload)

    try:
        response.raise_for_status()
    except httpx.HTTPStatusError:
        if response.status_code in (401, 403):
            logger.error(
                "send_message auth failed — DIVAR_API_KEY is invalid or missing required scope. "
                "Check DIVAR_API_KEY in .env",
                extra={"status_code": response.status_code, "response_body": response.text}
            )
        else:
            logger.error("send_message failed", extra={
                "status_code": response.status_code,
                "response_body": response.text
            })
        raise

    logger.debug("send_message succeeded", extra={"status_code": response.status_code})
    return True
```

**`services/chatbot_conversation.py`, `handle_bot_reply` (the caller with NO
guards). Key send sites, none wrapped in try/except:**

```python
async def handle_bot_reply(conversation_id: str, user_text: str) -> None:
    ...
    async with AsyncSessionLocal() as db:
        # ---- 1. Resolve conversation → client_id ----
        conv = await _lookup_conversation(db, conversation_id)

        if conv is not None:
            is_new = False
        else:
            resolved = await _resolve_new_conversation(db, conversation_id, user_text)
            if resolved is None:
                logger.info("unresolved conversation", extra={"text": user_text})
                await divar_service.send_message(               # <-- unguarded (1)
                    conversation_id, settings.UNRESOLVED_CLIENT_MESSAGE
                )
                return
            conv, is_new = resolved

        client_id = conv.client_id
        client_id_var.set(str(client_id))

        from services.price_lookup import _cache
        if client_id not in _cache:
            await refresh_lookup_cache(db, client_id)

        # ---- 4. Welcome message + auto-advance on first-in-conversation ----
        if is_new:
            await divar_service.send_message(                   # <-- unguarded (2)
                conversation_id, settings.WELCOME_MESSAGE
            )
            conv.current_state = transition(_state_of(conv), "menu").value

        # ---- 5. Intent matching & response ----
        normalized_text = normalize_text(user_text)
        intent = _match_intent(normalized_text)
        ...
        event = INTENT_EVENTS.get(intent)
        if event is not None:
            conv.current_state = transition(_state_of(conv), event).value

        reply = await generate_chatbot_reply(db, client_id, user_text)
        if is_new and _is_pure_greeting(normalized_text):
            reply = None

        # ---- 6. Persist state, then send ----
        await db.commit()

        if reply is None:
            return

        await divar_service.send_message(conversation_id, reply)  # <-- unguarded (3)
        logger.info("reply sent", extra={"text": reply})
```

There is no `_safe_send` helper anywhere in the codebase today (confirmed by
grep — advisor-plan 004 was never implemented).

**Repository conventions**:
- Logging via module logger `logger = logging.getLogger("chatbot")` at the top
  of `services/chatbot_conversation.py`.
- Errors are logged with `extra={...}` structured fields (see
  `services/divar.py`, `services/post_conversation.py`).
- `services/chatbot_conversation.py` already does
  `import services.divar as divar_service` and
  `from config import settings`.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Run tests | `pytest` | exit 0, all pass |
| Import check | `python -c "import services.chatbot_conversation"` | exit 0 |

(Assumes advisor-plan 001's test tooling. If not present,
`pip install pytest pytest-asyncio pytest-mock aiosqlite` first.)

## Scope

**In scope** (the only file you should modify):
- `services/chatbot_conversation.py` — add a small internal safe-send helper
  and route the outbound sends in `handle_bot_reply` through it

**Out of scope** (do NOT touch):
- `services/divar.py` — `send_message` keeps re-raising by design.
- `services/chatbot.py` — the re-export shim needs no change; it re-exports
  `handle_bot_reply` by reference, so the fix is visible through it
  automatically.
- `services/post_conversation.py` / `handle_post_bot_reply` — that orchestrator
  already has its own try/except around `send_supplier_message` (see
  `services/post_conversation.py`'s `except httpx.HTTPError` block, added in
  the 2026-08-19 timeout/exception-type fix). Do not touch it here; it is a
  separate, already-guarded code path.
- `api/webhook.py` — the background-task handoff is correct as-is.
- Retry/backoff logic — explicitly deferred (see maintenance notes).

## Git workflow

- Branch: `advisor/004-safe-send`
- Do NOT push or open a PR unless instructed.

## Steps

### Step 1: Add a `_safe_send` helper in services/chatbot_conversation.py

Add a module-level async helper (place it just above `handle_bot_reply`).
Target shape:

```python
async def _safe_send(conversation_id: str, text: str) -> bool:
    """Send a message, logging and swallowing send failures.

    handle_bot_reply runs in a FastAPI BackgroundTask after the webhook already
    returned 200, so a raised send error would only surface as an unhandled
    background-task exception. We log it and return False instead, so one failed
    send (e.g. the welcome) never aborts a later, more important send (the reply)
    or the state commit that precedes it.
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

Note: `logger.exception` records the traceback; do not put the message `text`
in `extra` here (avoid duplicating message-text logging beyond the existing
sanctioned line in `api/webhook.py`).

**Verify**: `python -c "import services.chatbot_conversation"` → exit 0.

### Step 2: Route the welcome send through `_safe_send`, and move it after the state write

Replace the welcome-send block:
```python
        if is_new:
            await divar_service.send_message(
                conversation_id, settings.WELCOME_MESSAGE
            )
            conv.current_state = transition(_state_of(conv), "menu").value
```
with:
```python
        if is_new:
            conv.current_state = transition(_state_of(conv), "menu").value
```
i.e. keep the state assignment where it is (it is only an in-memory ORM
attribute set here — the actual `db.commit()` already happens later, once, per
2.6's "single transaction per webhook" rule), and **remove the send call from
this block entirely**. Send the welcome later, alongside the reply, after the
commit — see Step 3. This preserves the existing single-commit invariant
(`CHANGELOG.md` 2026-08-11: "commit-before-send is deliberate") while fixing
the ordering bug: today a failed welcome send raises *before* `conv.current_state`
is even read in the intent-matching step below it, so the whole function
aborts with nothing committed. Moving the send out from between the state
write and the commit removes that failure point from the critical path
entirely.

**Verify**: manual read — confirm no `divar_service.send_message(` call
remains inside the `if is_new:` block that precedes intent matching.

### Step 3: Send welcome + reply together, after commit, both through `_safe_send`

Locate the tail of the function (after `await db.commit()`):
```python
        await db.commit()

        if reply is None:
            return

        await divar_service.send_message(conversation_id, reply)
        logger.info("reply sent", extra={"text": reply})
```

Replace with:
```python
        await db.commit()

        if is_new:
            await _safe_send(conversation_id, settings.WELCOME_MESSAGE)

        if reply is None:
            return

        await _safe_send(conversation_id, reply)
        logger.info("reply sent", extra={"text": reply})
```

This is the key correctness fix: the state transition and the welcome/reply
sends are now fully decoupled by the commit — a failed welcome can no longer
prevent the reply from being attempted, and neither send can prevent the
already-committed state from being persisted (it already was, by this point).

**Verify**: manual read — confirm `is_new` welcome send now happens after
`await db.commit()`, and both remaining sends go through `_safe_send`.

### Step 4: Route the unresolved-conversation send through `_safe_send`

Replace:
```python
                await divar_service.send_message(
                    conversation_id, settings.UNRESOLVED_CLIENT_MESSAGE
                )
                return
```
with:
```python
                await _safe_send(conversation_id, settings.UNRESOLVED_CLIENT_MESSAGE)
                return
```

This path persists nothing (per the 2.1 "unresolved conversations are
stateless" design — see `CHANGELOG.md` 2026-07-05), so there is no commit to
protect here; the only benefit is that a transient Divar failure while
replying to an unresolvable conversation no longer surfaces as an unhandled
background-task exception.

**Verify**: `grep -n "divar_service.send_message(" services/chatbot_conversation.py`
→ zero matches (all direct calls now go through `_safe_send`, and `_safe_send`
itself is the sole remaining caller of `divar_service.send_message`).

### Step 5: Run the test suite

```bash
pytest
```

**Verify**: Exit code 0. `tests/test_webhook.py` mocks `handle_bot_reply`
wholesale, so it is unaffected. `tests/test_chatbot.py` drives
`handle_bot_reply` end-to-end via its `bot` fixture, asserting on
`send_message.await_args_list` — those assertions should be unaffected since
`_safe_send` still calls `divar_service.send_message` with the same
arguments; only the exception-handling wrapper is new. If any existing test
fails, read it before changing it — it may be encoding a contract this plan
should not break (see STOP conditions).

## Test plan

Add unit tests to `tests/test_chatbot.py`, reusing its existing `bot` fixture
and `_patch_session_local` pattern:

- **Welcome-send failure does not abort the reply**: patch
  `chatbot_conversation.divar_service.send_message` to raise on the first call
  (welcome) and succeed on the second (reply); assert the second call still
  happened and the conversation's state was still persisted (verify via a
  fresh session, as the existing tests already do).
- **`_safe_send` returns `False` and logs on exception**: patch
  `divar_service.send_message` to raise; assert `_safe_send` returns `False`
  and does not propagate, and that an ERROR-level log record with
  `conversation_id` was emitted.
- **Reply-send failure is logged but does not raise out of `handle_bot_reply`**:
  patch `send_message` to raise only on the second (reply) call; assert
  `handle_bot_reply` returns normally and the failure is logged.

Follow the existing `_TrackedSessionContext` / `session_factory` patterns
already present in `tests/test_chatbot.py` for DB-session mocking — do not
introduce a new mocking approach.

**Verify**: `pytest tests/test_chatbot.py -k safe_send` (or however the new
tests are named) → all pass; full `pytest` → all pass.

## Done criteria

- [ ] `_safe_send` helper exists in `services/chatbot_conversation.py`
- [ ] The welcome send is moved to after `await db.commit()` and goes through
      `_safe_send` (a failed welcome no longer aborts the reply *or* the state
      commit)
- [ ] The unresolved-conversation send and the final reply send both route
      through `_safe_send`
- [ ] The only remaining `divar_service.send_message(` call in the file is
      inside `_safe_send`
- [ ] `services/chatbot.py` (the shim) is untouched
- [ ] `python -c "import services.chatbot_conversation"` exits 0
- [ ] `pytest` exits 0, all existing tests pass
- [ ] New test(s) added and passing per the Test plan above
- [ ] No files outside `services/chatbot_conversation.py` (+ its test file)
      modified (`git status`)
- [ ] `advisor-plans/README.md` row 004 status updated

## STOP conditions

Stop and report back if:

- `handle_bot_reply` or `send_message` no longer matches the "Current state"
  excerpts (drift beyond the already-accounted-for module split).
- Moving the welcome send after `db.commit()` conflicts with an existing test
  that asserts the welcome is sent *before* the commit, or before some other
  specific point — report; the test may encode a deliberate ordering contract
  this plan's author did not anticipate.
- You find `send_message` is also called from other modules that would
  benefit from the same guard — report (do not expand scope; this plan is
  scoped to `handle_bot_reply` in `services/chatbot_conversation.py`).
- Any test patches `chatbot.divar_service` or `chatbot._safe_send` (the shim)
  expecting it to affect `handle_bot_reply` — per the Retargeting note, this
  would only work for the module-object re-export (`divar_service`), not for
  a function re-export like `_safe_send`. Retarget the patch to
  `chatbot_conversation`, do not add a new export to the shim to route around
  it.

## Maintenance notes

- Deferred: automatic retry with backoff for transient Divar errors (429/5xx)
  on the `NEW_CHATBOT_MESSAGE` path. `services/post_conversation.py` already
  has this for the `NEW_MESSAGE` path via `send_supplier_message`'s
  `RETRYABLE_STATUS_CODES`/`RETRYABLE_EXCEPTIONS` machinery — if the same is
  ever wanted here, `_safe_send` is the natural seam to wrap it in, mirroring
  that design rather than reinventing it.
- If a dead-letter/alerting mechanism is introduced, `_safe_send`'s except
  branch is where a failed send should be enqueued.
- A reviewer should confirm the welcome-vs-reply ordering fix: the whole point
  is that a failed welcome must not prevent the substantive answer from
  sending, *and* must not prevent the state transition from being persisted —
  both of which the pre-fix code got wrong on the welcome-failure path.
- Should `services/chatbot.py` (the shim) ever be retired per its own
  documented follow-up ("Retiring the shim by repointing `api/webhook.py` and
  `tests/test_chatbot.py` at the new modules directly remains available as a
  follow-up" — `CHANGELOG.md` 2026-08-19), this plan's fix requires no further
  changes; it was already written against the real module.