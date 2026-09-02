# Phase 4 

## 4.0 Message Debouncing (Shared: Chatbot + Post Conversations)

> **Must land before §4.1 (AI Integration).** AI calls are slower and more expensive
> than the current keyword router — fragmented multi-message input (see rationale
> below) is a strictly worse problem once `services/ai.py` exists. This section is
> a prerequisite, not an independent feature.

### Rationale

Buyers frequently split one thought across several rapid messages
(`سلام` / `وقت بخیر` / `میتونم سوالا بپرسم` / `تخفیف این محصول چنده`). Both
orchestrators currently process every inbound message immediately and
independently:

- `services/chatbot_conversation.py::handle_bot_reply` — one call per
  `NEW_CHATBOT_MESSAGE` webhook event.
- `services/post_conversation.py::handle_post_bot_reply` — one call per
  `NEW_MESSAGE` webhook event.

This means a 4-message burst produces up to 4 disjointed bot replies, and the
bot never actually sees the buyer's real question in context.

### Design

**DB is the source of truth for WHAT to process. In-memory state is only a
TIMER — never message content.** This makes the debounce layer restart-safe
by construction: a Railway redeploy loses only timing, never data.

```text
Divar webhook (NEW_MESSAGE or NEW_CHATBOT_MESSAGE)
│
▼
persist_buyer_message() ← fast, no AI/HTTP call, returns 200 quickly
│
├─ insert message (dedup logic; NEW for the BOT-conversation system —
│ see 4.0.2)
│
▼
schedule_debounce(conversation_id) ← in-memory timer only
│
(silence ≥ DEBOUNCE_SECONDS, or DEBOUNCE started ≥ MAX_BATCH_WAIT_SECONDS ago)
│
▼
process_pending_batch(conversation_id) ← under a per-conversation asyncio.Lock
│
├─ load all BUYER messages newer than the latest BOT message (DB query,
│ no in-memory buffer — this IS the "batch", computed implicitly)
├─ generate_chatbot_reply(..., message_history=pending)
├─ send via divar_service (send_message / send_supplier_message)
└─ persist BOT message
```


#### Why no `batch_id` column

A "batch" is fully derivable from existing data: **all `sender_type=BUYER` rows
newer than the most recent `sender_type=BOT` row, for one conversation.** No
new table or column is needed on `messages`/`post_messages`. This follows the
project's existing "pre-production simplicity" principle (see `CHANGELOG.md`
2026-06-19 and 2026-08-29 entries) — do not add schema complexity a query can
already express.

#### Why a per-conversation lock, not just a timer

If batch 1 is mid-processing (e.g. `send_supplier_message` retrying for 20s)
and a new buyer message arrives, its own debounce timer must not race batch
1's flush. A `asyncio.Lock` per `conversation_id` serializes flushes:

1. Batch 1's flush acquires the lock, queries pending BUYER messages, replies,
   persists the BOT message, releases the lock.
2. Batch 2's flush (triggered by the new message's own timer) acquires the
   lock *after* batch 1 releases it, re-queries pending BUYER messages — and
   since the BOT message from batch 1 is already persisted, the query
   naturally returns only the messages that arrived during batch 1's
   processing. No manual batch bookkeeping needed.

If the lock is already held when a flush fires, the flush simply waits — it
does not skip or drop anything, since the query re-runs fresh once the lock
is acquired.

### Tasks

#### 4.0.1 — Shared debounce manager (`services/debounce.py`, new)

- [ ] `DEBOUNCE_SECONDS: float` and `MAX_BATCH_WAIT_SECONDS: float` added to
      `config.py` (defaults `3.0` and `10.0` — not hardcoded in the module).
- [ ] Module-level state, scoped to this module only (never imported directly
      by callers — see the abstraction note below):
```python
      _timers: dict[str, asyncio.Task] = {}
      _batch_started_at: dict[str, float] = {}
      _locks: dict[str, asyncio.Lock] = {}
```
- [ ] `async def schedule(conversation_id: str, flush_fn: Callable[[str], Awaitable[None]]) -> None`
      — call on every inbound buyer message, from both orchestrators. Resets
      the timer to `DEBOUNCE_SECONDS` from now, UNLESS
      `now - _batch_started_at[conversation_id] >= MAX_BATCH_WAIT_SECONDS`, in
      which case it schedules an immediate flush (delay `0`) instead of
      resetting. `_batch_started_at` is set on the *first* message of a new
      batch and cleared when the batch actually flushes.
