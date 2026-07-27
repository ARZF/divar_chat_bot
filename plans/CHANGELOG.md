# Changelog

> Full dated decision history. Not read cover-to-cover by default — consult when a
> phase file or REFERENCE.md points here for evidence behind a specific claim, or
> spot-check a specific date/topic.

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