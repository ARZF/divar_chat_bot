# Changelog

> Full dated decision history. Not read cover-to-cover by default — consult when a
> phase file or REFERENCE.md points here for evidence behind a specific claim, or
> spot-check a specific date/topic.

- **2026-08-30 (step 21: listing read/sync/availability APIs; presence split
  from availability)** — The three seller listing endpoints land, and the
  `is_available` conflation is resolved.

  - **Schema: new `posts.present_on_divar` column** (baseline `0001` only — no
    `0002`; the DB is recreated from the baseline, so changes fold in).
    Maintainer directive: three concepts were conflated under one boolean —
    (1) listing existence on Divar, (2) product sold/unsold, (3) chatbot
    enabled/disabled. Resolution:
    - `present_on_divar` — listing existence on Divar. **Written only by
      `services/divar_listings.py`** (sync): present in the user-posts
      response → True; absent from a sync → False (scoped to the syncing
      client only).
    - `is_available` — the seller's own chatbot on/off toggle (§3.8.4).
      **Written only by the PATCH endpoint.** Sync never touches it, so a
      manual toggle survives every sync.
    - "Sold" deliberately has **no posts field** — chatbot answers about
      products derive from the seller's products catalog (maintainer:
      "catalog is enough").
  - **Conversation resolution now requires BOTH flags.**
    `chatbot_conversation._resolve_new_conversation` (start touchpoint) and
    `post_conversation.handle_post_bot_reply` (NEW_MESSAGE webhook) resolve a
    post_token only when `present_on_divar AND is_available`; otherwise the
    token is treated exactly like an unregistered one (silent skip — no
    leak, no error). Before this step `is_available` had zero readers (both
    resolution sites selected only `client_id`), so redefining it changed no
    runtime behavior.
  - **`GET /api/v1/seller/listings`** — paginated (page/page_size 1..100,
    mirrors the products list), tenant-scoped via JWT, ordered
    `created_at DESC, post_token ASC`. Returns post_token, title, category,
    chat_enabled, is_phone_hidden, is_available, present_on_divar,
    last_synced_at — never `client_id`, never price/status/url (unsupported
    per the step 19 matrix). **Never calls Divar**: rate limits are per-app
    (docs/scopes/README.md), so sync-on-read would let one seller's dashboard
    polling burn the quota all sellers share. OTP-only sellers get an honest
    empty list, not an error.
  - **`POST /api/v1/seller/listings/sync`** — the explicit refresh trigger
    (the counterpart to the read endpoint's read-only design; the seller
    decides when to spend the one user-posts GET). `skipped` (OTP-only or
    refresh failure) writes nothing; a Divar outage maps to 502 with no
    writes.
  - **`PATCH /api/v1/seller/listings/{post_token}/availability`** — §3.8.4.
    Body `{"is_available": bool}`; lookup is always
    `post_token AND client_id`, so missing and cross-tenant return the same
    non-leaking 404 (§3.14). Sets only `is_available`; never calls Divar.
  - **Test note:** Pydantic v2 lax mode coerces `1`/`"yes"` to `True` for a
    `bool` field, so those are valid PATCH bodies, not 422s — the validation
    test uses payloads that genuinely fail (`{}`, `"maybe"`, `[True]`).
  - **Deferred, not forgotten:** image upload (§3.8.5) is out of scope for
    step 21, as the step text itself specifies.

