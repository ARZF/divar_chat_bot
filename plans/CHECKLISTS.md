# Checklists — Security, Pre-Production, Future Improvements

> Enforced in every phase. Consult before merging any auth/security-adjacent work,
> and always before a production deploy.

# Security Checklist (enforced in every phase)

- [ ] All webhook calls verified with `hmac.compare_digest` before any processing
- [ ] All OAuth callbacks verified via `state` matching before any token exchange (added
      this revision — see 1.B2 and 2.3)
- [ ] Every DB query scoped by `client_id` — raw cross-tenant queries are forbidden
- [ ] No PII (user IDs, message content) in logs — use structured logging with field
      suppression
      > **TEMPORARY OVERRIDE (2026-06-20):** the user explicitly chose to log message text
      > in 1.B3 during early development, accepting the tradeoff. Credentials/secrets are
      > NOT covered by this override and remain strictly forbidden in logs. Revisit this
      > checklist item — i.e. actually suppress message text — before production launch or
      > before any real seller's customer conversations flow through the system.
- [ ] Secrets only in `.env` or DB — `.env` is in `.gitignore` and never echoed in responses;
      per-client OAuth tokens in the DB are never logged or returned in API responses
- [ ] Admin endpoints require Bearer token — never `Depends(lambda: True)` placeholders
- [ ] File uploads: validate extension AND mime type, process in memory, discard after
- [ ] OTP codes: HMAC-SHA256 hashed at rest with `OTP_HMAC_KEY` — never stored as plaintext,
      never logged, never returned in API responses (see 2.8)
- [ ] Refresh tokens (app session): SHA-256 hashed at rest — never logged, never in API
      response bodies (cookie only). Divar OAuth tokens: plaintext in DB (acceptable for
      this phase) but never logged or returned in API responses (see 2.2/2.8)
- [ ] JWT secret and OTP HMAC key: `.env` only, never logged, never in source code

---

# Pre-Production Checklist

> Items that must be completed before the app transitions from test to production on Divar.
> These are external/administrative tasks, not code changes.

- [ ] **API key permissions (Kenar panel):** Ensure the production API key has:

      | Permission | Used By | Notes |
      |---|---|---|
      | `CHAT_BOT_SEND_MESSAGE` | `send_message()` — POST .../conversations/{id}/messages | Required per `docs/chat/chatbot_conversations.md` |
      | `EVENTS_REGISTER_SUBSCRIPTION` | `register_event_subscription()` — POST /events/subscriptions | API-key permission, **not** an OAuth scope, per `docs/events/ReadMe.md`. Confirmed present in this app's test-app panel; re-confirm on the production key |
      | `GET_POST` | Future: post info retrieval | Only if/when post lookup is implemented |