- [ ] `async def flush_now(conversation_id: str, flush_fn) -> None` — used by
      the recovery path (4.0.4) to trigger an immediate, lock-respecting flush
      without going through the timer.
- [ ] The lock (`_locks[conversation_id]`) is acquired inside the scheduled
      task, immediately before calling `flush_fn`, not before scheduling —
      scheduling itself must stay fast and non-blocking.
- [ ] `flush_fn` is supplied by the caller (the orchestrator), not hardcoded
      in this module — `services/debounce.py` must not import
      `chatbot_conversation.py` or `post_conversation.py` (same
      one-directional dependency discipline as `chatbot_engine.py`).
- [ ] Public API deliberately small and implementation-hiding: callers use
      `await debounce.schedule(conversation_id, flush_fn)`, never touch
      `_timers`/`_locks` directly, so a future swap to Redis-backed
      scheduling (not needed now — see "Explicitly deferred" below) does not
      require changing either orchestrator.

#### 4.0.2 — Persist every chatbot buyer message (BOT-conversation system)

> **Confirmed gap:** unlike `post_messages`, the `conversations`/`messages`
> system does not currently persist a row for every inbound buyer text —
> today's `handle_bot_reply` passes only the current `user_text` straight
> into `generate_chatbot_reply`, with no history. This must be fixed as part
> of this section, not deferred.

- [ ] On every inbound `NEW_CHATBOT_MESSAGE` buyer text, insert a `Message`
      row (`sender_type=SenderType.USER`, `text_content=user_text`,
      `divar_message_id` set from the webhook payload's message id for
      dedup — mirroring `PostMessage`'s existing
      `uq_post_messages_divar_message_id` pattern). This makes the
      "BUYER rows newer than the latest BOT row" query
      (see 4.0.2/process_pending_chatbot_batch below) work identically to
      the POST system.
- [ ] Existing dedup-by-`divar_message_id` semantics on `PostMessage` are
      the template — reuse the same `ON CONFLICT DO NOTHING` pattern for
      `Message` here.
- [ ] Confirm `schemas/webhook.py`'s `NewChatbotMessageSchema.id` (already
      present per Phase 1) is what gets used as `divar_message_id` — no
      schema change needed, this field already exists and was previously
      unused for this purpose.

#### 4.0.3 — Split persist vs. process, and rename old entry points

Both orchestrators are restructured so persistence and reply-generation are
separate functions. **The old `handle_bot_reply` / `handle_post_bot_reply`
names are retired outright — not kept as wrappers.** Every caller (webhook,
shim, tests) is updated in the same change; do not leave two parallel
processing paths active.

**`services/post_conversation.py`:**

- [ ] Rename/split into:
      - `persist_buyer_message(conversation_id, post_token, user_text, divar_message_id) -> None`
        — resolves/creates the `PostConversation` row (existing
        `_resolve_post_conversation` logic, unchanged), dedup-inserts the
        buyer `PostMessage` (existing `ON CONFLICT DO NOTHING` on
        `divar_message_id`, unchanged), commits, then calls
        `debounce.schedule(conversation_id, process_pending_post_batch)`.
        Must NOT call `generate_chatbot_reply` or any Divar send — this is
        the fast path the webhook's `BackgroundTasks` invokes directly.
      - `process_pending_post_batch(conversation_id: str) -> None` — the
        flush target. Opens its own `AsyncSessionLocal` (do not reuse a
        session across the debounce delay). Loads the `PostConversation` row,
        then queries all `PostMessage` rows with `sender_type == BUYER` and
        `created_at` after the latest `sender_type == BOT` row's
        `created_at` (or all BUYER rows if no BOT row exists yet). If empty,
        return immediately (another flush already handled it — see the lock
        note above). Otherwise builds `message_history` from those rows
        (oldest-first), calls `generate_chatbot_reply`, sends via
        `send_supplier_message` (existing token-refresh/re-registration/
        retry logic unchanged), persists the BOT message, advances
        `current_state` to `ACTIVE` — all exactly as the old
        `handle_post_bot_reply` did, just relocated and renamed.