- **2026-08-29 (step 20: Divar listing sync; POST /seller/posts retired)** —
  Listings now come from Divar, not from manual token registration.

  - **`POST /seller/posts` removed** (endpoint, `PostRegisterRequest`/
    `PostRegisterResponse`, its two tests). From this step on, a seller's
    `post_token` rows enter `posts` only via
    `services/divar_listings.sync_listings`, and only after the seller has
    completed "Sign in with Divar" (OAuth) at least once — OTP-only sellers
    have no `oauth_tokens` row, so sync is a no-op for them. The
    `ON CONFLICT (post_token) DO NOTHING` ownership pattern the endpoint used
    moved into the sync service unchanged: a token already owned by another
    client is never stolen.
  - **`services/divar_listings.py` (new):** one GET to
    `/v1/open-platform/finder/user-posts` per sync (no per-post enrichment
    calls). Posts present in the response are inserted or metadata-refreshed
    (`title`, `category`, `is_phone_hidden`, `chat_enabled` ←
    `supplier_chat_assistant_enabled`, `last_synced_at`) with
    `is_available = True`. Posts *owned by the syncing client* that the
    response no longer returns get `is_available = False`; rows of other
    clients are never touched (the update is scoped to `client_id`, and the
    empty-response case marks only that seller's own posts). A failed
    fetch/refresh aborts the sync before any write — a Divar error is never
    mistaken for "the seller has no listings". Token refresh reuses
    `oauth_refresh._refresh_supplier_token`. Maintainer decision: absent-from-
    sync ⇒ unavailable, per the approvals of 2026-08-29.
  - **OAuth scope:** `/oauth/start` now requests `USER_POSTS_GET` (sixth
    scope) so the sync's access token can read the seller's posts. The
    Pre-Production Checklist scope-approval ticket was updated to include it.
  - **Plan-text deviation, maintainer-approved:** PHASE3_EXECUTION.md step 20
    and PHASE3.md §3.8.2 say "never repurpose `posts`" / prefer a separate
    `listings` table. Superseded by the same-day decision to fold the listing
    columns into `posts` via the squashed baseline migration (see entry above)
    — re-splitting would contradict the approved squash. `posts`' conversation-
    resolution role is unchanged; the sync only adds nullable metadata.
  - **Deferred to step 21:** any route/trigger invoking `sync_listings` (listing
    read API, availability PATCH, UI). Step 20 ships the service + tests only.

- **2026-08-29 (migration history squashed into a single baseline)** — Deleted the
  five Alembic migrations (`0001_initial_schema`, `0002_shrink_post_token`,
  `0003_make_conversation_state_required`,
  `0004_globally_unique_divar_conversation_id`,
  `0005_add_post_conversation_memory`) and replaced them with ONE baseline
  `0001_initial_schema` (`down_revision = None`) that creates the entire current
  schema in a single `upgrade()`, including step 20's Divar-sourced listing
  columns on `posts` (`title`, `category`, `chat_enabled`, `is_phone_hidden`,
  `last_synced_at` — all nullable, written only by `services/divar_listings.py`).

  **Why safe:** no migration in the old chain has ever run against a real
  production database. The project is pre-production (the Pre-Production
  Checklist is fully unchecked) and the database is wiped and recreated on every
  redeploy, so no `alembic_version` row anywhere points at the deleted revision
  IDs. Maintainer confirmed this directly on 2026-08-29; the repo corroborates
  (no Railway/CI deploy configs checked in; deployments run
  `alembic upgrade head` on Railway against a database that is recreated, not
  migrated forward from an old chain).

  **⚠️ Do not repeat this** once a real production deployment exists: squashing
  then would strand every deployed `alembic_version` row and require manual
  stamping on each environment. From that point on, only additive migrations on
  top of the baseline.

  **Verification:** structural, not live-Postgres. (1) An
  `alembic upgrade head` → `alembic downgrade base` round-trip against a
  throwaway SQLite database (the JSONB columns compile there via a
  `.with_variant(sa.JSON(), "sqlite")` that renders plain JSONB on Postgres);
  all ten tables, both `conversations` UNIQUE constraints (the composite
  ON CONFLICT target AND the global one from old 0004), all indexes and
  server_defaults verified present, downgrade drops everything. (2) A manual
  column/constraint/index/enum diff of the new file against the five deleted
  migrations' cumulative state and the model files. It was **not** verified
  against a live Postgres instance — the first `alembic upgrade head` run on
  Railway's Postgres after this change ships is the real verification moment.

  Note for readers of earlier entries: references below to migrations `0003`
  and `0004` (2026-08-09, 2026-08-13) describe the now-deleted pre-squash
  files; their schema effects live on in the squashed baseline. Live-code
  comments that cited "migration 0004" by number were reworded to cite the
  constraint name (`uq_conversations_divar_conversation_id`) instead.

- **2026-08-20 (advisor-plans archived and removed)** — Deleted the `advisor-plans/`
  directory (7 plans + its `README.md`). These were **advisor-authored improvement
  plans**, deliberately kept separate from this project's own phased plan in `plans/`;
  all 7 have now been executed and marked DONE, so the directory carried no remaining
  work and its summaries are preserved here instead.

  - **001 — Declare test/dev dependencies and add a one-command test runner.** The
    suite existed but had no reproducible way to install or run it: `requirements.txt`
    listed production deps only, and every test file repeated ~12 inline
    `os.environ.setdefault` lines. Added a test-dep section plus root `pytest.ini`
    (`asyncio_mode = auto`) and `conftest.py` holding the shared env defaults.
    **DONE** (2026-07-28), with higher pins than planned (`pytest==9.1.1`,
    `pytest-asyncio==1.4.0`, `pytest-mock==3.15.1`, `aiosqlite==0.20.0`) which also
    killed ~5000 `get_event_loop_policy` DeprecationWarnings.
  - **002 — Fix CORS wildcard origin combined with credentials.** `main.py` used
    `allow_origins=["*"]` together with `allow_credentials=True`; the CORS spec forbids
    this and Starlette responds by reflecting the request `Origin`, so any site could
    drive credentialed requests against the seller auth API (which sets an HTTP-only
    refresh-token cookie). Replaced with a configurable `CORS_ALLOWED_ORIGINS: List[str]`
    setting in `config.py`, defaulting to `[]` (no cross-origin browser access).
    **DONE**.
  - **003 — Remove resolution debug/fallback scaffolding.** A leftover
    `logger.warning("RESOLVE DEBUG", ...)` fired at WARNING level on the hot
    `_resolve_new_conversation` path, dumping `user_text` and config on every
    unresolved message. With maintainer approval the scope was **expanded** beyond the
    log: the undocumented `EXPERIMENTAL_CLIENT_ID` bypass, its operational warning, its
    `config.py` setting, and its `.env.example` entry were all removed too, after real
    `Client`/`Post` fixtures and `/start MY_POST`/`DEMAND_POST` resolution tests were
    added first. **DONE — expanded and subsumed by the §2.1 hardening.**
  - **004 — Guard background-task send failures in `handle_bot_reply`.**
    `send_message` re-raises on non-2xx, and `handle_bot_reply` runs in a FastAPI
    `BackgroundTask` after the webhook already returned 200, so a transient Divar error
    only surfaced as an unhandled background-task exception — and worse, a failed
    *welcome* send (which ran between the state write and the commit) aborted both the
    substantive reply and the state transition. Added `_safe_send` and moved the welcome
    to after `db.commit()`. **DONE** — retargeted to `services/chatbot_conversation.py`
    because the 2026-08-19 module split moved `handle_bot_reply` out of
    `services/chatbot.py`.
  - **005 — Remove the dead `admin_token` setting.** After §2.7 moved seller endpoints
    to JWT `get_current_client_id()`, no source read `settings.admin_token`; it survived
    only as a *required* `Settings` field plus the test boilerplate that existed solely
    to satisfy it at import time. Removed from `config.py` and from the test env setup,
    as `plans/CHECKLISTS.md` had already called for. **DONE**.
  - **006 — Add a committed `.env.example` template.** A `.env` is required at startup
    (several required, no-default settings, some secret), but the only way to discover
    the variable list was to read `config.py`. Added a placeholder-only `.env.example`
    plus a `!.env.example` negation in `.gitignore` (needed because `.env.*` was
    ignored). No real secrets, no runtime impact. **DONE**.
  - **007 — Add test coverage for the chatbot intent router.** `services/chatbot.py` was
    the core product logic — it decides what the bot says to every customer — yet no test
    referenced it. Added `tests/test_chatbot.py` covering `parse_start_message`,
    `_match_intent`, `_is_pure_greeting`, `_extract_product_name`, and the price-reply
    branches, seeding the price cache the way `tests/test_price_lookup.py` does.
    **DONE**; the plan text ended up stale on one point — `_handle_price_intent` is now
    async with signature `(db, client_id, text)`.

  The full text of each plan remains recoverable from `git log` / commit history at its
  former path, `advisor-plans/00X-*.md` (e.g.
  `git show HEAD~1:advisor-plans/004-guard-background-send-failures.md`).
- **2026-08-19 (supplier-message timeout + exception-type fix)** — Closed the two defects
  behind the production incident where a single buyer message spent **~4 minutes** in
  `send_supplier_message` retries and then surfaced as Starlette's bare
  `ERROR: Exception in ASGI application` instead of our structured logs. Both causes were
  confirmed by reading the source, not inferred from logs.

  **Root cause 1 — shared client had a flat 60s timeout.** `main.py`'s lifespan built
  `httpx.AsyncClient(timeout=60)`, and `httpx` applies a bare number to **all four** phases
  (connect/read/write/pool). No call site in `services/divar.py` overrides it per request,
  so every one of `send_supplier_message`'s 4 attempts inherited a 60s ceiling —
  4 × 60s + backoff ≈ 4 minutes for a connect-timeout cycle.

  **Root cause 2 — `handle_post_bot_reply` caught the wrong exception type.**
  `services/post_conversation.py` caught only `httpx.HTTPStatusError`, but
  `send_supplier_message` re-raises the **original** exception after exhausting retries.
  For a transport failure that is `httpx.ConnectTimeout` (or the other members of
  `RETRYABLE_EXCEPTIONS`: `NetworkError`/`ReadTimeout`/`RemoteProtocolError`), none of
  which are `HTTPStatusError` — so it escaped the `BackgroundTask` entirely. The `except`
  clause's assumption that supplier-message failures always arrive as an HTTP *status*
  error was wrong for precisely the case `RETRYABLE_EXCEPTIONS` exists to handle.

  **The fixes.** `DIVAR_CLIENT_CONNECT_TIMEOUT_SECONDS` (default **5.0**) and
  `DIVAR_CLIENT_TOTAL_TIMEOUT_SECONDS` (default **15.0**) were added to `config.py` and
  `.env.example`; the lifespan now builds `httpx.Timeout(TOTAL, connect=CONNECT)`. The
  `except` widened to `httpx.HTTPError` — verified against the installed **httpx 0.28.1**
  as the common base of `HTTPStatusError` *and* `RequestError`/`TransportError`, so it
  covers both shapes — with `status_code` logged as `None` when there is no response, plus
  the error string. Deliberately **not** `except Exception`: a bug in the
  `generate_chatbot_reply` call earlier in the same function must still crash loudly.

  **Retry budget after the change** (documented in a comment next to `MAX_RETRIES` in
  `services/divar.py`, which previously said nothing about it): backoff is unchanged at
  `(1 + 2 + 4) + 3 × jitter ≤ 7.75s`, so with `MAX_ATTEMPTS = 4` the worst case is
  **≤ ~68s** (4 × 15s read) and **≤ ~28s** for the connect-timeout case (4 × 5s) — down
  from ~4 minutes.

  **Shared-client blast radius — verified, not assumed.** The same client is used by
  `send_message`, `get_conversation`, `get_user`, `refresh_access_token` and
  `register_event_subscription`; none override the timeout, so all five moved from 60s to
  the new values. None are expected to have a slow TCP/TLS connect under normal operation,
  and the `NEW_CHATBOT_MESSAGE` path (`services/chatbot_conversation.py` → `send_message`)
  is covered by a test asserting the settings-derived timeout reaches the outgoing request.

  **Tests.** Four added: two asserting the lifespan's client timeout is sourced from
  `settings` (one inspecting the constructed `httpx.Timeout`, one end-to-end via a settings
  override on a real outgoing request), and two on `handle_post_bot_reply` covering the
  `ConnectTimeout` branch (nothing propagates, one ERROR with `client_id`/`conversation_id`/
  `status_code: None`, `rollback()` called) and the `HTTPStatusError` branch as a regression
  guard (real status code preserved, `rollback()` still called). Mutation-checked: all three
  behavioral tests fail against the pre-fix code, with `ConnectTimeout` escaping exactly as
  in production. Suite **179 → 183 passed**.

  **Known gap, explicitly out of scope.** A message that exhausts all 4 attempts is now
  logged with full context, but there is still **no redelivery or dead-letter mechanism** —
  the buyer gets no reply and the seller gets no alert. Recorded under
  `CHECKLISTS.md` → Future Improvements. Also untouched: `_refresh_supplier_token`, and
  the intermittent Divar TLS-handshake timeout itself (external network condition).

- **2026-08-19 (chatbot.py module split)** — Split the 714-line `services/chatbot.py` into
  four focused modules. **Pure internal reorganization: no behavior, signature, log message,
  or SQL change.** Every function was moved verbatim.

  **What moved where.**
  - `services/chatbot_engine.py` (145 lines) — the shared reply engine both orchestrators
    call: `_match_intent`, `_is_pure_greeting`, `_extract_product_name`,
    `_handle_price_intent`, `generate_chatbot_reply`.
  - `services/chatbot_conversation.py` (291 lines) — BOT-conversation
    (`NEW_CHATBOT_MESSAGE`) orchestration: `TOUCHPOINT_NAMES`, `parse_start_message`,
    `_lookup_conversation`, `_resolve_new_conversation`, `_state_of`, `handle_bot_reply`.
  - `services/post_conversation.py` (253 lines) — POST-conversation (`NEW_MESSAGE`)
    orchestration: `_resolve_post_conversation`, `_load_post_message_history`,
    `handle_post_bot_reply`.
  - `services/oauth_refresh.py` (84 lines) — `_refresh_supplier_token`.

  **Dependency direction.** Both orchestrators depend on `chatbot_engine`; `chatbot_engine`
  depends on neither, and the two orchestrators never import each other. This is the same
  one-directional rule as the services → models discipline behind the `ConversationState`
  move (see 2026-08-16 below). Verified by AST inspection, not just by reading.

  **The re-export shim.** `services/chatbot.py` (36 lines) was kept, reduced to a docstring
  plus re-exports of all 14 previously-public-and-private names, so `api/webhook.py` keeps
  importing `handle_bot_reply`/`handle_post_bot_reply` from `services.chatbot` unchanged.
  The split is therefore mechanical from every caller's point of view.

  **Caveat the shim does NOT cover — important for future test authors.** A
  `from X import y` re-export binds a *value*, not a live alias, and a moved function
  resolves its globals against its own module. So `monkeypatch.setattr(chatbot, "name", ...)`
  silently becomes a **no-op** for the relocated implementations: the attribute is rebound on
  the shim while the real call site keeps using the original. `tests/test_chatbot.py`
  patched four such names, so those patches were retargeted onto the owning modules
  (`pg_insert` and `AsyncSessionLocal` now have to be patched in *every* module that imports
  them — two and three modules respectively; helper `_patch_session_local` and the
  `sqlite_upsert` fixture do this, and both carry a comment saying why it is not redundant).
  Only patch *targets* changed — no assertion, fixture logic, or test structure was touched.
  Confirmed load-bearing by a mutation check: pointing those patches back at the shim
  produces 12 failures + 9 errors, so they are genuinely in effect rather than passing
  vacuously. Suite is **179 passed before and after**, identical.

  `chatbot.divar_service` is deliberately re-exported as a *module object* rather than a
  value — patching an attribute on it mutates the one shared `services.divar` module, so
  the many existing `monkeypatch.setattr(chatbot.divar_service, ...)` calls still work.

  **Deliberately not done.** Callers were not migrated off the shim, and `PLAN.md`'s Active
  Phase / `STATUS.md`'s completion claims were untouched — this was a file-organization
  change, not a phase-scope change. Retiring the shim by repointing `api/webhook.py` and
  `tests/test_chatbot.py` at the new modules directly remains available as a follow-up.

- **2026-08-16 (`sent_at` type correction)** — Closed the **`sent_at` type mismatch**
  flagged as a real finding inside `test_realistic_divar_webhook_payload`'s docstring.

  **The finding.** `docs/events/chat.md` documents `ChatMessage.sent_at` as `Timestamp
  (int64)` — Divar's live payloads send it as a large microsecond integer (e.g.
  `1729429926140000`). `schemas/webhook.py` had declared `NewChatbotMessageSchema.sent_at`
  as `datetime` while `ChatMessage.sent_at` stayed `int`, an inconsistency between the two
  otherwise-identical message shapes (`ReadMe.md` specifies both `new_message` and
  `new_chatbot_message` carry the same `ChatMessage` type). The existing test had already
  worked around this by feeding an ISO 8601 string instead of the real integer format,
  masking rather than fixing the mismatch.

  **The fix.** Both `NewChatbotMessageSchema.sent_at` and `ChatMessage.sent_at` are now
  `datetime`. Confirmed Pydantic v2 parses **both** representations Divar could plausibly
  send — the real microsecond integer and an ISO 8601 string — into a valid `datetime`
  without error, so this is a safe type-widening, not a behavior change on the wire. The two
  message schemas are now structurally identical again, matching the docs.

  **Deliberately not done.** No source outside `schemas/webhook.py` was audited yet for code
  that assumes `sent_at` is a raw `int` (e.g. arithmetic, storage, logging). Flag as a
  follow-up if such a call site turns up — it would now receive a `datetime` object instead.