- [ ] **OAuth scope approval (Divar ticketing):** Submit ticket to approve for production:
      `USER_PHONE`, `USER_ID`, `offline_access`,
      `CHAT_SUPPLIER_ALL_CONVERSATIONS_MESSAGE_SEND`, `CHAT_SUPPLIER_ALL_CONVERSATIONS_READ`,
      `USER_POSTS_GET` (added 2026-08-29 by step 20 — powers the listing sync;
      narrower than the two chat scopes, it only reads the seller's own posts).
      Test apps get all scopes by default; production apps get none until individually
      approved. (Note: `docs/scopes/README.md` is a rate-limit/quota doc despite its name —
      the test-vs-production scope rule is in its final section. There is no complete scope
      registry in the docs; `docs/oauth/ReadMe.md`'s table lists only three examples.)
      > **Added 2026-08-16 (§2.9):** the two `CHAT_SUPPLIER_ALL_CONVERSATIONS_*` scopes are
      > materially broader than the first three — they cover reading and sending on *every*
      > chat of *every* post a seller owns. §2.9 already warns to expect scrutiny here.
      > Budget for a real justification in the ticket, and expect these two to be reviewed
      > separately from the login scopes.

- [ ] **Rate limits:** Review daily quota and minutely rate limit for the production app
      in Kenar panel. Request increase via ticket if expected volume exceeds defaults.

---

# Future Improvements (out of scope for all phases above)

- Media message handling
- Central FAQ knowledge base dashboard
- Live human handoff interface
- Analytics dashboard per tenant
- External CRM integration
- Multi-agent AI support workflows
- [ ] Extend `services/chatbot.py::generate_chatbot_reply(..., message_history=None)` in Phase 4 through `services/ai.py`; both BOT and POST orchestrators already share this seam, and POST supplies the latest ten isolated messages oldest-first.
- Admin billing panels
- Redis-backed rate limiting
- pgvector RAG for catalog search
- [ ] **No redelivery / dead-letter path for exhausted supplier messages.** After the
      2026-08-19 timeout + exception-type fix, a `send_supplier_message` call that burns all
      `MAX_ATTEMPTS` is logged with full context and swallowed — but the buyer never gets a
      reply and the seller is never alerted. Needs a retry queue, dead-letter store, or at
      minimum an alert. Explicitly out of scope of that fix; see `CHANGELOG.md` 2026-08-19.
- [ ] `services/post_conversation.py::handle_post_bot_reply` holds its `AsyncSessionLocal`
      DB session open for the full duration of the `send_supplier_message` HTTP call,
      including all retry/backoff time (worst case ~27–68s after the 2026-08-19 timeout
      fix, previously up to ~4 minutes). A DB connection from the pool is held idle for
      that entire window. Under a Divar-side network blip affecting several buyers at
      once, multiple concurrent `handle_post_bot_reply` background tasks could each hold
      a connection for tens of seconds, exhausting the pool and causing unrelated
      requests (other webhooks, seller-facing endpoints) to fail on connection
      acquisition — a resource-exhaustion risk, not just latency. Not fixed in the
      2026-08-19 timeout/exception-type pass (out of scope for that task). Candidate fix:
      restructure `handle_post_bot_reply` so the DB session is only open for the DB read/
      write portions, and `send_supplier_message` is called with no session held (e.g.
      resolve/persist before the send, reopen a session only for the final commit of the
      bot's reply + state update). Needs its own scoped task — touches transaction
      boundaries around dedup-insert, history load, and the final `db.commit()`.
- [ ] `/admin/upload-prices` returns an unhandled 500 on a corrupt/non-xlsx
      file with a valid extension (pandas parse failure not caught). The
      new `/api/v1/seller/products/import` (step 17) fixed this for its own
      route but the legacy admin endpoint was deliberately left untouched
      per the phase-3 execution scope.

### Authentication

- [ ] Implement periodic cleanup of expired `otp_codes` rows (Cron, Celery Beat, or scheduled background job) to prevent unbounded table growth.
- [ ] Invalidate and delete OTP records immediately after reaching `OTP_MAX_ATTEMPTS` instead of leaving them until expiration.
- [ ] Add structured audit logging for authentication events:
      - OTP requested
      - OTP verified
      - OAuth login completed
      - Refresh token rotated
      - Logout
      Never log OTP codes, access tokens, refresh tokens, JWTs, or secret keys.
- [ ] Consider expanding JWT claims (`sub`, `iat`, etc.) if future features require richer token metadata.

### SMS Infrastructure

- [ ] Support multiple SMS providers behind the existing `SMSService` interface.
- [ ] Add automatic retry with exponential backoff for transient SMS provider failures.
- [ ] Add provider failover (fallback provider when the primary provider is unavailable).
- [ ] Consider asynchronous SMS delivery (BackgroundTasks, Celery, or a message queue) for higher throughput deployments.
- [ ] Add delivery status monitoring and alerting for SMS provider failures.

### SMS OTP Delivery (deferred 2026-08-13, audit-confirmed gaps)

> **Status: OTP login path exists in code (api/auth.py) but is not production-usable.**
> Deliberately deferred — "Sign in with Divar" (OAuth) remains the only real login path
> until this is picked up. Do not enable/advertise OTP login until all items below are
> closed. Source: 2026-08-13 §2.8 audit.

- [ ] **No real SMS provider is wired in.** `services/sms.py`'s only concrete
      `SMSService` implementation is `ConsoleSMSService`, which logs the plaintext OTP
      instead of sending it — this is the active implementation returned by
      `get_sms_service()`, not a test-only stub. Must add a real provider (e.g.
      Kavenegar, per REFERENCE.md's original suggestion) before OTP can be exposed to
      real sellers.
- [ ] **`SMS_PROVIDER_API_KEY` / `SMS_PROVIDER_URL` are `str | None = None` in
      `config.py`.** §2.8 specifies both as required `str` with no default — should fail
      fast at startup if unset, not silently allow a no-op SMS path into production.
      Fix alongside the provider implementation above, since a required-but-unused
      setting is equally wrong.
- [ ] **`/auth/otp/request`'s SMS-failure response has the wrong shape.** Spec requires
      a top-level `{"error": "sms_unavailable", "message": "..."}`. Current
      implementation raises `HTTPException(detail={...})`, which FastAPI nests under
      `"detail"`. The existing test (`test_otp_request_sms_failure_returns_503_and_no_active_otp`)
      asserts the wrong (nested) shape and never actually queries `otp_codes` to confirm
      cleanup — both need fixing together when this is picked up, so the test isn't
      re-locking in the bug.
- [ ] **OTP request/verify are not concurrency-safe.** No locking or uniqueness
      constraint enforces "one active OTP per phone" — two simultaneous `/auth/otp/request`
      calls can both pass the cooldown check; two simultaneous `/auth/otp/verify` calls
      can both validate the same code before either deletes it. Needs a row lock or a
      partial-unique constraint before this is real.
- [ ] Add concurrency + exact-contract tests once the above land: OTP consumption
      after success, attempt increments after failure, stored hash values, and the two
      race conditions above.

**Not blocked on the above, already fixed 2026-08-13** (see CHANGELOG): refresh-token
rotation replay window and the OAuth token upsert race — both were independent of SMS
and didn't need to wait.

### Post-chat test coverage (Phase 2.9)

- [x] Webhook tests cover buyer dispatch, seller no-op, blank-text no-op, and unknown-post handling.
- [x] Chatbot tests cover post-conversation persistence, message deduplication, history isolation,
      missing OAuth credentials, token refresh and event re-registration, send failures, and
      cross-client conversation rejection.
- [x] Divar service tests cover supplier-message success, transient retries, non-transient
      failures, network failures, and retry exhaustion.


### Deployment & Security

- [ ] Allow configurable cookie settings (Domain, SameSite policy, Secure flag) per deployment environment.
- [ ] Document HTTPS-only production deployment requirements for authentication cookies.
- [ ] Add global rate limiting for all `/auth/*` endpoints (OTP cooldown alone is not sufficient for production-scale deployments).

### Observability

- [ ] Add authentication metrics (OTP requests, verification success rate, OAuth login success rate, refresh usage, SMS failures).
- [ ] Add monitoring and alerting for abnormal authentication failure rates.

### Price Cache Seams

- [ ] `services/chatbot.py`'s `handle_bot_reply` reaches into another module's private
      global: a function-body `from services.price_lookup import _cache`, used for the
      `if client_id not in _cache` check that guards the lazy `refresh_lookup_cache` warm.
      Noted during the 2026-08-03 §2.5 audit and **deliberately left as-is** — it works,
      and 2.4's cache shape is settled (see PHASE2.md §2.4). If it's ever cleaned up, the
      lazy path should ask `price_lookup` whether a client is warmed (e.g. a small
      `is_warmed(client_id)` / "refresh if missing" helper) rather than importing `_cache`,
      so the cache shape stays private to that module.
- [ ] `get_all_matching_prices` and `find_top_matches` still read the in-memory cache with
      no DB re-fetch, unlike `get_price` (2026-07-28). Same staleness exposure: stale price,
      since-deleted product. See PHASE2.md §2.4's "Known residual" note. Startup warming +
      lazy refresh-on-miss narrow the window; revisit if substring-path staleness becomes a
      real concern.

### Config Cleanup

- [ ] Remove the now-dead `admin_token` field from `Settings` (`config.py`) and from
      `.env`. As of 2.7 (2026-07-21) no source code references `settings.admin_token` —
      the seller-facing endpoints now authenticate via `get_current_client_id()` (JWT).
      Only the `config.py` field definition, doc prose, and the tests' `os.environ`
      setup (which merely satisfies the required Settings field) still mention it. Drop
      the field and update the test env-var setup in the same cleanup pass.
- [ ] Remove the now-dead `DIVAR_ACCESS_TOKEN` and `DIVAR_REFRESH_TOKEN` fields from
      `Settings` (`config.py`), `.env.example`, and the `os.environ.setdefault` blocks in
      `conftest.py` and the test modules. As of the 2026-08-16 refresh-token fix, no source
      code reads either one — per-seller tokens live in `oauth_tokens`, and
      `refresh_access_token` now receives the refresh token as a parameter. Deliberately
      **not** done in that bug-fix commit: it changes every deployment's `.env` and six test
      modules, which is a separate concern from the fix. Note the `/oauth/dev/*` bootstrap
      routes still *print* tokens for manual `.env` pasting but never read these settings, so
      dropping them does not break that tool. Best done together with the `admin_token`
      cleanup above, since both touch the same test env-var setup.
---

