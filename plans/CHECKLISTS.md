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
      | `GET_POST` | Future: post info retrieval | Only if/when post lookup is implemented |

- [ ] **OAuth scope approval (Divar ticketing):** Submit ticket to approve for production:
      `USER_PHONE`, `USER_ID`, `offline_access`. Test apps get all scopes by default;
      production apps get none until individually approved per `docs/scopes/README.md`.

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
- Admin billing panels
- Redis-backed rate limiting
- pgvector RAG for catalog search

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
---