- **2026-08-16 (refresh-token fix)** — Fixed the **`refresh_access_token()` per-seller
  defect** recorded as open in the entry below, wired the **mandatory event re-registration**
  that was blocked behind it, and closed the concurrency hole the fix exposed.

  **The defect.** `refresh_access_token()` read `settings.DIVAR_REFRESH_TOKEN` from `.env`
  while its only caller, `handle_post_bot_reply`, persisted the returned pair onto a
  specific seller's `oauth_tokens` row. Every per-seller refresh was therefore attempted with
  the global bootstrap credential, and its result overwrote that seller's stored tokens.

  **The fix.** The signature is now
  `refresh_access_token(current_access_token, refresh_token)` — no `settings` read remains in
  the function, and the docstring states that both arguments must belong to the same seller,
  since Divar rotates the refresh token on every call. The refresh/persist logic moved out of
  `handle_post_bot_reply` into `services/chatbot.py::_refresh_supplier_token(client_id)
  -> Optional[str]`, returning `None` to mean "refresh failed, send nothing." The caller
  shrank to a four-line call, so the expired-token branch now has one owner.

  **Concurrency, fixed in the same pass rather than deferred.** Two buyer messages arriving
  together for a seller with an expired token spawn two background tasks. Because Divar
  rotates *and invalidates* the refresh token on every call, both refreshing would leave
  whichever pair lost the write permanently unusable — that seller could never refresh again,
  with nothing surfaced anywhere. `_refresh_supplier_token` claims the row with
  `SELECT ... FOR UPDATE` and **re-checks the expiry under the lock**, so a task that waited
  reuses the winner's token rather than burning a second rotation. Same philosophy as the
  2026-08-13 `delete(...).returning(...)` claim on app-session refresh tokens: make the race
  impossible in SQL instead of defending against it afterwards.

  **Event re-registration.** `_refresh_supplier_token` calls
  `register_event_subscription(new_access_token)` after committing, outside the lock. Failure
  is logged as a warning and swallowed — the buyer's reply still goes out. This closes §2.9's
  last "mandatory, recurring" item **for the one refresh path that exists**; a future refresh
  *scheduler* must call it too, since the obligation is per-refresh, not per-code-path. The
  two stale `TODO`s (one in `api/oauth.py`, one in `chatbot.py`) are gone.

  **Test evidence — 163 passed** (from 159 passing + 2 failing before this pass; the venv
  needed for a runnable suite is created under `.venv/`, which is gitignored). Each change
  was verified to actually be covered by deliberately reverting it: restoring the
  `settings.DIVAR_REFRESH_TOKEN` read fails both `refresh_access_token` tests, and disabling
  the re-registration call fails both supplier-refresh tests. New/updated tests assert the
  seller's own refresh token reaches the request body, that it differs from the global
  setting, that re-registration happens with the new token, and that a failed
  re-registration does not block the reply.

  **Known testing limitation — do not read the concurrency coverage as proof.** The suite
  runs on SQLite, which **silently drops `FOR UPDATE`** from the compiled statement (verified
  by compiling the same `select()` against both dialects: absent on SQLite, present on
  PostgreSQL). A two-task `asyncio.gather` test was written, observed to fail with
  `refresh.await_count == 2`, and then **deliberately removed** rather than weakened into
  something that passed for the wrong reason — on SQLite it could never demonstrate
  serialization. What replaced it: a dialect-level test pinning that the statement compiles to
  `... FOR UPDATE` on PostgreSQL and that `.with_for_update()` remains in the source, plus a
  test driving the woken-up-loser branch directly. **The lock's real behaviour under
  PostgreSQL remains unverified** — worth an integration check when a live DB is available.

  **Deliberately not done.** `settings.DIVAR_ACCESS_TOKEN` and `settings.DIVAR_REFRESH_TOKEN`
  are now read by no source code at all. Removing them touches every deployment's `.env`,
  `.env.example`, `conftest.py`, and five test modules — not appropriate inside a bug-fix
  commit, so it is logged in `CHECKLISTS.md` under Config Cleanup beside the existing
  `admin_token` item. The `/oauth/dev/*` bootstrap routes only *print* tokens for manual
  `.env` pasting and never read these settings, so that cleanup will not break the tool.

