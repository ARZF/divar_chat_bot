# Reference — Existing Files, Tech Stack, Project Structure

> Consulted by any phase when working on files that already exist, or when you need
> the tech stack / directory layout. Not phase-specific.

## Existing Files — Read Before Touching Anything

> The following files already exist. The agent must treat them as the source of truth for
> structure, but must apply the fixes listed below. Do NOT rewrite files from scratch —
> patch only what is listed.

### Project Structure Note
The project root is `D:\code\divar_chat_bot\`. There is **no `app/` subdirectory** — all
modules live flat at the root. All imports must reflect this (e.g. `from services.divar
import ...` not `from app.services.divar import ...`).

### `config.py` — EXISTS
- Uses Pydantic v2 `model_config = SettingsConfigDict(...)` — correct
- Field names are UPPERCASE — keep them as-is, do not rename
- Chatbot configuration constants (`SUGGESTION_MIN_SCORE`, `MAX_BULK_RESULTS`, all reply
  message strings, `GREETING_TOKENS`, `FILTERED_KEYWORDS`, `KEYWORD_MAP`) already live here
  as settings fields. `chatbot.py` imports all of these from `settings` — do not move them
  back into `chatbot.py`.
- **BUG, must fix in Phase 1 (see bugfix list below):** `services/divar.py` references
  `settings.DIVAR_CLIENT_ID`, but `Settings` only defines `DIVAR_CLIENT_SECRET`. This field
  is missing and must be added.

### `main.py` — EXISTS
- Only imports `webhook_router` and `admin_router` for now (`api/oauth.py`'s router must also be mounted —
  verify this is wired in; if not, add it as part of the Phase 1 bugfix pass)
- Sets up the single shared `httpx.AsyncClient` via `lifespan`

### `api/webhook.py` — EXISTS, updated for Phase 2 design
- Verifies `Authorization` header via `hmac.compare_digest()` — correct, keep as-is
- Wraps `handle_bot_reply` in `BackgroundTasks` — correct, keep as-is
- **Updated (2026-07-04):** Route changed from `POST /api/v1/webhook/{client_id}` to
  `POST /api/v1/webhook`. Per Kenar documentation, the webhook URL is a single app-level
  endpoint — Divar does not append any client/seller identifier to the path. The `client_id`
  path parameter has been removed. Tenant resolution will be performed in Phase 2 via
  `post_token` → `posts` table → `client_id` (see section 2.1).

### `schemas/webhook.py` — EXISTS, needs 1 addition before Phase 2
- Current schema captures `type`, `new_chatbot_message.text`,
  `new_chatbot_message.conversation.id`. Per the actual Divar payload
  (`docs/chat/chatbot_conversations.md`), the full message object also contains `id`
  (the message id) and `type: "TEXT"` on the message itself (distinct from the
  top-level event `type`), and `conversation.type: "BOT"`.
- **Add these fields now, in Phase 1, even though they're not used until later:**
  `new_chatbot_message.id` (message id — needed in Phase 2 for the `messages` table's
  `divar_message_id` unique constraint) and `new_chatbot_message.type` (needed in Phase 3
  to distinguish `TEXT` from future `button_click` events). Do not implement any logic that
  uses these fields yet — just make sure the schema captures them so Phase 2/3 don't need a
  schema migration just to read fields that were already arriving and being discarded.

### `services/divar.py` — EXISTS, needs fixes before Phase 2 (see bugfix list below)
- Creates a single shared `httpx.AsyncClient` — correct, keep as-is
- **BUG:** `refresh_access_token()` references `settings.DIVAR_CLIENT_ID`, which doesn't
  exist on `Settings`. Must be fixed in Phase 1 (see bugfix list).
- **Design issue, not a bug, but must change before Phase 2 can build on this file:**
  `send_message`, `get_conversation`, `_headers`, and `refresh_access_token` all read
  `settings.DIVAR_ACCESS_TOKEN` / `settings.DIVAR_REFRESH_TOKEN` directly, and
  `refresh_access_token`'s caller mutates `settings.DIVAR_ACCESS_TOKEN` in place. This is
  acceptable **only** because Phase 1 has exactly one global token. The moment tokens become
  per-client (Phase 2), this pattern cannot continue — there is no single global token to
  mutate. This rework is itself a Phase 2 task (see "2.3 Divar Service — Per-Client Tokens"
  below); do not attempt it during Phase 1.
  > **Status 2026-08-16: done.** `send_message`/`get_conversation` were converted to
  > `X-Api-Key`-only per 2.3, no caller mutates `settings.DIVAR_ACCESS_TOKEN`, and
  > `refresh_access_token` now takes the seller's own refresh token as a parameter instead of
  > reading `settings.DIVAR_REFRESH_TOKEN` — which is what this note predicted "cannot
  > continue" once tokens went per-client. It was in fact still reading the global setting
  > when §2.9 gave it a genuinely per-seller caller; fixed, with the row lock and testing
  > caveats recorded in PHASE2.md §2.9's resolved-defect note. Both `DIVAR_ACCESS_TOKEN` and
  > `DIVAR_REFRESH_TOKEN` are now unused by source code (see CHECKLISTS.md Config Cleanup).

### `services/chatbot.py` — EXISTS
> **Status 2026-08-19: now a backward-compatible re-export shim, not the primary
> implementation.** The 714-line module was split along its five responsibilities into
> `services/chatbot_engine.py` (shared reply engine), `services/chatbot_conversation.py`
> (BOT-conversation orchestration), `services/post_conversation.py` (POST-conversation
> orchestration) and `services/oauth_refresh.py` (seller token refresh). `chatbot.py` now
> contains only a docstring and re-exports so `api/webhook.py` keeps importing
> `handle_bot_reply`/`handle_post_bot_reply` unchanged. Pure reorganization — no behavior
> change; see `CHANGELOG.md` 2026-08-19. **Read the new modules, not this shim, when
> changing chatbot logic**, and note that patching a name on the shim does not affect the
> moved functions (see the changelog entry for why).
- Contains `handle_bot_reply(conversation_id, user_text)` — main orchestrator.
  **Updated (2026-07-04):** `client_id` parameter removed — it was never used for any
  business logic. Per Kenar documentation, the webhook payload contains no client/seller
  identifier; tenant resolution will be performed in Phase 2 via `post_token` → `posts`
  table → `client_id` (see section 2.1). All price lookups currently hit the single global
  catalog. Phase 2 will add `client_id` back as a resolved value from the DB, not a URL param.
- Contains `_match_intent`, `_extract_product_name`, `_is_pure_greeting` — all correct as-is,
  no changes needed in Phase 1 or at the start of Phase 2.
- 3-tier price lookup (substring → fuzzy → suggestions) is implemented and correct.
- Imports all reply constants from `settings` — correct, keep as-is.

### `services/price_lookup.py` — EXISTS
- Module-level state: `_prices`, `_canonical_names`, `_product_names` — single shared
  catalog, no per-client scoping. This is correct and expected for Phase 1. Phase 2 replaces
  this with a `client_id`-keyed structure (see Phase 2 section) — do not attempt this rework
  during Phase 1.
- `normalize_text()`, `_parse_df()`, `find_best_match()`, `find_top_matches()`,
  `get_all_matching_prices()`, `get_price()` are all implemented correctly per spec.
- `_parse_df()` expects columns literally named `"price"` and `"product"` in the source
  Excel file. **Known limitation, not a bug:** if an uploaded file doesn't have these exact
  column names, `_parse_df` raises **`AttributeError`** (an unhandled 500), not a clean
  validation error. **Corrected 2026-07-21** — previously documented as `KeyError`; the
  actual implementation uses `df.itertuples(index=False)` and accesses columns via
  attribute access (`row.price`, `row.product`), so a missing/misnamed column raises
  `AttributeError` on the namedtuple, not a dict-style `KeyError`. Same underlying bug
  (missing column → unhandled crash instead of clean validation), different exception
  type than originally assumed. Phase 2's admin endpoint rework should catch
  `AttributeError` (not `KeyError`) and return `HTTP 400` with a clear message — see
  Phase 2 admin endpoint task.

### `api/oauth.py` — EXISTS, Phase 1 version is a one-time manual setup tool only
- **Renamed (2026-07-20):** routes are now `GET /oauth/dev/start` and
  `GET /oauth/dev/callback` (previously `/oauth/start` / `/oauth/callback`), to avoid
  colliding with section 2.3's per-seller login routes, which now own the un-prefixed
  `/oauth/start` / `/oauth/callback` paths. See changelog for the `.env`/Kenar-panel
  follow-up this rename requires.
- Current implementation: `GET /oauth/dev/callback` exchanges `code` for `access_token` via
  `oauth.divar.ir/oauth2/token`, prints the response, returns it as JSON. The developer
  copies `access_token`/`refresh_token` into `.env` by hand. This was correct **for its
  one-time purpose** of bootstrapping the single Phase 1 seller's token, and remains
  available for local debugging **until 2.3+2.8 are confirmed working end-to-end, at which
  point it should be deleted** — its original justification (populating global
  `DIVAR_ACCESS_TOKEN`/`DIVAR_REFRESH_TOKEN` for `send_message`/`get_conversation`) no
  longer applies now that those functions use `X-Api-Key` only (see 2.3 correction).
- **BUG, must fix in Phase 1 (see bugfix list below):** the `state` query parameter is read
  but never validated. Per Divar's OAuth docs (`docs/oauth/ReadMe.md`), `state` exists
  specifically so the receiving application can authenticate that the callback actually
  originated from a request it made — skipping this check means any crafted callback to this
  endpoint is accepted as legitimate. This must be fixed before Phase 2, because Phase 2's
  per-client OAuth flow (section 2.3 below) depends on `state` carrying a verifiable,
  lookupable value, and that only works if state validation is actually wired up correctly
  from the start.
- Confirmed from Divar's docs: `state` is returned **unmodified** in the redirect — same
  value the app sent in step 1 comes back unchanged in step 2. This is the mechanism Phase 2
  uses to map an OAuth callback to a specific pending client (see section 2.3).
- Also confirmed: requesting `offline_access` in the `scope` parameter during step 1 is what
  causes `refresh_token` to be included in the step-3 token response. The current `.env`
  bootstrap flow implicitly relies on this already having been requested; Phase 2's
  per-client flow must request it explicitly every time, since every new seller needs their
  own refresh token.

### `models/enums.py` — EXISTS
- Contains `ConversationState`, moved verbatim from `services/state_machine.py` to keep the
  dependency direction services → models. `services/state_machine.py` re-exports it for
  existing importers; see `CHANGELOG.md` 2026-08-16.

### `requirements.txt` — EXISTS, needs updating for Phase 2
Current (Phase 1):
```
fastapi
uvicorn[standard]
httpx
pydantic-settings
pandas
openpyxl
rapidfuzz
```
Phase 2 additions (do not install until Phase 2 begins):
```
sqlalchemy[asyncio]
asyncpg
alembic
pyjwt
```

### `docs/` — EXISTS, do not touch
- Contains Divar Open API documentation, including `docs/chat/chatbot_conversations.md`
  (webhook payload shape, `/start` touchpoint formats) and `docs/oauth/ReadMe.md` (OAuth
  flow, `state` semantics, refresh token mechanics). Read-only reference material for the
  agent. **Phase 2 tasks reference specific sections of these files directly — read them
  before implementing section 2.3 or the webhook resolver in section 2.1.**

---

## Tech Stack (Fixed — Do Not Deviate)

| Layer | Library |
|-------|---------|
| Web framework | FastAPI |
| HTTP client | httpx (AsyncClient only) |
| Validation | Pydantic v2 |
| Config | pydantic-settings, `.env` file |
| Background tasks | FastAPI BackgroundTasks (no Celery in Phase 1/2) |
| DB (Phase 2+) | PostgreSQL + SQLAlchemy async + Alembic |
| Excel parsing | pandas + openpyxl |
| Auth (Phase 1) | HTTP Bearer token (static per client) |
| Auth (Phase 2+) | OTP + "Sign in with Divar" (OAuth) → JWT access token + DB-stored refresh token; per-client Divar OAuth tokens in `oauth_tokens` table; webhook auth unchanged |
| JWT (Phase 2+) | PyJWT (HS256) |

---

## Project Structure

```
app/
├── api/
│   ├── webhook.py        # Phase 1, reworked in Phase 2
│   ├── oauth.py           # Phase 1 one-time tool kept; Phase 2 adds new per-client routes
│   ├── auth.py            # Phase 2 (2.8) — OTP, refresh, logout, /auth/me
│   ├── admin.py          # Phase 1, reworked in Phase 2
│   └── seller.py         # Phase 2 (2.7) — POST /seller/posts (post-token registration)
├── services/
│   ├── divar.py          # Phase 1, reworked in Phase 2 (header split, get_user)
│   ├── price_lookup.py   # Phase 1, reworked in Phase 2 (per-client cache)
│   ├── chatbot.py        # Backward-compatible re-export shim only — NOT the implementation
│   ├── chatbot_engine.py       # Shared reply engine: intent match, generate_chatbot_reply
│   ├── chatbot_conversation.py # BOT-conversation (NEW_CHATBOT_MESSAGE) orchestration
│   ├── post_conversation.py    # POST-conversation (NEW_MESSAGE) orchestration
│   ├── oauth_refresh.py        # Seller OAuth token refresh
│   ├── state_machine.py  # Phase 2 (2.6) — ConversationState, TRANSITIONS, INTENT_EVENTS
│   └── ai.py             # Phase 4 only — do not create earlier
├── schemas/
│   ├── webhook.py        # Phase 1 (gains 2 fields, see above), Phase 2 unchanged
│   ├── admin.py          # Phase 1
│   └── seller.py         # Phase 2 (2.7) — post-token register request/response
├── models/               # Phase 2 only — do not create earlier
│   ├── enums.py           # ConversationState (moved from services/state_machine.py; see CHANGELOG 2026-08-16)
│   ├── client.py
│   ├── oauth_token.py     # Phase 2 (2.8) — Divar OAuth tokens per client
│   ├── otp_code.py        # Phase 2 (2.8) — pending OTP codes
│   ├── refresh_token.py   # Phase 2 (2.8) — app session refresh tokens
│   ├── post.py
│   ├── product.py
│   ├── conversation.py
│   └── message.py
├── db/
│   └── session.py        # Phase 2 only
├── data/
│   └── prices.xlsx       # Sample fixture only — never production data
├── config.py             # Phase 1
├── logging_config.py     # Phase 1 (added 1.B3) — structured logging setup
├── main.py               # Phase 1
├── .env.example          # committed template — copy to .env and fill in real values
└── PLAN.md
tests/
├── test_webhook.py
├── test_divar_service.py
├── test_price_lookup.py
├── test_oauth.py          # Phase 2 — covers state validation + per-client token exchange
└── test_auth.py           # Phase 2 (2.8) — OTP, session, merge logic
```

> **Agent rule:** Only create files listed above. Do not add files not in this tree without
> explicit user instruction.

---

