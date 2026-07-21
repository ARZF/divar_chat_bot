# Phase 2 — Multi-Tenant Conversation Management (Active)

> **Agent rule:** Do not begin Phase 2 tasks until `PLAN.md`'s Active Phase reads
> `Phase 2`, and both Phase 1 bugfix tasks (1.B1, 1.B2) are checked off in `PHASE1.md`.
>
> Cross-references: 2.1/2.3 assume Kenar chatbot docs behavior confirmed in this file's
> own notes and the Changelog (see `CHANGELOG.md` for the dated evidence trail if you
> need to re-verify a claim). 2.3 builds on 1.B1's `refresh_access_token` fix — see
> `PHASE1.md` if you need that context.

# Phase 2 — Multi-Tenant Conversation Management

> **Agent rule:** Do not begin Phase 2 tasks until `PLAN.md` header reads `Active Phase: 2`,
> **and** both Phase 1 bugfix tasks (1.B1, 1.B2) are checked off.
>
> This section assumes the chatbot is reached **only** via Divar touchpoints (post pages,
> "my Divar", professional panel, direct chat links) — confirmed against
> `docs/chat/chatbot_conversations.md`. It does not use the chat-addon `post_token` field,
> because that field only exists on the *addon* webhook, not the chatbot webhook this project
> uses. The resolution mechanism is to parse the touchpoint's auto-sent `/start ...` message
> instead — see 2.1 below.

## 2.1 Conversation → Client Resolution

> **Confirmed from `docs/chat/chatbot_conversations.md`:** when a chatbot conversation starts
> from a touchpoint, the **first message** the webhook receives is an auto-sent string in one
> of these exact forms:
> ```
> /start MY_POST {post_token}
> /start MY_DIVAR
> /start DIVAR_PRO
> /start CHAT {conversation_id}
> /start DEMAND_POST {post_token}
> ```
> Per the docs: *"در صورتی که شناسه آگهی در دسترس نباشد، فقط نام نقطه تماس ارسال می‌شود"*
> — if no post id is available, only the touchpoint name is sent (e.g. bare `/start
> MY_DIVAR`, no token at all).
>
> **Both `MY_POST` and `DEMAND_POST` carry a `post_token`.** A resolver that only checks for
> `MY_POST` will silently fail to resolve `DEMAND_POST` conversations — both must be handled
> identically by the parser.

**New model: `posts` — maps a `post_token` to a `client_id`**

```
posts:    post_token (PK), client_id (FK, indexed), created_at
```

> NOTE: a `post_token` always belongs to exactly one client (one listing belongs to one
> seller), so `post_token` as a primary key is safe here — unlike `products` or
> `conversations`, there is no multi-tenant collision risk on this table specifically.

**Tasks:**

- [ ] Create the `posts` model as above
- [ ] Implement a parser function `parse_start_message(text: str) -> Optional[Tuple[str, Optional[str]]]`
      returning `(touchpoint_name, token_or_none)` if `text` matches `/start <TOUCHPOINT>
      [<token>]`, else `None`. Must handle all five touchpoint names listed above, and must
      not assume a token is present (handles bare `/start MY_DIVAR` correctly).
- [ ] In the webhook handler: on first message in a `conversation_id`, if no DB row exists for
      that `divar_conversation_id` (i.e. conversation is not yet resolved to a `client_id` via `/start` message), attempt to parse it as a `/start` message:
      - If touchpoint is `MY_POST` or `DEMAND_POST` and a token is present: look up
        `posts.client_id` for that `post_token`. If found, this is the resolved `client_id`
        for the conversation — create the `conversations` row now, with that `client_id`.
      - If touchpoint is `MY_DIVAR`, `DIVAR_PRO`, `CHAT`, or `MY_POST`/`DEMAND_POST` with no
        matching `posts` row: **do not create a `conversations` row.** Send
        `settings.UNRESOLVED_CLIENT_MESSAGE` (new setting, see 2.1 config addition below) and
        return — no price lookup, no further processing, nothing persisted.
      - If the first message does **not** match `/start ...` at all (defensive case — should
        not normally happen, but the docs do not guarantee it never will): treat the same as
        an unresolved client.
- [ ] For all messages **after** the first in a given `divar_conversation_id`: look up the
      existing `conversations` row by `divar_conversation_id` to retrieve the already-resolved
      `client_id`. Do not re-parse `/start` on every message — only the first one carries it.
- [ ] **Unresolved conversations have no persisted row, so they are handled statelessly on
      every message.** Because nothing is persisted for an unresolved conversation (see NOTE
      below), the "is this the first message?" DB-row-existence check will report *not found*
      for **every** message in that conversation. This is intentional and correct: each message
      re-runs the `/start` parse, fails to resolve a `client_id` again (the `/start` launch
      message is never redelivered — see NOTE), and re-sends `settings.UNRESOLVED_CLIENT_MESSAGE`.
      Do **not** attempt to suppress the repeat reply — doing so would require persisting a
      per-conversation marker, which this design deliberately avoids. The reply is idempotent
      in effect (same canned message every time) and safe under Divar's at-least-once webhook
      redelivery.