- **2026-08-16 (§2.9 implementation + commit audit)** — Built out **supplier-wide chat
  messaging** across five commits (`1e89184`, `cfcd4c1`, `182d915`, `593453b`, `167658f`),
  then audited those commits against `docs/` and the plan files. §2.9 is now
  **substantially implemented but not complete** — see its status note for the three
  remaining items.

  **What landed.** The real `/oauth/start` scope string gained
  `CHAT_SUPPLIER_ALL_CONVERSATIONS_MESSAGE_SEND` and `CHAT_SUPPLIER_ALL_CONVERSATIONS_READ`.
  `services/divar.py` gained `send_supplier_message()` (v2 endpoint, `message` body field,
  `_oauth_headers`) and `register_event_subscription()` (`{"event_type":
  "NEW_MESSAGE_ON_POST"}`, no `event_resource_id`). `schemas/webhook.py` gained the
  `NEW_MESSAGE` enum member and the `new_message` field; `api/webhook.py` dispatches on
  `payload.type` and drops non-`BUYER` senders. `services/chatbot.py` gained
  `handle_post_bot_reply`, which resolves `post_token → posts.client_id` and sends the
  seller-authorized reply. `/oauth/callback` registers the subscription after login.
  Verified against docs: the endpoint, body field, and auth of `send_supplier_message` match
  `docs/chat/users_conversations.md`; omitting `event_resource_id` to mean "all posts" matches
  `docs/events/ReadMe.md`.

  **Open question resolved: unresolved `post_token`.** One of the two questions left open in
  the 2026-07-2X entry is now decided as specified — log a warning with `post_token` and
  `conversation_id`, send no reply. Because resolution happens inside the background task,
  the webhook's 200 is already returned before the lookup runs, so no redelivery is
  triggered. The other question (`/oauth/dev/start` scopes) remains open, and it also
  contradicts §2.9's own checkbox, which states it as a decided task rather than a question.
  Left unresolved rather than silently picking a side.

  **Deliberate deviations, recorded so they aren't re-flagged.** `api/webhook.py` uses two
  sequential terminal `if` blocks rather than the `if`/`elif` shown in §2.9 — behaviourally
  identical. §2.9 named the payload model `WebhookPayload`; it is actually `WebhookSchema`.
  A failed post-login subscription registration is logged and swallowed rather than failing
  the login, with no retry — so an affected seller receives no events until a later
  registration succeeds.

  **`expires_in` fix (`167658f`).** `refresh_access_token()` now returns the real
  `expires_in` from the token response as a third tuple element, and
  `handle_post_bot_reply` computes `token_expires_at` from it instead of hardcoding 7 days.
  This aligns with the 2026-07-20 live-test finding that `expires_in` was `604800`, not the
  documented `3600`, and with §2.3's "never hardcode 3600" note.

  **Open defect found by the audit — `refresh_access_token()` is not per-seller.** The
  function takes the current access token as a parameter but still reads
  `settings.DIVAR_REFRESH_TOKEN` from `.env` for the request body, while its only
  per-seller caller persists the result onto that seller's `oauth_tokens` row. Any seller
  with an expired access token is therefore refreshed against the global bootstrap token,
  and the returned pair overwrites their stored credentials. `REFERENCE.md` had already
  warned this pattern "cannot continue" once tokens went per-client. `167658f` fixed the
  return arity, not the input — separate concerns. **Not fixed; under investigation.** The
  mandatory event re-registration on refresh is blocked behind it, since both hang off the
  same call site. Full write-up and the questions to settle are in PHASE2.md §2.9.
  > **Superseded — fixed later the same day; see the refresh-token-fix entry above.**

  **Open question — scope encoding.** `urlencode(params)` defaults to `quote_plus`, so the
  authorize URL emits `scope=USER_PHONE+USER_ID+...` while `docs/oauth/ReadMe.md` specifies
  space or `%20` and never shows `+`. Predates §2.9 (also affects `/oauth/dev/start`) and has
  never been observed to fail — Divar's OAuth server appears to be Ory, whose Go query parser
  decodes `+` as a space. Flagged, not changed: verify against the live authorize endpoint
  before touching it.

  **Also updated.** `EVENTS_REGISTER_SUBSCRIPTION` added to the Pre-Production API-key
  permission table, and the two new scopes added to the OAuth scope-approval item, with a
  note that they are materially broader than the login scopes and will be reviewed
  separately. Corrected there too: `docs/scopes/README.md` is a rate-limit/quota doc despite
  its name, and no complete scope registry exists in the docs —
  `CHAT_SUPPLIER_ALL_CONVERSATIONS_READ` is documented only in `docs/events/ReadMe.md`'s
  event table, and `..._MESSAGE_SEND` only in `docs/chat/users_conversations.md`. Both are
  confirmed flat scopes with no `IDENTIFIER`.

  **Test evidence.** None gathered during the audit itself: `python -m pytest` failed at
  collection for all six test modules with `ModuleNotFoundError: No module named 'httpx'`
  (dependencies were not installed in that environment). **Resolved in the refresh-token-fix
  pass above**, which created a local `.venv` and ran the suite — the baseline for these five
  commits was **159 passing, 2 failing**, both failures being tests that pinned the old
  `refresh_access_token` signature.

- **2026-08-16** — Closed the **models → services inverted-layering item** left open in
  the 2026-08-11 §2.6 entry, and verified that the enum move produces no schema drift.

  **Dependency correction.** `ConversationState` was moved verbatim from
  `services/state_machine.py` to the new `models/enums.py`. `models/conversation.py` now
  imports only from `models.enums`; the model layer no longer imports any `services.*`
  module. This restores the project's dependency direction: services → models, never the
  reverse, removing the latent import-cycle risk that was expected to surface first during
  Alembic autogenerate.

  **Backward compatibility.** `services/state_machine.py` imports and re-exports
  `ConversationState` from `models.enums`. Existing importers in `services/chatbot.py` and
  `tests/test_chatbot.py` therefore required no changes, and the transition table continues
  to use the same enum members and values. `TRANSITIONS` and `INTENT_EVENTS` were not
  changed.

  **Schema verification.** A live PostgreSQL autogenerate check was not possible in this
  environment: the configured database is `postgresql+asyncpg://divar:divar@localhost:5432/divar`,
  but PostgreSQL was unreachable and Docker was unavailable. The required static fallback
  was run instead. The current SQLAlchemy metadata reports `Conversation.current_state` as
  `String(50)`, `nullable=False`, Python-side default `'START'`, and `server_default=None`.
  The `current_state` definition in the pre-move and post-move model source is identical.
  Migration history remains unchanged with `0004` (`globally_unique_divar_conversation_id`)
  as the expected head. No throwaway or committed migration was generated.

  **Test evidence.** The enum-move commit's verification remains valid: the full suite
  passed with **151 tests**, and the enum identity check confirmed that the model import,
  `models.enums`, and the `services.state_machine` re-export resolve to the same enum object.
  The focused state-machine and integration checks also passed. This closes the 2026-08-11
  open layering item. The separate `services/state_machine.py` tree-drift note in that older
  entry is historical and unrelated to this correction; it remains as written.

