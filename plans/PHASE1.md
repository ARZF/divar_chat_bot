# Phase 1 — Core MVP + Bugfixes (Complete)

> Status: **Complete**, including all bugfixes (1.B1, 1.B2, 1.B3). Kept for reference —
> Phase 2 tasks build directly on some of this (especially 1.B1's `refresh_access_token`
> fix, consumed by section 2.3). Read this file when a Phase 2 task references a Phase 1
> fix/function you need to verify, not by default.

# Phase 1 — Outstanding Bugfixes

> **These two fixes must be completed before any Phase 2 task begins.** They are bugs in
> already-"complete" Phase 1 code, found during a review against the real Divar docs. Phase
> 2's OAuth and token-refresh design (section 2.3) builds directly on top of
> `refresh_access_token`, so a broken refresh path must be fixed first — otherwise Phase 2
> code will be built on, and will inherit, a function that already throws `AttributeError`
> on first use.

## 1.B1 — Fix `refresh_access_token()`'s wrong `settings.DIVAR_CLIENT_ID` reference

> **RESOLVED (2026-06-25) against literal `docs/oauth/ReadMe.md` text.** `client_id` is **not**
> a separate identifier — the doc states explicitly, at both the authorize step and the token
> step, that `client_id` = the app slug (`شناسه‌ی اپلیکیشن (Slug در پنل کنار)`). There is no
> Divar concept of a distinct "client ID." `api/oauth.py` already does this correctly
> (`"client_id": settings.DIVAR_APP_SLUG`). The bug is narrower than originally scoped: only
> `services/divar.py::refresh_access_token()` uses the wrong attribute name. **Do not add a
> new `DIVAR_CLIENT_ID` setting** — that would create two settings holding the same value and
> invite future drift.

- [x] In `services/divar.py::refresh_access_token()`, change every reference to
      `settings.DIVAR_CLIENT_ID` → `settings.DIVAR_APP_SLUG`
- [x] **Also add the missing `code` field to the refresh request body.** Per the doc's literal
      refresh-token example (step 5), the request body must include `code` set to **the
      currently-held access token** (not the authorization code — the field is confusingly
      named `code` but its value here is the current `access_token`), in addition to
      `refresh_token`, `client_id`, `client_secret`, `grant_type: "refresh_token"`, and
      `redirect_uri`. The current implementation omits `code` and `redirect_uri` entirely,
      which will likely cause every real refresh attempt to fail. New required body:
      ```python
      data={
          "code": <current_access_token>,
          "client_id": settings.DIVAR_APP_SLUG,
          "client_secret": settings.DIVAR_CLIENT_SECRET,
          "grant_type": "refresh_token",
          "redirect_uri": settings.DIVAR_REDIRECT_URI,
          "refresh_token": settings.DIVAR_REFRESH_TOKEN,
      }
      ```
      This means `refresh_access_token()` needs access to the *current* access token, not just
      the refresh token — check its call sites and add that parameter if missing.
- [x] Per the doc: a successful refresh returns **both** a new `access_token` and a new
      `refresh_token`. The old refresh_token becomes invalid (with a ~2 minute grace window
      per the doc). Confirm the caller persists **both** new values — persisting only the new
      `access_token` and keeping the old `refresh_token` will break the *next* refresh.
- [x] Confirm `services/divar.py::refresh_access_token()` now resolves
      `settings.DIVAR_APP_SLUG` without error

## 1.B2 — Validate `state` in `api/oauth.py`

- [x] `oauth_callback` must reject the callback (return `HTTP 400`) if `state` is missing
- [x] `oauth_callback` must validate `state` against a value the application itself
      generated and stored at the start of the OAuth redirect (step 1) — not just check that
      *a* `state` parameter is present, since an empty validation is not a validation
- [x] For the Phase 1 one-time bootstrap use case (single developer manually starting the
      OAuth flow once), an acceptable minimal fix is: generate a random `state` value when
      printing/logging the authorization URL the developer needs to visit, store it
      in-memory or in a temp file, and check it matches on callback. This does not need to be
      production-grade for Phase 1 — it needs to demonstrate correct `state` handling so
      Phase 2's per-client flow (section 2.3) has a working pattern to extend.
- [x] Do not remove the existing behavior of printing/returning the raw token response — that
      remains useful for the one-time manual bootstrap

## 1.B3 — Structured request/response logging

> **Deliberate, user-approved override of the Security Checklist's "no message content in
> logs" rule.** The user explicitly chose to log message text for now, accepting the PII
> tradeoff, to make debugging easier during early development. **This is logged here as a
> conscious decision, not an oversight** — revisit before any production launch or before
> onboarding a real seller's real customer conversations. The Security Checklist item itself
> is not deleted; this section documents the temporary exception to it.

**Goal:** every inbound webhook request and every outbound bot reply is logged as a single
structured (JSON) line to stdout, with `client_id` and `conversation_id` attached to every
line automatically — not passed manually into every log call — so the same logging code
requires no changes when Phase 2 makes `client_id` meaningful (real per-tenant value instead
of an unused parameter).

**New file: `logging_config.py`**

- [x] Define two module-level `contextvars.ContextVar` instances: `client_id_var` and
      `conversation_id_var`, both defaulting to `"-"`
- [x] Define a `logging.Filter` subclass that reads both vars and attaches them to every
      `LogRecord` as `record.client_id` / `record.conversation_id`
- [x] Define a `logging.Formatter` subclass that emits one JSON object per line, containing
      at minimum: `ts` (UTC ISO timestamp), `level`, `logger` name, `message`, `client_id`,
      `conversation_id`, and — when present — any additional structured fields passed via
      the stdlib `extra={...}` mechanism (e.g. `text`, `intent`, `status_code`). Must not
      crash if `extra` is omitted.