- [ ] **Add to `config.py`:** `UNRESOLVED_CLIENT_MESSAGE: str` — Persian message asking the
      user to open the chat via a specific listing, used when `client_id` cannot be resolved.

> NOTE — why no `conversations` row for unresolved clients: the `conversations` table's
> composite unique constraint is `(client_id, divar_conversation_id)`. `client_id` is a
> required FK with no defined null-handling in this schema, and inventing a sentinel
> "unknown" client would itself be a tenant-isolation risk (every unresolved conversation
> would collide on the same sentinel row). It is simpler and safer to treat unresolved
> conversations as ephemeral/stateless: **persist nothing, and re-send
> `UNRESOLVED_CLIENT_MESSAGE` on every message in that conversation** (not just the first),
> letting the user retry via a proper post link.

> NOTE — unresolved conversations can never be recovered from a later message; the stateless
> re-reply is deliberate. **Confirmed (2026-07-05):**
> - `/start` is a **one-time launch message**, sent when the chatbot is launched from a
>   touchpoint (`START_CHAT_BOT` action) — `docs/chat/chatbot_conversations.md`
>   §"پیام شروع از نقاط تماس" (lines 18–31). The docs never state it is redelivered on
>   subsequent messages.
> - The chatbot webhook payload's conversation object is `{"id": ..., "type": "BOT"}` with
>   **no `post_token`** — `docs/chat/chatbot_conversations.md` payload (lines 42–57).
> - This is structural, not incidental: `docs/events/chat.md` §"Conversation" (lines 234–240)
>   defines `post_token` as `Optional`, present *«در صورتی که نوع مکالمه POST باشد»* — only when
>   `conversation.type == POST`. Chatbot conversations are type `BOT`, so `post_token` is never
>   populated for them.
>
> Consequently there is **no field on any subsequent webhook message** that could let us
> re-attempt resolution, and no second `/start` to re-parse. An unresolved conversation stays
> unresolved for its entire life. We therefore re-send `UNRESOLVED_CLIENT_MESSAGE` each time
> rather than pretending we can recover — the alternative (a `divar_conversation_id`-keyed
> `unresolved_conversations` marker table to reply only once) was considered and rejected to
> preserve the "persist nothing" invariant for conversations we cannot attribute to a tenant.

## 2.2 Database Models (SQLAlchemy async, exact field names)

```
clients:        id, phone_number (Unique, nullable), divar_user_id (Unique, nullable),
                created_at
                CHECK (phone_number IS NOT NULL OR divar_user_id IS NOT NULL)

oauth_tokens:   id, client_id (FK, Unique, indexed), divar_access_token,
                divar_refresh_token, token_expires_at, created_at, updated_at

otp_codes:      id, phone_number (indexed), code_hash (HMAC-SHA256),
                expires_at, attempts (default 0), created_at

refresh_tokens: id, client_id (FK, indexed), token_hash (SHA-256),
                expires_at, created_at

posts:          post_token (PK), client_id (FK, indexed), created_at

products:       id, client_id (FK, indexed), item_name, normalized_name, price,
                created_at, updated_at
                UNIQUE (client_id, normalized_name)   -- composite, NOT globally unique

conversations:  id, client_id (FK, indexed), divar_conversation_id,
                current_state, metadata (JSONB), created_at, updated_at
                UNIQUE (client_id, divar_conversation_id)  -- composite, NOT globally unique

messages:       id, conversation_id (FK, indexed), divar_message_id (Unique),
                sender_type (Enum: user|bot|human_agent), text_content,
                payload (JSONB), created_at
```

> NOTE — `clients.username` / `password_hash` are **removed** (confirmed 2026-07-03). Sellers
> authenticate via OTP-to-phone or "Sign in with Divar" (OAuth) — see section 2.8. There is
> no separate password. Do not reintroduce `password_hash`.

> NOTE — `users` table and `conversations.user_id` FK are **deferred** to a future phase
> (confirmed 2026-07-03). The chatbot webhook provides no end-customer identifier, and getting
> one would require OAuth consent from the end customer. Do not create `models/user.py` in
> Phase 2.

> NOTE — `clients.divar_user_id` is the **seller's own** Divar identity from their OAuth
> login (2.8). **Confirmed (2026-07-03):** `docs/oauth/get_user.md` explicitly lists `USER_ID`
> as a valid OAuth scope, and the response includes `"user_id": "awoDdf1ecd2wac"`. The
> `user_id` is per-app (different apps see different IDs for the same Divar user) but stable
> and unique for a given (user, app) pair. The OAuth scope in `/oauth/start` requests both
> `USER_PHONE` and `USER_ID` so this column can be populated during "Sign in with Divar."