- **2026-08-13** — Fixed two **§2.2 conversation-resolution defects** found in the Phase 2
  audit, plus the schema correction the second one needed.

  **(1) Double-welcome race — the checked box was only half-implemented.** §2.2 says the
  upsert must be *"checked for whether it actually inserted a row."* The upsert had been there
  since 2026-08-11, but the check had not: `handle_bot_reply` set `is_new = True` on the sole
  basis that its own entry-point `SELECT` had found nothing. Under Divar's at-least-once
  redelivery, two deliveries can both pass that `SELECT` before either commits — so both
  claimed to be new. Only one actually inserted. The loser re-sent `WELCOME_MESSAGE` and
  re-applied `START → MAIN_MENU`, knocking a mid-conversation user back to the menu.
  `_resolve_new_conversation` now derives `is_new` from `result.rowcount == 1` on the upsert
  itself and returns `Optional[Tuple[Conversation, bool]]`; `handle_bot_reply` unpacks it.
  There was **no `SELECT`-before-`INSERT` inside `_resolve_new_conversation` to remove** — the
  upsert was already first. The bug was entirely in how the caller inferred `is_new`.

  The post-upsert re-`SELECT` (needed because a Core insert yields no ORM instance, and
  inserts nothing at all on the race path) is now scoped to the full composite key
  `WHERE client_id = ... AND divar_conversation_id = ...` instead of reusing the unscoped
  `_lookup_conversation`. `client_id` is known by that point, which makes this the one query
  in the whole flow where §2.2's *"enforce `WHERE client_id` on every query"* rule is
  enforceable in code rather than merely relied upon via the constraint.

  **(2) `MultipleResultsFound` risk on the unscoped entry-point lookup.**
  `_lookup_conversation` is the chatbot's entry point and keys on `divar_conversation_id`
  alone. It cannot filter by `client_id` — resolving `client_id` is its entire purpose. With
  only the composite `(client_id, divar_conversation_id)` unique constraint, two rows could
  legally share a `divar_conversation_id` across clients, and `scalar_one_or_none()` would
  raise `MultipleResultsFound` inside a `BackgroundTask` — an unhandled 500-class failure
  where the user simply never gets a reply.

  Fixed at the root (**Option B**) rather than by making the read defensive: migration `0004`
  adds a standalone global `UNIQUE (divar_conversation_id)`, and the model gains the matching
  `UniqueConstraint`. A `.first()`/`limit(1)` fallback was explicitly rejected — it would have
  silently served one of two rows that must never coexist. `_lookup_conversation` keeps its
  logic unchanged and carries a comment pointing at `0004` so a future reader does not
  reintroduce that fallback.

  **Evidence basis — inference, not a documented guarantee.** The Divar docs nowhere state
  that `conversation.id` is globally unique. It is inferred from the ID being **Divar-assigned**
  and appearing as a UUID in every documented example:
  - `docs/events/chat.md` — `conversation.id` is `"edbb9499-cccc-4d35-b21f-621fa95f2b3e"` in
    all seven message-type payload examples (TEXT/IMAGE/FILE/VOICE/LOCATION/VIDEO/CONTACT).
  - `docs/widgets/actions/dynamic_action.md` and `docs/widgets/actions/open_server_link.md` —
    `"conversation_id": "6b3d5cf7-9291-4fa9-892a-9d07e300daea"`; the latter also documents a
    max length of 64.
  - `docs/chat/chatbot_conversations.md` uses a bare `{{conversation_id}}` placeholder — it
    shows no literal value, so it supports the *provenance* claim (Divar assigns it) but not
    the UUID-format one. `docs/events/ReadMe.md` does not mention `conversation_id` at all.

  Note this is the **inverse** of the `products.normalized_name` reasoning, which the old §2.2
  note wrongly cited as the same case. That one is composite-only precisely *because* the value
  is **seller-supplied** and two tenants can legitimately both list "iPhone 13". A
  Divar-assigned opaque ID has no such collision mode. The §2.2 note has been corrected.

  **Decision taken anyway, and why.** A UUID-shaped, platform-assigned identifier colliding
  across two of our tenants would mean Divar handed the same conversation to two different
  sellers' touchpoints — which would be a Divar-side bug, not a scenario to design for. The
  alternative (defensive read) makes the *guaranteed-broken* case silent while adding a
  permanent correctness hazard. Constraining the schema instead makes the impossible case
  loud, and the composite constraint is deliberately **kept** alongside it: it remains the
  named `ON CONFLICT` target that keeps legitimate redelivery a silent no-op.

  **Residual risk if the inference is wrong.** The composite `ON CONFLICT DO NOTHING` does not
  cover the global constraint, so a second client claiming an already-owned
  `divar_conversation_id` raises `IntegrityError` at insert. `_resolve_new_conversation`
  catches it specifically, rolls back, logs at `ERROR` with **both** client_ids plus the
  `divar_conversation_id` and `post_token`, and returns `None` — routing through the exact same
  path as an unresolved client (`UNRESOLVED_CLIENT_MESSAGE`, no further processing, nothing
  persisted). So the failure mode is: **the losing request fails safe to "unresolved," and the
  legitimate owner's row is untouched. It is not a 500, and it is not cross-tenant data
  leakage** — no client ever reads a row it does not own, because the losing insert never
  lands. Migration `0004` also deliberately performs no dedup backfill: if live data already
  violates the constraint it fails loudly, since picking a winner between two tenants' rows is
  not a decision a migration should make silently.

  **Tests** (`tests/test_chatbot.py`): `test_redelivered_upsert_reports_not_new` pins the
  `rowcount → is_new` contract directly; `test_redelivered_start_does_not_rewelcome_or_reset_state`
  drives the race end-to-end (state is moved to `SERVICE_MENU` first, so a re-applied
  `START → MAIN_MENU` is *observable* — asserting on `MAIN_MENU` alone would have been masked
  by `MAIN_MENU --menu--> MAIN_MENU` landing on the same state);
  `test_cross_client_conversation_id_collision_fails_safe` asserts the `IntegrityError` is
  caught, logged with both client_ids, and answered with `UNRESOLVED_CLIENT_MESSAGE`. Both
  race tests patch `_lookup_conversation` to `None` to simulate "row not yet visible to the
  entry lookup" — which is why the collision path's owner lookup uses a direct `SELECT` rather
  than reusing `_lookup_conversation`: the diagnostic must stay accurate regardless. Verified
  by reverting `is_new` to hardcoded `True` and confirming both redelivery tests fail.
  Full suite: 141 passed.

  **Explicitly out of scope** (separate, undecided items from the same audit): §2.4/2.5, the
  dev OAuth routes, and `/seller/posts`.