- [ ] **Resolve the open session-lifetime issue while rewriting this path**
      (tracked in `CHECKLISTS.md` under Future Improvements): restructure so
      the DB session used for the dedup-insert/history-read/final-commit is
      NOT held open during the `send_supplier_message` HTTP call. Concretely:
      load history and generate the reply inside one session scope, close it,
      call `send_supplier_message` with no session held, then open a fresh
      session only to persist the BOT message + state update. Fix this here
      since the function is being restructured anyway, not as a separate pass.

**`services/chatbot_conversation.py`:**

- [ ] Same split for the BOT-conversation path:
      - `persist_chatbot_message(conversation_id, user_text, divar_message_id) -> None` —
        resolves the conversation (existing `_lookup_conversation` /
        `_resolve_new_conversation` logic, unchanged — including `/start`
        parsing, auto-advance-on-first-contact, and the welcome message,
        which stay tied to conversation *resolution*, not to reply
        generation), inserts the `Message` row per 4.0.2's new dedup logic,
        then calls
        `debounce.schedule(conversation_id, process_pending_chatbot_batch)`.
      - `process_pending_chatbot_batch(conversation_id: str) -> None` — the
        flush target. Queries all `Message` rows with `sender_type == USER`
        and `created_at` after the latest `sender_type == BOT` row's
        `created_at` (same query shape as the POST system, now that 4.0.2
        makes it possible). If empty, return (another flush already handled
        it). Builds `message_history`, calls `generate_chatbot_reply`,
        matches intent/state-machine transitions (existing logic, unchanged),
        sends via `send_message`, persists the BOT `Message` row. The
        auto-advance-on-first-contact welcome send stays in
        `persist_chatbot_message` (conversation resolution), not in this
        flush function — only the *substantive* reply is debounced.
- [ ] `api/webhook.py` changes: `background_tasks.add_task(...)` calls switch
      from `handle_bot_reply` / `handle_post_bot_reply` to
      `persist_chatbot_message` / `persist_buyer_message` respectively. The
      webhook's own logic (auth check, sender/text validation, event-type
      dispatch) is otherwise unchanged.
- [ ] `services/chatbot.py`'s re-export shim (per the 2026-08-19 module-split
      pattern) drops the old names entirely and re-exports only the new
      function names. Every remaining import of `handle_bot_reply` /
      `handle_post_bot_reply` anywhere in the codebase (tests included) is
      updated in this same change — grep for both names before considering
      this task done.
- [ ] `tests/test_webhook.py` — update assertions to expect
      `persist_chatbot_message` / `persist_buyer_message` as the
      `background_tasks.add_task` target, not the old names.
- [ ] `tests/test_chatbot.py` — every direct call to `handle_bot_reply` /
      `handle_post_bot_reply` is replaced with the new two-step flow (call
      `persist_*`, then `process_pending_*_batch` or `debounce.flush_now`
      directly in the test) so assertions still exercise the real reply path
      instead of being silently weakened.

#### 4.0.4 — Testability

- [ ] Debounce delay must be mockable exactly like the existing
      `send_supplier_message` retry backoff pattern (`no_sleep` fixture in
      `tests/test_divar_service.py`): tests patch `asyncio.sleep` (or inject
      a fake clock) so a debounce test does not actually wait 3–10 real
      seconds.
- [ ] New test module `tests/test_debounce.py` covering, at minimum:
      - a single message flushes after `DEBOUNCE_SECONDS` of silence and
        produces exactly one reply;
      - three rapid messages (each resetting the timer) produce exactly one
        reply containing all three as history, not three replies;
      - a message arriving after `MAX_BATCH_WAIT_SECONDS` has elapsed since
        the batch's first message forces an immediate flush instead of
        resetting further;
      - a message arriving *while* a flush is in-flight (lock held) is picked
        up by a second flush after the first releases the lock — i.e. no
        message is lost and no message is double-processed;
      - `process_pending_*_batch` called with nothing pending (e.g. a
        redelivered/duplicate flush trigger) is a safe no-op — no reply sent,
        no error.
- [ ] New tests for 4.0.2 (`tests/test_chatbot.py` or a dedicated module):
      chatbot buyer messages are persisted with dedup-by-`divar_message_id`,
      mirroring the existing `PostMessage` dedup tests.