> NOTE — `oauth_tokens` table: **extracted from `clients`** (2026-07-03 user request). Stores
> the Divar OAuth `access_token` and `refresh_token` per client. `client_id` is Unique
> (one-to-one — a seller has at most one set of Divar OAuth tokens). These tokens are used
> **only** to call `get_user_phone_number()` during login/merge — they are **not** used to
> authorize `send_message`/`get_conversation` (those use the global `settings.DIVAR_API_KEY`).
> Do not log these columns and do not include them in any API response.

> NOTE — `otp_codes` table: stores pending OTP verification codes, HMAC-SHA256 hashed (not
> bcrypt — OTP codes are short-lived and high-entropy; bcrypt's slow hash adds unnecessary
> latency). Only one active OTP per phone number at a time. See 2.8 for the full OTP flow.

> NOTE — `refresh_tokens` table: stores the app's own session refresh tokens (not Divar's
> OAuth refresh tokens, which live in `oauth_tokens`). SHA-256 hashed. One-to-many with
> `clients` — a seller may have multiple active sessions (e.g. phone + laptop). See 2.8.

> NOTE — `products.normalized_name` uniqueness: composite `(client_id, normalized_name)`, not
> standalone — two sellers can each list "iPhone 13" without collision.

> NOTE — `products.normalized_name` is in addition to `item_name`: Phase 1's separation of
> canonical (display) name vs. normalized (matching) text must be preserved at the DB level —
> store both, don't re-normalize on read.

> NOTE — `conversations.divar_conversation_id` uniqueness: composite
> `(client_id, divar_conversation_id)`, same reasoning as `products`.

**Tasks:**

- [x] Setup `db/session.py` with an async SQLAlchemy engine (`asyncpg` driver) + async
      `get_db` dependency (yields `AsyncSession`)
- [x] Create all models above with exact fields, including composite unique constraints
- [x] Setup Alembic; first migration auto-generated from models
- [x] Replace in-memory `seen_conversations: set` with the DB-row-existence check described
      in 2.1 — implemented as a single atomic upsert
      (`INSERT ... ON CONFLICT (client_id, divar_conversation_id) DO NOTHING`, checking
      whether a row was actually inserted), to avoid the double-welcome race described below
- [x] Enforce `WHERE client_id = :current_client_id` on every query — no exceptions
- [x] Migrate price storage from in-memory dict to `products` table, scoped by `client_id`

> NOTE — race condition on first message: Divar may redeliver a webhook (at-least-once
> delivery). A `SELECT ...; if not found: INSERT` pattern can let two near-simultaneous
> deliveries for the same new conversation both see "not found" and both send the welcome
> message. A single atomic upsert, checked for whether it actually inserted a row, avoids
> this.

## 2.3 Divar Service — API Key Auth (send_message) + OAuth (phone number only)

> **MAJOR CORRECTION (2026-06-25) against literal `docs/chat/chatbot_conversations.md` and
> `docs/oauth/ReadMe.md` text.** Every previous revision of this section assumed
> `send_message`/`get_conversation` need a **per-seller OAuth `access_token`**. That premise
> is wrong. The literal doc example for
> `POST /v1/open-platform/chat/bot/conversations/{conversation_id}/messages` shows only:
> ```
> X-Api-Key: {your-api-key}
> ```
> No `Authorization` header, no Bearer token, no OAuth at all. This was confirmed live in this
> project's own logs on 2026-06-25 — `send_message` returned a real `200 OK` using only the
> existing Phase 1 `X-API-Key` header, no `access_token` involved. **There is no
> `clients.divar_access_token` / `divar_refresh_token` requirement for replying inside an
> existing chatbot conversation.** A *separate* endpoint,
> `POST /chat/bot/users/{user_id}/messages`, *does* use `Authorization: Bearer {access_token}`
> with scope `CHAT_BOT_USER_MESSAGE_SEND` — but that's for messaging a user **directly without
> a conversation_id**, a different feature this project does not currently use. Do not conflate
> the two endpoints.
>
> **What OAuth is actually needed for in this project, confirmed from the doc:** retrieving a
> seller's **phone number** and **user ID** via `scope=USER_PHONE USER_ID`
> (`POST /v1/open-platform/users`) — which 2.8's "Sign in with Divar" login/merge-by-phone
> flow genuinely depends on. That is the *only* confirmed use of per-seller OAuth tokens in
> this plan. `oauth_tokens` (2.2) exists to support **that** OAuth use case, not to authorize
> `send_message`.
>
> **Tenant isolation — RESOLVED (2026-07-03):** Confirmed from `docs/management/api-keys.md`
> and `docs/chat/chatbot_conversations.md`: the API key identifies the *application*, not any
> seller within it. There is no per-seller isolation mechanism in the Divar API — the chatbot
> endpoint takes only `conversation_id` + API key, with no seller identifier. Tenant isolation
> for outbound messages is **purely an application-level concern**: the app's single API key
> can legitimately call `send_message` on any `conversation_id` belonging to conversations
> initiated via its own touchpoints. The app scopes replies to the correct seller's catalog
> internally via 2.1/2.4.
>
> **get_user response shape — defensive handling (2026-07-03):** `docs/oauth/get_user.md`
> shows `{"phone_number": "...", "user_id": "..."}` (singular string fields), while
> `docs/oauth/ReadMe.md` step 4 shows `{"phone_numbers": [...]}` (plural array). The
> implementation handles both shapes defensively: checks for `phone_number` (string) first,
> then `phone_numbers` (array), extracts first entry either way. Same for `user_id`.
>
> **HTTP method — resolved (2026-07-20):** `get_user.md` also disagrees with `ReadMe.md` on
> method (`GET` vs `POST`) for this same endpoint. Confirmed via live test: `GET` reaches
> token validation (`"Invalid access token"`), `POST` is rejected at the access-control
> layer (`"RBAC: access denied"`) before token validation even runs. **`GET` is correct** —
> `get_user_phone_number()` must use `GET`, not `POST`.