- **2026-08-11** — Marked PHASE2.md **§2.6 (State Machine)** as done. `services/state_machine.py`
  had existed since 2026-08-10 but was **entirely dead code** — its only importer was
  `models/conversation.py`, for a column default. `handle_bot_reply` was still the Phase 1
  stateless keyword router: `current_state` was written once at insert and never read again.
  All three §2.6 boxes are now genuinely satisfied:

  1. **Stored** — `conversations.current_state`, `NOT NULL` with `server_default='START'`
     (migration `0003`, which also backfills existing `NULL`s before the `SET NOT NULL`;
     Postgres `server_default` does not retroactively fill rows).
  2. **Single transaction per webhook** — `_resolve_new_conversation` no longer commits
     internally and now returns the `Conversation` ORM object (re-`SELECT` after the Core
     `on_conflict_do_nothing` upsert, which produces no instance and inserts nothing on the
     race path). `handle_bot_reply` owns the transaction with one `await db.commit()`.
  3. **One `transitions` map** — `TRANSITIONS` in `services/state_machine.py`; no state
     conditionals anywhere in `chatbot.py`.

  **Two vocabularies, one bridge.** `config.KEYWORD_MAP` yields uppercase intents
  (`PRICE|WARRANTY|SUPPORT|MENU|SERVICE`); `TRANSITIONS` consumes lowercase events
  (`price|service|human|menu|back|exit`). They previously disagreed — `WARRANTY` mapped to
  no state, `SERVICE_MENU` to no intent. Reconciled with a single `INTENT_EVENTS` dict, the
  only place the two meet. A test asserts `set(INTENT_EVENTS) == set(KEYWORD_MAP.values())`
  so a new keyword cannot be added without routing it.

  **Decisions taken (user-confirmed before implementation):**
  - **No persistent human-support mode this phase.** The task spec wanted SUPPORT →
    `MAIN_MENU`; the map sent `human` → `HUMAN_SUPPORT`. Resolved by repointing `human` to
    `MAIN_MENU`: SUPPORT/WARRANTY reply with `SUPPORT_PHONE_NUMBER` appended on a second
    line and return to the menu immediately. Bot replies are **not** suppressed afterward.
    `HUMAN_SUPPORT` is now defined-but-unreachable, alongside the `back`/`exit` edges
    (Phase 3 owns button navigation, `PHASE3.md:5-9`). **Retained deliberately — do not
    delete as dead code.**
  - **`price`/`service`/`human`/`menu` edges added to both `PRICE_MENU` and `SERVICE_MENU`**,
    which previously defined only `back`. Menus are not sticky: any intent routes correctly
    from any state.
  - **`START` auto-advances to `MAIN_MENU` on first contact, unconditionally** — no keyword
    needed. It reuses the existing `{"menu": MAIN_MENU}` edge rather than adding a code path.
    Previously nothing moved a conversation out of `START` at all.
  - **State values are uppercase** (`"START"`, not `"start"`) — `ConversationState` is a
    `StrEnum` whose values match `chatbot.py`'s literals. `chatbot.py` now uses
    `ConversationState.START.value` instead of a bare `"START"`, killing the drift risk.

  **Persian tokens** (each verified to survive `normalize_text`'s `_CHAR_MAP`/`_WORD_SYNONYMS`
  rewrites unchanged, since `_match_intent` runs on normalized text): `menu` → `منو`;
  `service` → `خدمات` with `سرویس` as a synonym in the same frozenset; `اپراتور`
  ("operator") added to the existing SUPPORT set, because `پشتیبانی` means *support desk*
  and does not cover talk-to-a-human phrasing. All four added to `FILTERED_KEYWORDS` so they
  cannot leak into `_extract_product_name` output (leak check on `قیمت خدمات منو گوشی`
  returns only `گوشی`). `KEYWORD_MAP` insertion order matters — `_match_intent` returns the
  first match, so it is the tiebreak on messages carrying more than one keyword.

  **Commit-before-send is deliberate.** `send_message` re-raises on non-2xx
  (`services/divar.py`) and no `_safe_send` exists in this codebase (advisor-plan 004 was
  never implemented). Committing first means a transient Divar failure costs the outbound
  message but never the state. Relatedly, the branch chain was restructured to only *build*
  `reply` (using `None` for the suppressed-greeting case) rather than send-and-return inline —
  the old greeting early-return at `chatbot.py` would have silently dropped any state write
  that preceded it. The **unresolved-client** path keeps its bare `return` with no commit
  (no row is ever persisted for unresolved conversations, per 2026-07-20 below), now with a
  comment so the asymmetry does not read as an oversight.

  **`_state_of(conv)`** parses `current_state` and falls back to `START` with a warning on
  `ValueError`. A malformed or legacy row would otherwise raise inside a `BackgroundTask`,
  where the webhook has already returned 200 and the user simply never gets a reply.

  **New config** (reply strings live in `config.py`, never in `chatbot.py` — see REFERENCE.md):
  `SUPPORT_PHONE_NUMBER` (placeholder default `021-00000000`, no `.env` requirement so
  nothing breaks when unset; mirrored into `.env.example` commented out),
  `CONTACT_MESSAGE_TEMPLATE`, `MENU_MESSAGE`, and `SERVICE_MENU_MESSAGE`.
  **Both `SUPPORT_PHONE_NUMBER` and `SERVICE_MENU_MESSAGE` are `TODO` placeholders** — the
  real phone number is pending, and real service-menu content is undefined anywhere in
  `plans/`. The `SERVICE` branch needs one so it has something to send; replace in a
  future pass.

  Also added `services/state_machine.py` to REFERENCE.md's file tree — it was created
  2026-08-10 without being listed, which conflicts with the "only create files listed above"
  agent rule. Tree drift remains for `tests/test_chatbot.py` and `alembic/`, not fixed here.

  **Tests** (`tests/test_chatbot.py`): a `TestTransitionTable` class covers the new edges as
  pure units (no DB), plus integration tests driving `handle_bot_reply` and asserting the
  persisted row from a *separate* verification session — auto-advance on first contact,
  SUPPORT/`اپراتور`/WARRANTY all landing in `MAIN_MENU` with the phone in the reply, PRICE
  reaching `PRICE_MENU` with its reply byte-identical to before, service→menu round trip,
  and unknown text leaving state untouched. These need a fresh session per call, since the
  existing `_TrackedSessionContext` mock is single-entry and cannot be entered twice; a `bot`
  fixture patches `chatbot.AsyncSessionLocal` with `lambda: session_factory()`. Three
  mutations confirmed the tests are real guards, not decoration: reverting the `human` edge
  fails 4, removing the auto-advance fails 7, removing the single commit fails 8. Full suite:
  **138 passed**.

  **Still open, deliberately not addressed** (raised, reviewed, left): `models/conversation.py`
  imports `services.state_machine` — inverted layering (every other service imports models,
  not the reverse) and a latent import cycle that will surface first in Alembic autogenerate;
  fixing it means moving the enum, which widens the diff. `_lookup_conversation` filters on
  `divar_conversation_id` alone against the composite `(client_id, divar_conversation_id)`
  unique constraint, so `scalar_one_or_none()` raises `MultipleResultsFound` if two clients
  ever share a conversation id (confirmed by execution; pre-existing). `PHASE4.md:8` expects
  the state machine to return `FALLBACK`, which is not one of §2.6's five states — an
  unreconciled gap for Phase 4.

- **2026-08-03** — Marked PHASE2.md **§2.5 (Background Task / Session Lifetime)** as done.
  **It was completed as a side effect of implementing 2.1 and 2.4, not as a separate pass** —
  which is why both boxes stayed `[ ]` long after the code had actually landed. Audit
  evidence for each item:
  - `services/chatbot.py`:
    `async def handle_bot_reply(conversation_id: str, user_text: str) -> None` — Phase 1
    signature unchanged, no `db`/session parameter; it opens its own session via
    `async with AsyncSessionLocal() as db:`, exactly as §2.5's NOTE prescribes.
  - `api/webhook.py`:
    `background_tasks.add_task(handle_bot_reply, conversation_id, user_text)` — no session
    and no `client_id` handed in from the request.
  - `client_id` is resolved *inside* the task via 2.1's `_lookup_conversation` /
    `_resolve_new_conversation` (`posts` → `conversations`), including the unresolved →
    `UNRESOLVED_CLIENT_MESSAGE` persist-nothing branch.
  - Logging context: `client_id_var.set(str(client_id))` (plus `conversation_id_var`).
  - Price lookup scoped per 2.4 via `_handle_price_intent(db, client_id, ...)`;
    `divar_service.send_message(conversation_id, text)` keeps its Phase 1 two-arg,
    global-API-key form per the 2.3 correction.

  The one genuine gap was **test coverage, not code** — nothing would have failed if
  someone reintroduced a request-scoped session parameter, since `tests/test_webhook.py`
  mocks `handle_bot_reply` wholesale and `tests/test_chatbot.py` only exercised the
  helpers. Closed with two tests in `tests/test_chatbot.py`, reusing the existing
  `session_factory` / `seeded_post` / `sqlite_upsert` / `catalog` fixtures:
  1. `test_handle_bot_reply_takes_no_session_parameter` — signature guard via
     `inspect.signature`, asserting the params are exactly
     `["conversation_id", "user_text"]`.
  2. `test_handle_bot_reply_opens_its_own_session` — patches `chatbot.AsyncSessionLocal`
     (the name must be patched on the `chatbot` module, since `chatbot.py` does
     `from db.session import AsyncSessionLocal`) with a mock wrapping the real
     `session_factory`, driven through the actual `/start MY_POST` resolution path with
     `chatbot.divar_service.send_message` mocked. Asserts `AsyncSessionLocal` is called
     once with no args and used as an `async with` context manager (both `__aenter__` and
     `__aexit__` fire, so the session is always closed), and that the session was real —
     the resolved `conversations` row is verifiable from a separate session.

  No webhook-level test was added for the `add_task` call signature; that is already
  covered by `tests/test_webhook.py::test_valid_auth_and_payload_schedules_background_task`.
  `tests/test_chatbot.py`: 34 passed; full suite: 122 passed.

  Also recorded (deliberately **not** changed) the one known seam noticed during this
  audit: `handle_bot_reply` does a function-body
  `from services.price_lookup import _cache` to check `if client_id not in _cache` before
  the lazy warm — a reach into another module's private global. Logged under
  `CHECKLISTS.md`'s Future Improvements rather than refactored, since it works and 2.4's
  cache shape is settled.