#### 4.0.5 — Restart recovery

- [ ] In `main.py`'s `lifespan`, alongside the existing `_warm_price_caches()`
      call, add `_recover_pending_conversations()`:
      - Queries both systems for conversations with at least one BUYER
        message newer than the latest BOT message (same query shape as
        `process_pending_*_batch`'s own lookup, run at the conversation-list
        level instead of per-conversation).
      - For each, calls `debounce.flush_now(conversation_id, process_fn)` —
        immediate flush, no `DEBOUNCE_SECONDS` wait, since these messages
        already waited out a restart.
      - Wrapped in try/except so a recovery failure logs and does not block
        app startup (same pattern as `_warm_price_caches`).
- [ ] Recovery must not double-process a conversation that is *not* actually
      stuck — i.e. must only pick up conversations where the buyer message is
      genuinely unanswered, not ones where the previous instance was about to
      reply. This is naturally correct given the "unanswered since last BOT
      message" query — if the previous instance already persisted the BOT
      reply before dying, recovery sees nothing pending.

### Explicitly deferred (do not implement now)

- **Redis-backed debounce.** Not needed at current scale/single-instance
  deployment (per `plans/CHECKLISTS.md`'s existing "Redis-backed rate
  limiting" deferral). The `services/debounce.py` module's public API
  (`schedule`/`flush_now`, keyed by `conversation_id`, taking an injected
  `flush_fn`) is deliberately designed so a future Redis/worker-queue
  implementation can replace the module internals without either
  orchestrator changing a single call site.
- **A `batches` table.** Explicitly rejected in favor of the implicit
  "BUYER messages since last BOT message" query — see rationale above.
  Revisit only if a real need for an explicit batch record (e.g. per-batch
  analytics) emerges later.
- **Cross-instance coordination.** Current deployment is a single Railway
  instance; if multiple replicas are ever introduced, this section's
  in-memory locks/timers stop being safe and must be revisited alongside the
  Redis migration above — do not attempt to make this section
  multi-instance-safe prematurely.

### Acceptance

- [ ] A 4-message rapid-fire burst (like `سلام` / `وقت بخیر` / `میتونم سوالا
      بپرسم` / `تخفیف این محصول چنده`) produces exactly one bot reply, with
      all four messages visible to `generate_chatbot_reply` as
      `message_history` — for BOTH the chatbot and post-conversation systems.
- [ ] A message arriving during an in-flight reply-send is never lost and
      never merged into the batch that already started sending.
- [ ] A simulated process restart with a pending unanswered buyer message
      results in that message being answered shortly after the next startup,
      without manual intervention.
- [ ] Both `NEW_CHATBOT_MESSAGE` and `NEW_MESSAGE` webhook paths use the same
      `services/debounce.py` module — no duplicated debounce logic between
      the two orchestrators.
- [ ] No reference to `handle_bot_reply` or `handle_post_bot_reply` remains
      anywhere in the codebase (source or tests).
- [ ] `pytest` remains green; new tests cover the scenarios in 4.0.4.

## AI Integration (Not Started)

> **Agent rule:** Do not create `services/ai.py` or any LLM imports before this phase.

- [ ] Create `services/ai.py` with `ask_llm(prompt: str, history: list[dict]) -> str`
- [ ] LLM provider: OpenAI-compatible endpoint (configurable via `settings.llm_base_url`)
- [ ] Add to `Settings`: `llm_api_key: str`, `llm_base_url: str`, `llm_model: str`
- [ ] Trigger AI only when state machine returns `FALLBACK` — not for menu-routed intents
- [ ] Per-tenant rate limit: max 20 AI calls / tenant / hour (in-memory, Redis in future)
- [ ] Prompt template in a separate `prompts/` directory, not hardcoded in `ai.py`

# Phase 5 — Interactive Buttons (Not Started)

> **Agent rule:** Do not begin until `PLAN.md`'s Active Phase reads `Phase 3`.

- [ ] Build `build_button_payload(labels: list[str]) -> dict` utility
- [ ] Send buttons via Divar message payload structure (refer to Divar API docs)
- [ ] Handle `button_click` action type in webhook alongside text messages — this is why
      `schemas/webhook.py` was given the `new_chatbot_message.type` field back in Phase 1;
      use it here to distinguish `TEXT` from button-click events