**`services/divar.py` — corrected scope of changes for Phase 2:**

- [ ] `send_message(conversation_id: str, text: str) -> bool` and
      `get_conversation(conversation_id: str) -> dict` **keep their Phase 1 signatures
      unchanged** — they continue to use the single global `settings.DIVAR_API_KEY` via
      `X-Api-Key`, exactly as today. No `client_id` or `access_token` parameter is added to
      either function. The earlier plan revision's `access_token: str` parameter on these two
      functions is **retracted**.
- [x] Fix `refresh_access_token()` per bugfix 1.B1 (wrong attribute name, missing `code` field)
      — this function still exists and is still needed, but only for the **OAuth/phone-number**
      use case below, not for `send_message`/`get_conversation`.
- [ ] Add `get_user_phone_number(access_token: str) -> str | None` — calls
      `GET /v1/open-platform/users` (confirmed via live test 2026-07-20 — see changelog;
      `docs/oauth/ReadMe.md`'s `POST` example is stale) with `X-Api-Key` +
      `Authorization: Bearer {access_token}`,
      returns the phone number from the response (handles both `phone_number` string and
      `phone_numbers` array shapes defensively), or `None` if the field is absent/empty
      or the API call fails. Does not raise — caller decides the failure behavior.
      Used only by 2.8's OAuth-login callback.
- [ ] **Split the single `_headers()` into two builders** so auth mechanisms are no longer
      conflated (today `_headers()` sends *both* `X-Api-Key` and `Authorization: Bearer` on every
      call, which only works by accident): `_api_key_headers() -> dict` (`X-Api-Key` only —
      used by `send_message`/`get_conversation`) and `_oauth_headers(access_token: str) -> dict`
      (`X-Api-Key` + `Authorization: Bearer {access_token}` — used only by
      `get_user_phone_number`). Confirmed against docs: `POST /chat/bot/conversations/{id}/messages`
      requires `X-Api-Key` only (no Bearer), while `POST /v1/open-platform/users` requires both.
- [ ] **Remove the OAuth refresh-on-401/403 block from `send_message` and `get_conversation`.**
      These endpoints authenticate via the API key, not the OAuth token, so a 401/403 from them is
      not a token-expiry condition — refreshing `settings.DIVAR_ACCESS_TOKEN`/`DIVAR_REFRESH_TOKEN`
      there is dead logic that also mutates global token state for no reason. `refresh_access_token`
      remains, used only by the OAuth/phone-number flow (2.8).


**OAuth entry points — now scoped only to the login/phone-number use case (2.8), not to
chat-sending permission, since chat-sending needs no OAuth at all:**

**`GET /oauth/start`** *(no path param — single purpose now: "Sign in with Divar")*

- [ ] Generates a random, unguessable `state` value, stores `state -> "LOGIN"` (in-memory,
      short TTL — short-lived handshake artifact, not durable data)
- [ ] Redirects to:
      ```
      https://oauth.divar.ir/oauth2/auth?response_type=code
        &client_id={settings.DIVAR_APP_SLUG}
        &redirect_uri={settings.DIVAR_REDIRECT_URI}
        &scope=USER_PHONE USER_ID offline_access
        &state={generated_state}
      ```
      `offline_access` causes Divar to also return a `refresh_token` (valid 30 days per the
      doc) — needed since a seller's session shouldn't require re-authenticating with Divar
      every `expires_in` (3600s per the doc) seconds. **Note the corrected scope:** `USER_PHONE`
      replaces the previous, unconfirmed `CHAT_BOT_SEND_MESSAGE` — that name does not appear
      anywhere in `docs/oauth/ReadMe.md`'s scope list and was likely a conflation with the
      chatbot conversation doc's separate (and differently-mechanized) permission language.

**`GET /oauth/callback`**

- [ ] Reads `state` and `code` from query params
- [ ] **Rejects with `HTTP 400` if `state` is missing or doesn't match the stored `"LOGIN"`
      mapping** (per-client version of the 1.B2 bugfix)
- [ ] Exchanges `code` for tokens: `POST https://oauth.divar.ir/oauth2/token` with
      `grant_type: "authorization_code"`, `code`, `client_id` (=`DIVAR_APP_SLUG`),
      `client_secret`, `redirect_uri` — exactly per the doc's step 3 example
- [ ] Calls `get_user_phone_number(access_token)` to get the seller's phone number
- [ ] **Failure path — phone number unavailable:** If `get_user_phone_number()` returns
      `None` (seller declined `USER_PHONE` scope, field absent from response, empty array,
      or the `get_user` API call itself failed): return HTTP 403 with
      `{"error": "phone_required", "message": "دسترسی به شماره تلفن الزامی است. لطفاً مجدداً با تأیید دسترسی شماره تلفن وارد شوید."}`.
      Do NOT create a `clients` row, do NOT issue a session, do NOT store OAuth tokens.
      Discard the exchanged tokens entirely. Log a warning with the failure reason.
      The seller must re-initiate "Sign in with Divar" and grant `USER_PHONE` to proceed.
      **Rationale (confirmed from `docs/oauth/get_user.md`):** the `phone_number` field is
      returned ONLY if the `USER_PHONE` scope is present in the access token — each field
      is independently conditional on its respective scope. Since `phone_number` is the sole
      merge key for `find_or_create_client`, authentication cannot proceed without it.
- [ ] Hands off to 2.8's find-or-create-by-phone logic to resolve (or create) the `client_id`
- [ ] Stores `access_token`, `refresh_token`, `token_expires_at` on the resolved `clients` row
- [ ] Removes the `state` mapping after use (one-time use)
- [ ] Issues the seller session per 2.8 and redirects/responds accordingly — does not return
      the raw token response to the browser

> NOTE — refresh flow for this OAuth use case only (not send_message): on access-token
> expiry, call `refresh_access_token()` per the corrected 1.B1 implementation (passing the
> *current* access token in the `code` field, per the doc's literal requirement), and persist
> **both** the new `access_token` and new `refresh_token` returned — the doc confirms both
> rotate on every refresh and the old `refresh_token` stops working (after a ~2 minute grace
> window). **`expires_in` is NOT reliably `3600`** — confirmed via live test (2026-07-20) it
> can be `604800` (7 days) for this app. Always read `expires_in` from the actual token
> response and compute `token_expires_at` from it; never hardcode `3600`.

## 2.4 Price Cache (Hybrid: DB-backed source of truth, in-memory fuzzy index)

> Rationale: PostgreSQL has no efficient native equivalent to `rapidfuzz`'s fuzzy scorers.
> The fix is a hybrid cache: the `products` table is the source of truth; a per-tenant
> in-memory index is rebuilt only on app startup and after an admin upload for that tenant.

> **STATUS (audited 2026-07-21, during 2.7's implementation):** this section is
> **substantially already built** in `services/price_lookup.py`, discovered while
> implementing 2.7 (which depends on `refresh_lookup_cache`/`load_prices_to_db`).
> `STATUS.md` previously implied "not started" — that was stale. Actual state per item,
> below. Two real gaps remain (items 2's startup-warming and 3's `db` re-fetch) — those
> are still open `[ ]` tasks for whoever picks this section up properly.

- [x] **Per-client cache structure — satisfied, with an approved shape deviation.**
      Actual implementation (`price_lookup.py`):
      ```python
      _cache: dict[int, ClientPriceCache] = {}   # client_id (int) -> ClientPriceCache
      # ClientPriceCache dataclass holds: prices, canonical_names, product_names
      ```
      This deviates from the shape originally specified below (kept for historical
      context, not to be implemented — the dataclass approach above is the accepted
      design): `dict[str, dict[str, int]]` keyed by `client_id: str` storing
      `{normalized_name: product_id}`, plus a parallel `dict[str, list[str]]` for names.
      **Decision (2026-07-21): the dataclass shape is accepted as the real spec going
      forward** — it satisfies the actual requirement (per-tenant isolation, no flat
      global) via a cleaner structure than originally written. Do not "fix" this to
      match the old literal dict shape.
- [ ] **`refresh_lookup_cache(db, client_id)` — PARTIALLY done.** Function exists and is
      correctly called after every admin upload (via `load_prices_to_db`). **Still
      missing:** the "call once per known `client_id` on app startup" behavior —
      `main.py`'s lifespan never warms the cache; `chatbot.py` currently only populates
      lazily on first cache-miss per client. This lazy-load covers correctness but not
      the original startup-warming requirement (first message per client currently pays
      a cold-cache penalty). Remaining task: add startup warming in `main.py`'s
      lifespan, iterating known `client_id`s and calling `refresh_lookup_cache` for each.
- [ ] **`get_price(client_id, item_name, threshold=70.0)` — PARTIALLY done.** Fuzzy match
      against that client's `product_names` is correctly scoped and working. **Still
      missing:** (a) no `db` parameter — current signature doesn't accept a DB session
      at all; (b) no DB re-fetch defense-in-depth — the matched result is returned
      straight from the in-memory cache with no `client_id`-filtered re-verification
      against the `products` table. Remaining task: add `db: AsyncSession` param, and
      after a cache hit, re-fetch the matched row from `products` filtered by
      `client_id` before returning, per the original defense-in-depth intent.
- [x] **Admin upload scoped transactional replace — satisfied** (service layer). 
      `load_prices_to_db(db, client_id, df)` does exactly the specified sequence: scoped
      delete → scoped insert → commit → `refresh_lookup_cache`. (The *endpoint's* JWT
      scoping was 2.7's job, not 2.4's — see PHASE2.md §2.7.)
- [x] **`_parse_df` `AttributeError` → HTTP 400 — resolved as a side effect of 2.7.**
      Confirmed `_parse_df` raises `AttributeError` (not `KeyError` — see 2026-07-21
      changelog entry), via `itertuples()` attribute access. This is fixed in 2.7's
      `/admin/upload-prices` rework (catches `AttributeError`, not the previously-wrong
      `KeyError`) — not a separate 2.4 task anymore.

## 2.5 Background Task / Session Lifetime

> NOTE — do not inject the request's DB session into `BackgroundTasks`. FastAPI's
> `Depends(get_db)` session may already be closed by the time a background task runs.
> Instead, the background task opens its own session:
> ```python
> async def handle_bot_reply(conversation_id: str, user_text: str) -> None:
>     async with AsyncSessionLocal() as db:
>         ...
> ```

- [ ] `handle_bot_reply` keeps its current Phase 1 signature `(conversation_id, user_text)`
      — opens its own DB session internally rather than receiving one as a parameter.
      `client_id` is resolved inside from the DB (via 2.1), not passed from the webhook URL.
- [ ] Inside, it now: resolves/loads the conversation's `client_id` per section 2.1, sets
      `client_id_var` for logging context, runs price lookup scoped per section 2.4, and
      calls the reworked `divar.py` functions (which use the global API key, not per-client
      tokens — see 2.3 correction)

## 2.6 State Machine

States: `START → MAIN_MENU → PRICE_MENU | SERVICE_MENU | HUMAN_SUPPORT`

- [ ] Store `current_state` in `conversations.current_state`
- [ ] On each webhook: load state → process → save updated state as a single transaction
- [ ] State transitions defined in a single `transitions: dict` map, not scattered
      conditionals

## 2.7 Admin & Seller Endpoints Rework

> **RESOLVED (2026-06-24, updated 2026-07-03).** `client_id` is derived from the
> authenticated seller's JWT session (see 2.8), not from the static global `admin_token`
> and not from a client-supplied `client_id` field. The seller login/session mechanism is
> now fully specified in section 2.8 (OTP + "Sign in with Divar" → JWT + refresh token).

> **Decision:** The Phase 1 `admin_token` (single global secret, no client association) is
> dropped for seller-facing endpoints. Each seller logs in via OTP or Divar OAuth (2.8);
> the upload/posts request is authenticated via `get_current_client_id()`
> (`Authorization: Bearer <JWT>`) which resolves `client_id` from the JWT — never trusted
> from a query param, form field, or request body the caller controls.

> **Dependency on 2.8:** `get_current_client_id` (the auth dependency) is defined and
> implemented in section 2.8. It must be available before this section's endpoints can be
> built. All seller-facing endpoints below use it.

**Tasks:**

- [x] `POST /admin/upload-prices` becomes tenant-scoped: resolve `client_id` via
      `get_current_client_id`, then delete-and-replace that client's rows only
      (`WHERE client_id = :current_client_id`), insert the new rows tagged with that
      `client_id`, commit, then call `refresh_lookup_cache(db, client_id)` (2.4)
- [x] Remove the old global `admin_token` check from this endpoint once the auth dependency
      is in place. Do not run both schemes side by side past this section's completion.
- [x] `POST /seller/posts` — authenticated seller registers their post tokens:
      - Requires `Authorization: Bearer <JWT>` → `get_current_client_id()`
      - Body: `{ "post_tokens": ["TOKEN1", "TOKEN2", ...] }`
      - For each token: `INSERT INTO posts (post_token, client_id) ... ON CONFLICT DO NOTHING`
      - Returns `{ "registered": N, "already_existed": M }`
      - **Future improvement:** confirmed 2026-07-20 that `GET_USER_POSTS` exists as a
        real Kenar API-key permission — this could replace manual `post_token` entry with
        an OAuth-based auto-fetch of the seller's post list, once its scope/endpoint
        mechanics are confirmed against docs (not yet documented in any file reviewed so
        far — needs its own doc lookup before implementing). Not required for Phase 2.

## 2.8 Seller Authentication (OTP + "Sign in with Divar" + Merge)

> Sellers authenticate via two paths: **OTP-to-phone** (the app sends an SMS via an external
> SMS provider) or **"Sign in with Divar"** (OAuth, reusing the 2.3 flow). Both paths end by
> resolving a `clients` row by phone number (the merge key) and issuing the same JWT +
> refresh-token session. There is no username/password mechanism.
>
> The "Sign in with Divar" path is triggered by a link the bot sends in the seller's Divar
> conversation, which opens `/oauth/start` in the seller's browser — this is just a trigger
> mechanism, not a separate auth flow. The actual authentication (state validation, code
> exchange, phone-number lookup, session issuance) goes through the same OAuth callback
> defined in section 2.3.
>
> **Important distinction — do not conflate these two, confirmed 2026-07-20 against live
> Kenar panel permissions:** OAuth here (`USER_PHONE`/`USER_ID` scopes) is used **only** to
> read the seller's phone number/ID for login/merge. It grants the bot no ongoing authority
> over the seller's chats. The bot's ability to reply to *any* customer in the chatbot
> (`addon_{slug}`) conversation comes from a completely separate mechanism: the
> `CHAT_BOT_SEND_MESSAGE` **API-key permission** (app-level, set once in the Kenar panel,
> confirmed present in this app's permission list), used via `X-Api-Key` — no per-seller
> OAuth grant, no `CONVERSATION_SEND_MESSAGE`/`CHAT_SUPPLIER_ALL_CONVERSATIONS_MESSAGE_SEND`
> scope, and no seller action beyond the one-time `/seller/posts` registration (2.7) is
> needed for the bot to answer a customer. Those other scopes belong to Divar's *general
> post-chat* system (`conversation.type == POST`), a different conversation type this
> project's chatbot (`conversation.type == BOT`) does not use — see 2.1's changelog entry
> for the `POST` vs `BOT` distinction.

### New settings in `config.py`

```
JWT_SECRET_KEY: str              # signing key for access JWTs — .env only, never logged
JWT_ALGORITHM: str = "HS256"
ACCESS_TOKEN_LIFETIME_MINUTES: int = 30
REFRESH_TOKEN_LIFETIME_DAYS: int = 30
OTP_LENGTH: int = 6
OTP_LIFETIME_MINUTES: int = 5
OTP_MAX_ATTEMPTS: int = 5
OTP_REQUEST_COOLDOWN_SECONDS: int = 120   # min interval between OTP requests for same phone
OTP_HMAC_KEY: str                # secret key for HMAC-SHA256 OTP hashing — .env only
SMS_PROVIDER_API_KEY: str        # for the SMS provider (Kavenegar etc.)
SMS_PROVIDER_URL: str            # SMS API endpoint
```
### SMS service

> OTP delivery is implemented through an abstract SMS service interface. Authentication
> endpoints depend only on this interface, not on a specific SMS provider implementation.
> The initial implementation may use a single provider (e.g. Kavenegar), while future
> implementations may replace or extend the provider without changing the authentication
> flow.

```python
class SMSService(Protocol):
    async def send_otp(self, phone_number: str, code: str) -> None:
        ...
```


### Endpoints (all in `api/auth.py`)

**`POST /auth/otp/request`**

- [ ] Body: `{ "phone_number": "09..." }`
- [ ] Rate-limits: max 1 OTP per phone per `OTP_REQUEST_COOLDOWN_SECONDS`; reject with 429
      if too soon (check `otp_codes.created_at` for that phone)
- [ ] Deletes any previous unexpired OTP rows for the same phone number before inserting
      (only one active OTP per phone)
- [ ] Generates a random `OTP_LENGTH`-digit code, HMAC-SHA256 hashes it with `OTP_HMAC_KEY`,
      stores in `otp_codes` with `expires_at = now + OTP_LIFETIME_MINUTES`
- [ ] Sends the plaintext OTP via the configured SMS provider service.
      The SMS provider implementation is abstracted behind a service interface
      so providers (e.g. Kavenegar) can be replaced without changing endpoint logic.
- [ ] If the SMS provider call fails (timeout, network error, or non-success response),
      the OTP MUST NOT remain active. Roll back the transaction (or delete the OTP if
      already persisted) and return HTTP 503:
      `{ "error": "sms_unavailable", "message": "Unable to send OTP. Please try again later." }`
- [ ] Returns `{ "message": "OTP sent" }` — do not confirm whether the phone number is
      registered (prevents enumeration)

**`POST /auth/otp/verify`**

- [ ] Body: `{ "phone_number": "09...", "code": "123456" }`
- [ ] Looks up the latest `otp_codes` row for that phone where `expires_at > now`
- [ ] If not found or `attempts >= OTP_MAX_ATTEMPTS`: return 400
- [ ] Increments `attempts`, then verifies `code` against `code_hash` (HMAC-SHA256 with
      `OTP_HMAC_KEY`)
- [ ] On failure: return 400 (do not distinguish "wrong code" from "expired")
- [ ] On success: delete the OTP row, then execute **merge-by-phone** (below), then
      **issue session** (below)

**`POST /auth/refresh`**

- [ ] Reads refresh token from HTTP-only Secure cookie (`refresh_token`)
- [ ] Hashes it (SHA-256), looks up `refresh_tokens` row where `token_hash` matches and
      `expires_at > now`
- [ ] If not found: return 401
- [ ] If found: delete old row, generate new refresh token, insert new row, issue new JWT,
      set new cookie
- [ ] Returns: `{ "access_token": "...", "expires_in": 1800 }`

**`POST /auth/logout`**

- [ ] Reads refresh token from cookie
- [ ] Deletes the matching `refresh_tokens` row (by SHA-256 hash lookup)
- [ ] Clears the cookie
- [ ] Returns 200

**`GET /auth/me`**

- [ ] Requires `Authorization: Bearer <JWT>` → `get_current_client_id()`
- [ ] Returns `{ "id": ..., "phone_number": "09...", "divar_user_id": "..." or null, "created_at": "..." }`
- [ ] Does NOT return tokens, token hashes, or any secret material

### Merge-by-phone logic

```python
async def find_or_create_client(
    db: AsyncSession,
    phone_number: str,
    divar_user_id: str | None = None,
) -> Client:
    """
    Merge key: phone_number.
    1. SELECT FROM clients WHERE phone_number = :phone_number
    2. If found: update divar_user_id if it was null and we now have one. Return row.
    3. If not found: INSERT new clients row with phone_number (and divar_user_id if
       available). Return row.
    Race condition: two simultaneous requests for the same phone could both see "not found"
    and both try to INSERT. The UNIQUE(phone_number) constraint prevents duplicates — the
    second INSERT gets a unique-violation, which the code catches and retries as a SELECT.
    """
```

> NOTE — `phone_number` is the sole merge key. If a seller first signs up via OTP (creates
> a `clients` row with `phone_number`) and later signs in via Divar OAuth (which returns the
> same phone from `get_user`), they merge into the same row. Reverse direction: same logic.
> `divar_user_id` is stored when available but is NOT used as a merge key.

### Session issuance (shared by OTP verify and OAuth callback)

```python
async def issue_session(
    db: AsyncSession, client: Client, response: Response
) -> dict:
    """
    1. Generate JWT: payload = {"client_id": client.id, "exp": now + 30min}
       Sign with settings.JWT_SECRET_KEY using HS256.
    2. Generate random refresh token (64-byte secrets.token_urlsafe).
    3. Hash refresh token (SHA-256), store in refresh_tokens table with
       expires_at = now + 30 days.
    4. Set refresh token in HTTP-only Secure cookie:
       SameSite=Lax, path=/auth, max_age=30*24*60*60.
    5. Return {"access_token": jwt, "expires_in": 1800}
    """
```

### Auth dependency for seller-facing endpoints

```python
async def get_current_client_id(
    authorization: str = Header(...)
) -> int:
    """
    Extracts and validates the JWT from the Authorization: Bearer header.
    Returns the client_id from the JWT payload.
    Raises HTTPException(401) if token is missing, expired, or invalid.
    Used by: POST /admin/upload-prices, POST /seller/posts, GET /auth/me,
    and any future seller-facing endpoint.
    """
```

> NOTE — this replaces the Phase 1 `admin_token` check on seller-facing endpoints.

### Security rules for 2.8

- OTP codes: HMAC-SHA256 hashed at rest with `OTP_HMAC_KEY`, never logged, never returned
  in any API response
- Refresh tokens: SHA-256 hashed at rest, never logged, never returned in API response
  bodies (cookie only)
- JWT secret: in `.env` only, never logged
- `OTP_HMAC_KEY`: in `.env` only, never logged
- All auth endpoints should be rate-limited in production (OTP request has explicit cooldown;
  consider global rate limiting for `/auth/*`)

---