- **2026-07-28** — Closed the two remaining `[ ]` gaps in PHASE2.md §2.4 (the other
  2.4 items were already `[x]` and left untouched):
  1. **Startup cache warming:** `main.py`'s lifespan now calls
     `refresh_lookup_cache` for every client that has catalog data
     (`SELECT DISTINCT client_id FROM products` — clients with no products are
     intentionally skipped). Wrapped in try/except so a warming failure logs and
     continues; the lazy-load-on-first-miss fallback in `chatbot.py` is retained
     as the safety net for clients uploading after boot.
  2. **`get_price` `db` param + DB re-fetch (defense-in-depth):** `get_price` is
     now `async def get_price(db, client_id, item_name, threshold=70.0)`. After a
     fuzzy cache hit resolves a `normalized_name`, the row is re-fetched from
     `products WHERE client_id = :cid AND normalized_name = :key` and the DB
     `item_name`/`price` is returned. Cache hit but no DB row (deleted/replaced
     catalog) → logged as a cache/DB divergence, `None` returned (not found).
     `_handle_price_intent` in `services/chatbot.py` is now async and threads the
     existing `handle_bot_reply` session through; no ripple beyond the chatbot
     service. Tests converted to async against a real in-memory SQLite `products`
     table (test_auth.py pattern), with two new cases: stale-price (DB wins) and
     deleted-row (None). `get_all_matching_prices` / `find_top_matches` were left
     cache-only per the scoped task; their staleness exposure is flagged in
     PHASE2.md §2.4 as a known residual for a future improvement.

- **2026-07-27** — Added new section **2.9 — Supplier-Wide Chat Messaging** to
  `PHASE2.md`, sequenced after 2.1/2.4/2.5/2.6 (not started until those complete).
  Confirmed via `docs/chat/users_conversations.md`, `docs/events/ReadMe.md`, and
  `docs/events/chat.md` (Chat Message / Conversation / Message Sender schemas) that
  Divar's general post-chat (`conversation.type == POST`) is a structurally separate
  system from this project's existing chatbot (`conversation.type == BOT`) — different
  webhook event type/field, different reply endpoint/auth/body field, different send
  permission. This is additive: `send_message()`, the existing `NEW_CHATBOT_MESSAGE`
  webhook handling, and 2.1's `/start`-parsing resolver are explicitly untouched; 2.9
  adds a new `send_supplier_message()` function and a new webhook branch dispatching on
  `payload.type`, both coexisting with the existing code. Confirmed `conversation.type
  == POST` messages carry `post_token` directly on every message (unlike the chatbot's
  one-time `/start` message), so client_id resolution for this system reuses the
  existing `posts` table with a direct lookup, no `/start` parsing needed. **New
  operational requirement discovered:** per `docs/events/ReadMe.md`, the event
  subscription (`POST /events/subscriptions`) is bound to the specific access token used
  to create it — every per-seller token refresh must be followed by re-registering the
  subscription with the new token, or that seller's buyer messages silently stop
  arriving with no visible error. This is flagged as a mandatory follow-up task wherever
  token-refresh scheduling is eventually implemented (not yet built). Two open questions
  left unresolved in 2.9, pending user decision: whether `/oauth/dev/start` should also
  request the new scopes, and what to do when a `NEW_MESSAGE` event's `post_token`
  doesn't resolve to a known client_id.

- **2026-07-26 (2.3 implementation decisions)** — Implemented the real seller-facing
  `/oauth/start` and `/oauth/callback` routes alongside the retained `/oauth/dev/*` bootstrap
  routes. Real login state uses a process-local `dict[str, float]` of state-to-expiry values
  with lazy cleanup and a 10-minute TTL, rather than the bootstrap tool's single global state,
  so concurrent seller handshakes do not overwrite one another. The callback temporarily
  returns the existing `{"access_token", "expires_in"}` JSON session contract with the refresh
  cookie because no seller frontend/panel URL exists yet; it should become a `RedirectResponse`
  once that destination is defined. The Divar user lookup now has a `get_user()` helper that
  returns the defensively parsed `phone_number` and `user_id` from one GET request, while the
  required `get_user_phone_number() -> str | None` remains as a thin phone-only wrapper.

- **2026-07-21** — 2.4 status corrected: discovered ~60% pre-built while auditing 2.7's
  dependency on `refresh_lookup_cache`. Item 1's cache shape (dataclass, `int`-keyed)
  accepted as the real spec, replacing the original literal dict shape. Two real gaps
  remain open (startup cache warming; `get_price` missing `db` param + DB re-fetch). See
  PHASE2.md §2.4 for full detail.

- **2026-07-21** — Corrected `price_lookup.py`/2.4 spec: `_parse_df` raises `AttributeError`
  on a missing column (via `itertuples()`), not `KeyError` as previously documented. 2.4's
  admin-upload handler must catch `AttributeError`. No code changed.