- [x] Define `setup_logging(level: int = logging.INFO) -> None` that installs a single
      `StreamHandler` (stdout) using the formatter and filter above as the root logger's only
      handler. Call this once, at app startup, from `main.py`'s `lifespan`/startup event —
      not from every module that wants to log.

**Changes to `api/webhook.py`:**

- [x] At the very top of the `webhook` endpoint, immediately after receiving `client_id`:
      `client_id_var.set(client_id)`
- [x] After successfully extracting `conversation_id` from the parsed payload:
      `conversation_id_var.set(conversation_id)`
- [x] Log one line on auth failure (`logger.warning("webhook auth failed")`) — no need to log
      the bad token value itself
- [x] Log one line for each accepted inbound message, including the message text via
      `extra={"text": user_text}` (per the override above)

**Changes to `services/chatbot.py`:**

- [x] **Important:** `ContextVar` values do not automatically propagate into
      `BackgroundTasks` callables — FastAPI runs background tasks after the response is sent,
      in a separate context. `handle_bot_reply` must re-set both context vars at its own entry
      point, using the `client_id`/`conversation_id` it already receives as parameters:
      ```python
      async def handle_bot_reply(client_id: str, conversation_id: str, user_text: str) -> None:
          client_id_var.set(client_id)
          conversation_id_var.set(conversation_id)
          ...
      ```
- [x] Log one line when processing starts (`extra={"text": user_text}`)
- [x] Log one line when an intent is matched (`extra={"intent": intent}`), including the
      `None`/no-match case
- [x] Log one line immediately before calling `divar_service.send_message`, with the reply
      text via `extra={"text": reply}`

**Changes to `services/divar.py`:**

- [x] Log one line after `send_message` succeeds or raises, including the HTTP status code
      (do not log the access token or any header value)
- [x] Log one line after `get_conversation` succeeds or raises, including the HTTP status code
      (same pattern as `send_message`: `logger.info` on success, `logger.error` on failure
      before re-raise; no secrets logged)

**Do NOT:**
- Use `print()` anywhere for this — all of the above goes through the standard `logging`
  module so output stays structured and consistent
- Log the `Authorization` header value, `DIVAR_ACCESS_TOKEN`, `DIVAR_WEBHOOK_SECRET`, or any
  other secret — text content and IDs are the explicitly approved exception; credentials are
  not, and remain covered by the Security Checklist without exception
- Hardcode `client_id`/`conversation_id` as manual arguments to individual `logger.info(...)`
  calls scattered through the code — the whole point of the `ContextVar` approach is that
  Phase 2 needs zero changes to this logging code when `client_id` becomes a real per-tenant
  value instead of an unused parameter

---

# Phase 1 — Core MVP

*(unchanged from original — all `[x]` tasks below remain complete; included here for
reference only)*

## 1.1 Configuration (`config.py`)
- [x] Create `config.py` using `pydantic-settings` `BaseSettings`
- [x] Load from `.env` file only — never hardcode values
- [x] Expose a single `settings` singleton imported app-wide

## 1.2 Divar Service (`services/divar.py`)
- [x] Implement `send_message(conversation_id: str, text: str) -> bool`
- [x] Implement `get_conversation(conversation_id: str) -> dict`
- [x] Use a single shared `httpx.AsyncClient`
- [x] Return `False` / raise on HTTP errors — do not swallow exceptions silently

## 1.3 Schemas (`schemas/webhook.py`, `schemas/admin.py`)
- [x] Define `EventType` enum with at minimum: `NEW_CHATBOT_MESSAGE`
- [x] Define `WebhookPayload` Pydantic model matching Divar's actual payload shape
- [x] Define `UploadPricesRequest` schema for admin file upload
- [x] **New, Phase 1, not yet done:** add `new_chatbot_message.id` and
      `new_chatbot_message.type` fields — see "Existing Files" note on `schemas/webhook.py`
      above

## 1.4 Webhook Endpoint (`api/webhook.py`)
- [x] ~~Mount at `POST /api/v1/webhook/{client_id}`~~ → **Refactored (2026-07-04):** route is
      now `POST /api/v1/webhook` (no `client_id` path param). See "Existing Files" note above.
- [x] Verify `Authorization` header via `hmac.compare_digest`
- [x] Parse body as `WebhookPayload`
- [x] Pass bot reply logic to `BackgroundTasks`
- [x] ~~`client_id` path parameter passed into background task~~ → removed (2026-07-04)

## 1.5 Bot Logic (`services/chatbot.py`)
- [x] Welcome message on first message, tracked via `seen_conversations: set`
- [x] Keyword matching against `settings.KEYWORD_MAP`
- [x] Pure greeting detection via `_is_pure_greeting()`
- [x] Fallback message for unmatched, non-greeting messages
- [x] 3-tier price lookup (substring → fuzzy → suggestions)

## 1.6 Price Lookup (`services/price_lookup.py`)
- [x] All public API functions implemented per spec (see "Existing Files" above)

## 1.7 Admin Endpoint (`api/admin.py`)
- [x] Mount at `POST /admin/upload-prices`
- [x] Bearer token auth
- [x] `.xlsx`-only validation
- [x] Parse + overwrite in-memory cache
- [x] Return `{"status": "ok", "rows_loaded": N}`

## Completed OAuth Setup (One-Time)
- `GET /oauth/callback` exchanges `code` for `access_token`
- Token stored manually in `.env` as `DIVAR_ACCESS_TOKEN`
- **Superseded by Phase 2 section 2.3 for any *new* seller onboarding** — this one-time flow
  remains only for the original bootstrap seller / local dev debugging

---