- **2026-07-20 (2.8 clarification)** — Fixed the corrupted intro paragraph in section 2.8
  (orphaned sentence fragment + inaccurate "bot authorized to act on behalf of seller"
  claim). Also resolved a real point of confusion raised this session: whether the bot
  replying to chatbot customers requires per-seller OAuth (`CONVERSATION_SEND_MESSAGE` or
  similar). Confirmed against `docs/chat/users_conversations.md`, `docs/chat/ReadMe.md`,
  `docs/chat/chatbot_conversations.md`, and this app's live Kenar panel permission list:
  Divar has **two separate chat systems** — (1) general post-chat
  (`conversation.type == POST`), which does use per-seller OAuth scopes
  (`CONVERSATION_SEND_MESSAGE`, `CHAT_SUPPLIER_ALL_CONVERSATIONS_MESSAGE_SEND`, etc. — none
  of which this project uses), and (2) the chatbot (`conversation.type == BOT`, this
  project's entire chat surface), which uses the `CHAT_BOT_SEND_MESSAGE` **API-key
  permission** (app-level, confirmed present in this app's Kenar panel permission list) via
  plain `X-Api-Key` — no OAuth, no per-seller grant, no per-conversation scope. 2.3's
  original correction (`send_message`/`get_conversation` need only `X-Api-Key`) was correct
  all along; this entry documents the fuller evidence trail so the distinction doesn't need
  re-litigating. Also confirmed the required Kenar panel touchpoint settings for this
  project: `MY_POST` and `DEMAND_POST` touchpoints with `START_CHAT_BOT` enabled (not
  `LOAD_WEBVIEW_DIRECT_LINK`/`LOAD_WEBVIEW_SERVER_LINK`, which belong to an unrelated webview
  feature this project doesn't use). The `OWNERSHIP` touchpoint's `/start` behavior is
  undocumented in any file reviewed — leave disabled until/unless documented.
- **2026-07-20 (final confirmation)** — Fully confirmed `GET /v1/open-platform/users` against
  the live API using a real access token obtained through the `/oauth/dev/*` bootstrap flow
  (scope `USER_PHONE USER_ID offline_access`). Response:
  `{"phone_numbers": ["09395020382"], "phone_number": "09395020382", "user_id": "..."}`.
  **Confirms:** (1) `GET` is correct — `ReadMe.md`'s `POST` example was simply wrong, not a
  version-skew artifact. (2) The real API returns **both** response shapes simultaneously
  (`phone_number` singular AND `phone_numbers` array in the same response) — neither doc was
  "wrong" about the field existing, each just documented only one of the two fields Divar
  actually sends. `get_user_phone_number()`'s defensive parsing (check `phone_number` first,
  fall back to `phone_numbers`) is confirmed correct and sufficient as designed — no change
  needed. (3) `user_id` is populated and working, confirming `USER_ID` scope end-to-end.
  **Also discovered:** live `expires_in` was `604800` (7 days), not the `3600` (1 hour) shown
  in `docs/oauth/ReadMe.md`'s refresh-flow example. Any refresh-scheduling logic in 2.3/2.8
  must use the literal `expires_in` value from each token response, never hardcode 3600.
- **2026-07-20 (later)** — Resolved a real conflict between `docs/oauth/ReadMe.md` (shows
  `POST /v1/open-platform/users`) and `docs/oauth/get_user.md` (shows `GET`, same URL, same
  purpose — fetch phone/user_id using an already-held access token). **Confirmed via live
  test against the real API:** `GET` returned `{"message": "Invalid access token"}` (request
  routed correctly, failed only on token validity — expected with a bad/expired test token);
  `POST` returned `{"message": "RBAC: access denied"}` (rejected at the access-control layer,
  before/instead of token validation — consistent with POST not being a valid method for this
  route). **Decision: `GET` is correct.** `ReadMe.md`'s `POST` example is stale documentation.
  Section 2.3's `get_user_phone_number()` task updated: `GET /v1/open-platform/users`
  (previously stated `POST`).
- **2026-07-20** — Resolved the `/oauth/start` / `/oauth/callback` route collision between
  the Phase 1 bootstrap tool and section 2.3's per-seller "Sign in with Divar" login flow.
  **Decision:** rename the Phase 1 bootstrap tool's routes to `/oauth/dev/start` and
  `/oauth/dev/callback` now, freeing `/oauth/start`/`/oauth/callback` for 2.3's real
  implementation once 2.8 (`find_or_create_client`, `issue_session`) exists to support it.
  The bootstrap tool itself is **not deleted yet** — it remains available for manual
  debugging of OAuth-scoped endpoints until 2.3+2.8 are confirmed working end-to-end,
  at which point it will be deleted (tracked as a follow-up task, not done automatically).
  `api/oauth.py` updated accordingly (function names and route decorators only — state
  validation and token-exchange logic unchanged). **Manual follow-up required, not yet
  done:** `DIVAR_REDIRECT_URI` in `.env` must be updated to the new `/oauth/dev/callback`
  path, and the registered redirect URI in the Kenar panel must be updated to match, or
  Divar will reject the redirect with `redirect_uri mismatch` (this exact failure mode was
  hit once before in this project). Confirmed `main.py` mounts `oauth_router` with no
  prefix, so no double-prefixing risk from the rename.
- **2026-07-05** — Closed the "unresolved-conversation recovery" gap in section 2.1. Confirmed
  against `docs/events/chat.md` §"Conversation" (lines 234–240) that `post_token` is populated
  *only* when `conversation.type == POST`; chatbot conversations are type `BOT`
  (`docs/chat/chatbot_conversations.md` payload, lines 42–57), so **no** webhook message —
  first or subsequent — ever carries a resolution field. `/start` is a one-time launch message
  tied to the `START_CHAT_BOT` touchpoint action (`docs/chat/chatbot_conversations.md`
  lines 18–31), never redelivered. Therefore an unresolved conversation can never be resolved
  from a later message. Decision (user-confirmed): keep the fully stateless "persist nothing"
  behavior — reply `UNRESOLVED_CLIENT_MESSAGE` on *every* message in an unresolved conversation,
  not just the first. Reworded the misleading "reply once" NOTE accordingly (a stateless design
  cannot know a message is not the first). No new table, no sentinel client_id.
- **2026-07-04 (later)** — Added explicit failure path for OAuth login when Divar does not
  return a phone number (section 2.3, `GET /oauth/callback`). Previously the plan assumed
  `get_user_phone_number()` always succeeds; now it documents that if phone is unavailable
  (scope denied, field absent, or API error), auth fails with HTTP 403 — no client row
  created, no session issued. `get_user_phone_number` return type updated to `str | None`.
  Confirmed against `docs/oauth/get_user.md`: each response field is independently conditional
  on its respective OAuth scope being present in the access token.
- **2026-07-04** — Removed `{client_id}` from webhook route (`POST /api/v1/webhook/{client_id}`
  → `POST /api/v1/webhook`). Per Kenar documentation, the webhook URL is a single app-level
  endpoint — Divar does not append any client/seller identifier. `client_id` parameter also
  removed from `handle_bot_reply` signature (it was never used for business logic). Phase 2
  will resolve `client_id` internally from `post_token` via the DB (section 2.1). Updated
  sections: "Existing Files" for webhook.py and chatbot.py, 1.4, 2.5. Tests updated.
- **2026-07-03** — Comprehensive Phase 2 planning session completed. All 11 open questions
  (Q1–Q11) resolved with user confirmation. Key decisions:
  - **Seller auth (Q4):** OTP-to-phone + "Sign in with Divar" (OAuth). No username/password.
    `password_hash` stays removed from `clients`. Section 2.8 written with full spec.
  - **Session mechanism (Q3):** JWT access token (30 min, `Authorization: Bearer`) + refresh
    token in PostgreSQL (30 days, HTTP-only Secure cookie). `pyjwt` added to requirements.
  - **Tenant isolation (Q2):** Confirmed from docs — API key identifies the *application*, not
    any seller. Tenant isolation for outbound messages is purely app-level (2.1/2.4 handle it).
  - **USER_ID scope (Q1/Q10):** Confirmed to exist in `docs/oauth/get_user.md`. Both
    `USER_PHONE` and `USER_ID` requested in OAuth scope. `user_id` is per-app, stable.
  - **users table (Q7):** Removed from Phase 2. `conversations.user_id` FK removed. Deferred.
  - **posts population (Q6):** Seller endpoint (`POST /seller/posts`). Future: Divar API sync.
  - **OAuth tokens (user request):** Extracted from `clients` to separate `oauth_tokens` table.
  - **OTP hashing (user request):** HMAC-SHA256 instead of bcrypt (short-lived, high-entropy).
  - **GET /auth/me (user request):** Added to section 2.8.
  - **get_user method (Q8):** originally recorded as POST per `docs/oauth/ReadMe.md`;
    **superseded 2026-07-20** — confirmed via live test to be `GET`, per `docs/oauth/get_user.md`
    (see later changelog entry). Defensive response-shape handling still applies.
  - **Section 2.5 (Q9):** Fixed stale `access_token` reference.
  - **CHECK constraint (Q11):** Safe — clients only created through auth.
  - **Section 2.8:** New section written — OTP endpoints, OAuth "Sign in with Divar", merge-by-phone,
    `otp_codes`/`refresh_tokens`/`oauth_tokens` tables, auth dependency, session issuance.
  - Updated Project Structure, requirements, Tech Stack, Security Checklist, Current Status.
  - Proposed build order: 2.2 → 2.8 → 2.7 → 2.3 → (2.1 ∥ 2.4 ∥ 2.6) → 2.5 → 2.7 admin rework.
- **2026-06-24** — Resolved the 2.7 admin-endpoint blocker: `client_id` will be derived from
  the authenticated seller's own login session/token (not the global `admin_token`, not a
  caller-supplied `client_id`). This decision introduces a new, currently unspecified
  dependency — a seller login/session mechanism — which is now called out explicitly in 2.7
  as its own set of tasks, with the exact session scheme (JWT vs server-side, lifetime,
  refresh) still open and requiring user confirmation before implementation. Phase 2 remains
  blocked until that follow-up question is answered, in addition to 1.B1/1.B2.
- **2026-06-19** — Phase 1 robustness patches applied to `services/chatbot.py` and
  `services/price_lookup.py`. Phase 2 schema revised to fix tenant-isolation gaps.
- **2026-06-19 (later)** — Reviewed actual source of `config.py`, `services/chatbot.py`,
  `services/price_lookup.py`, `services/divar.py`, `api/webhook.py`, `api/oauth.py` against
  real Divar Kenar docs (`docs/chat/chatbot_conversations.md`, `docs/oauth/ReadMe.md`).
  Found and documented two real Phase 1 bugs (see "Phase 1 — Outstanding Bugfixes") that
  must be fixed first, since Phase 2's per-client OAuth design builds directly on the
  refresh-token code path. Confirmed `/start` touchpoint format, confirmed `state` is
  round-tripped unmodified by Divar's OAuth server. Phase 2 section rewritten with the
  full per-client OAuth flow, the `post_token`/`conversation_id` → `client_id` resolver,
  and corrected `divar.py` signatures. No phase transition occurred — Phase 1 main task
  list remains complete; the two bugfix tasks below are new and outstanding; Phase 2
  remains not-started until they're done.
- **2026-06-20 (later)** — Completed 1.B3 verification pass: confirmed all previously-implemented
  logging (logging_config.py, main.py lifespan call, webhook.py context-var sets + "incoming
  message" log, chatbot.py re-set + "processing message" / "intent matched" / "reply sent" logs,
  divar.py "send_message succeeded" log) was already present and correct on disk. Verified
  `send_message` failure-path logging (try/except with `logger.error` + `status_code` before
  re-raise) was already implemented. Added matching success/failure logging to
  `get_conversation` per user decision. Confirmed "Do NOT" list compliance: no `print()` calls,
  no secrets logged, no manual `extra={}` for `client_id`/`conversation_id` anywhere.
- **2026-06-20** — Added task 1.B3: structured JSON request/response logging via
  `contextvars`-based `client_id`/`conversation_id` tagging, designed so Phase 2 needs no
  changes when `client_id` becomes a real per-tenant value. User explicitly approved logging
  message text despite the Security Checklist's existing "no PII in logs" rule; this is
  recorded as a deliberate, dated, temporary override in both 1.B3 and the Security Checklist
  itself, not a silent contradiction — flagged for revisit before production launch.