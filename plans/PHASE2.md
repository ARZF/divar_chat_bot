# Phase 2 — Multi-Tenant Conversation Management (Active)

> **Agent rule:** Do not begin Phase 2 tasks until `PLAN.md`'s Active Phase reads
> `Phase 2`, and both Phase 1 bugfix tasks (1.B1, 1.B2) are checked off in `PHASE1.md`.
>
> Cross-references: 2.1/2.3 assume Kenar chatbot docs behavior confirmed in this file's
> own notes and the Changelog (see `CHANGELOG.md` for the dated evidence trail if you
> need to re-verify a claim). 2.3 builds on 1.B1's `refresh_access_token` fix — see
> `PHASE1.md` if you need that context.
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

- [x] Create the `posts` model as above
- [x] Implement a parser function `parse_start_message(text: str) -> Optional[Tuple[str, Optional[str]]]`
      returning `(touchpoint_name, token_or_none)` if `text` matches `/start <TOUCHPOINT>
      [<token>]`, else `None`. Must handle all five touchpoint names listed above, and must
      not assume a token is present (handles bare `/start MY_DIVAR` correctly).
- [x] In the webhook handler: on first message in a `conversation_id`, if no DB row exists for
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
- [x] For all messages **after** the first in a given `divar_conversation_id`: look up the
      existing `conversations` row by `divar_conversation_id` to retrieve the already-resolved
      `client_id`. Do not re-parse `/start` on every message — only the first one carries it.
- [x] **Unresolved conversations have no persisted row, so they are handled statelessly on
      every message.** Because nothing is persisted for an unresolved conversation (see NOTE
      below), the "is this the first message?" DB-row-existence check will report *not found*
      for **every** message in that conversation. This is intentional and correct: each message
      re-runs the `/start` parse, fails to resolve a `client_id` again (the `/start` launch
      message is never redelivered — see NOTE), and re-sends `settings.UNRESOLVED_CLIENT_MESSAGE`.
      Do **not** attempt to suppress the repeat reply — doing so would require persisting a
      per-conversation marker, which this design deliberately avoids. The reply is idempotent
      in effect (same canned message every time) and safe under Divar's at-least-once webhook
      redelivery.
- [x] **Add to `config.py`:** `UNRESOLVED_CLIENT_MESSAGE: str` — Persian message asking the
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
                UNIQUE (client_id, divar_conversation_id)  -- composite; ON CONFLICT target
                UNIQUE (divar_conversation_id)             -- global, migration 0004

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

> NOTE — `conversations.divar_conversation_id` uniqueness: **both** a composite
> `(client_id, divar_conversation_id)` and a standalone global `UNIQUE
> (divar_conversation_id)` (migration `0004`, 2026-08-13). This is **not** the
> `products` reasoning — that one is about *seller-supplied* values legitimately
> colliding (two sellers both listing "iPhone 13"). A `divar_conversation_id` is
> **assigned by Divar**, so one ID belongs to exactly one conversation and
> therefore exactly one client; there is nothing for two tenants to collide on.
> The global constraint is load-bearing: the chatbot's entry-point lookup
> (`_lookup_conversation`) keys on `divar_conversation_id` alone — it *cannot*
> filter by `client_id`, since resolving `client_id` is its entire job — so
> without it, `scalar_one_or_none()` would raise `MultipleResultsFound`.
> The composite is kept because it is the named `ON CONFLICT` target that makes a
> redelivered webhook a silent no-op; the global one raises `IntegrityError`
> instead, which `_resolve_new_conversation` catches and fails safe on. See
> `CHANGELOG.md` 2026-08-13 for the evidence basis and residual risk.

**Tasks:**

- [x] Setup `db/session.py` with an async SQLAlchemy engine (`asyncpg` driver) + async
      `get_db` dependency (yields `AsyncSession`)
- [x] Create all models above with exact fields, including composite unique constraints
- [x] Setup Alembic; first migration auto-generated from models
- [x] Replace in-memory `seen_conversations: set` with the DB-row-existence check described
      in 2.1 — implemented as a single atomic upsert
      (`INSERT ... ON CONFLICT (client_id, divar_conversation_id) DO NOTHING`, checking
      whether a row was actually inserted), to avoid the double-welcome race described below
      — the upsert landed 2026-08-11, but the **"checking whether a row was actually
      inserted"** half was missing until 2026-08-13 (`is_new` was hardcoded `True`); this box
      was ticked early. `is_new` now derives from `result.rowcount == 1`.
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
> (`GET /v1/open-platform/users`) — which 2.8's "Sign in with Divar" login/merge-by-phone
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
> **get_user response shape — confirmed live (2026-07-20):** A real successful
> `GET /v1/open-platform/users` response returned all three fields together:
> ```json
> {
>   "phone_numbers": ["<phone_number>"],
>   "phone_number": "<phone_number>",
>   "user_id": "<per-app-user-id>"
> }
> ```
> `phone_number` is a singular string, `phone_numbers` is an array containing the same phone
> number, and `user_id` is a singular string. This resolves the apparent documentation
> conflict: the live API includes both phone representations simultaneously. The
> implementation must still parse defensively for backward compatibility: prefer a non-empty
> `phone_number`, otherwise use the first non-empty string in `phone_numbers`. Read `user_id`
> directly from its singular field when present.
>
> **HTTP method — resolved (2026-07-20):** `get_user.md` also disagrees with `ReadMe.md` on
> method (`GET` vs `POST`) for this same endpoint. Confirmed via live test: `GET` reaches
> token validation (`"Invalid access token"`), `POST` is rejected at the access-control
> layer (`"RBAC: access denied"`) before token validation even runs. **`GET` is correct** —
> `get_user_phone_number()` must use `GET`, not `POST`.

**`services/divar.py` — corrected scope of changes for Phase 2:**

- [x] `send_message(conversation_id: str, text: str) -> bool` and
      `get_conversation(conversation_id: str) -> dict` **keep their Phase 1 signatures
      unchanged** — they continue to use the single global `settings.DIVAR_API_KEY` via
      `X-Api-Key`, exactly as today. No `client_id` or `access_token` parameter is added to
      either function. The earlier plan revision's `access_token: str` parameter on these two
      functions is **retracted**.
- [x] Fix `refresh_access_token()` per bugfix 1.B1 (wrong attribute name, missing `code` field)
      — this function still exists and is still needed, but only for the **OAuth/phone-number**
      use case below, not for `send_message`/`get_conversation`.
- [x] Add `get_user_phone_number(access_token: str) -> str | None` — calls
      `GET /v1/open-platform/users` (confirmed via live test 2026-07-20 — see changelog;
      `docs/oauth/ReadMe.md`'s `POST` example is stale) with `X-Api-Key` +
      `Authorization: Bearer {access_token}`,
      returns the phone number from the confirmed response shape above (prefer the non-empty
      `phone_number` string, then fall back to the first non-empty string in `phone_numbers`),
      or `None` if both fields are absent/empty or the API call fails. Does not raise — caller
      decides the failure behavior.
      Used only by 2.8's OAuth-login callback.
- [x] **Split the single `_headers()` into two builders** so auth mechanisms are no longer
      conflated (today `_headers()` sends *both* `X-Api-Key` and `Authorization: Bearer` on every
      call, which only works by accident): `_api_key_headers() -> dict` (`X-Api-Key` only —
      used by `send_message`/`get_conversation`) and `_oauth_headers(access_token: str) -> dict`
      (`X-Api-Key` + `Authorization: Bearer {access_token}` — used only by
      `get_user_phone_number`). Confirmed against docs: `POST /chat/bot/conversations/{id}/messages`
      requires `X-Api-Key` only (no Bearer), while `GET /v1/open-platform/users` requires both.
- [x] **Remove the OAuth refresh-on-401/403 block from `send_message` and `get_conversation`.**
      These endpoints authenticate via the API key, not the OAuth token, so a 401/403 from them is
      not a token-expiry condition — refreshing `settings.DIVAR_ACCESS_TOKEN`/`DIVAR_REFRESH_TOKEN`
      there is dead logic that also mutates global token state for no reason. `refresh_access_token`
      remains, used only by the OAuth/phone-number flow (2.8).


**OAuth entry points — now scoped only to the login/phone-number use case (2.8), not to
chat-sending permission, since chat-sending needs no OAuth at all:**

**`GET /oauth/start`** *(no path param — single purpose now: "Sign in with Divar")*

- [x] Generates a random, unguessable `state` value, stores `state -> "LOGIN"` (in-memory,
      short TTL — short-lived handshake artifact, not durable data)
- [x] Redirects to:
      ```
      https://oauth.divar.ir/oauth2/auth?response_type=code
        &client_id={settings.DIVAR_APP_SLUG}
        &redirect_uri={settings.DIVAR_REDIRECT_URI}
        &scope=USER_PHONE USER_ID offline_access
               CHAT_SUPPLIER_ALL_CONVERSATIONS_MESSAGE_SEND
               CHAT_SUPPLIER_ALL_CONVERSATIONS_READ
        &state={generated_state}
      ```
      `offline_access` causes Divar to also return a `refresh_token` (valid 30 days per the
      doc) — needed since a seller's session shouldn't require re-authenticating with Divar
      every `expires_in` (3600s per the doc) seconds. **Note the corrected scope:** `USER_PHONE`
      replaces the previous, unconfirmed `CHAT_BOT_SEND_MESSAGE` — that name does not appear
      anywhere in `docs/oauth/ReadMe.md`'s scope list and was likely a conflation with the
      chatbot conversation doc's separate (and differently-mechanized) permission language.
      > **Scope string updated 2026-08-16 (§2.9):** the two `CHAT_SUPPLIER_ALL_CONVERSATIONS_*`
      > scopes above were added by §2.9's "New OAuth scopes" item. This block previously listed
      > only `USER_PHONE USER_ID offline_access` and had gone stale against the implementation.
      > §2.9 owns those two scopes; §2.3 owns the other three. Do not remove either set when
      > editing this list.

**`GET /oauth/callback`**

- [x] Reads `state` and `code` from query params
- [x] **Rejects with `HTTP 400` if `state` is missing or doesn't match the stored `"LOGIN"`
      mapping** (per-client version of the 1.B2 bugfix)
- [x] Exchanges `code` for tokens: `POST https://oauth.divar.ir/oauth2/token` with
      `grant_type: "authorization_code"`, `code`, `client_id` (=`DIVAR_APP_SLUG`),
      `client_secret`, `redirect_uri` — exactly per the doc's step 3 example
- [x] Calls `get_user_phone_number(access_token)` to get the seller's phone number
- [x] **Failure path — phone number unavailable:** If `get_user_phone_number()` returns
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
- [x] Hands off to 2.8's find-or-create-by-phone logic to resolve (or create) the `client_id`
- [x] Stores `access_token`, `refresh_token`, `token_expires_at` on the resolved `clients` row
- [x] Removes the `state` mapping after use (one-time use)
- [x] Issues the seller session per 2.8 and redirects/responds accordingly — does not return
      the raw token response to the browser

> **Temporary callback response (2026-07-26):** Until a seller frontend/panel URL exists,
> `GET /oauth/callback` returns the same JSON `{"access_token", "expires_in"}` contract as
> OTP login and sets the HTTP-only refresh cookie. Once a seller-facing frontend/panel
> destination is defined, replace this with a `RedirectResponse`; this JSON response is not
> the permanent browser-flow design.

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
- [x] **`refresh_lookup_cache(db, client_id)` — done.** Function exists and is
      correctly called after every admin upload (via `load_prices_to_db`), **and** is
      now called once per known `client_id` at app startup in `main.py`'s lifespan.
      Startup warming enumerates clients with catalog data only
      (`SELECT DISTINCT client_id FROM products` — a client with no products has nothing
      to warm), loops `refresh_lookup_cache` for each, and is wrapped so a warming
      failure logs and continues without blocking startup. The lazy-load-on-first-miss
      fallback in `chatbot.py` is retained as the safety net for clients that upload
      after boot or are missed at startup.
- [x] **`get_price(db, client_id, item_name, threshold=70.0)` — done.** Now async with
      a required `db: AsyncSession` param and defense-in-depth: after a fuzzy cache hit
      resolves a `normalized_name`, the row is re-fetched from `products` filtered by
      `client_id` + `normalized_name`, and the **DB** `item_name`/`price` (source of
      truth) is returned. If the cache hit but the DB row is gone (deleted/replaced
      catalog since warming) → logged as a cache/DB divergence and `None` returned
      (treated as not found). This catches stale prices, since-deleted products, and
      belt-and-suspenders re-verifies tenant scoping. Callers updated:
      `_handle_price_intent` in `services/chatbot.py` is now async and threads `db`
      through (the `handle_bot_reply` session is reused — no ripple beyond the
      chatbot service).

> **Known residual (out of scope this pass, 2026-07-28):** `get_all_matching_prices`
> (the Tier-1 substring path in `services/chatbot.py`'s `_handle_price_intent`) and
> `find_top_matches` still read straight from the in-memory cache with no DB re-fetch.
> They therefore carry the same cache-staleness exposure `get_price` had before this
> pass (stale price, deleted product). Left unaddressed deliberately — the
> defense-in-depth requirement was scoped to `get_price` only. Candidate for a future
> improvement (see `CHECKLISTS.md`'s Future Improvements) if substring-path staleness
> becomes a real concern. The lazy refresh on cache-miss + startup warming mitigate
> the window.
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

- [x] `handle_bot_reply` keeps its current Phase 1 signature `(conversation_id, user_text)`
      — opens its own DB session internally rather than receiving one as a parameter.
      `client_id` is resolved inside from the DB (via 2.1), not passed from the webhook URL.
- [x] Inside, it now: resolves/loads the conversation's `client_id` per section 2.1, sets
      `client_id_var` for logging context, runs price lookup scoped per section 2.4, and
      calls the reworked `divar.py` functions (which use the global API key, not per-client
      tokens — see 2.3 correction)

## 2.6 State Machine

States: `START → MAIN_MENU → PRICE_MENU | SERVICE_MENU | HUMAN_SUPPORT`

> **DONE (2026-08-11).** Wired in `services/state_machine.py` + `services/chatbot.py`.
> `HUMAN_SUPPORT` and the `back`/`exit` edges are **defined but text-unreachable this
> phase** — there is no persistent human-support mode (SUPPORT/WARRANTY hand out
> `SUPPORT_PHONE_NUMBER` and stay in `MAIN_MENU`), and button navigation belongs to
> Phase 3. Do not delete them as dead code. See `CHANGELOG.md` 2026-08-11.

- [x] Store `current_state` in `conversations.current_state`
- [x] On each webhook: load state → process → save updated state as a single transaction
- [x] State transitions defined in a single `transitions: dict` map, not scattered
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

## 2.9 Supplier-Wide Chat Messaging (New — additive to the existing chatbot, not a replacement)

> **Do not begin until 2.1, 2.4, 2.5, 2.6 are complete.** This section is intentionally
> sequenced after the rest of Phase 2's core chatbot hardening — it's higher-risk (new
> OAuth scopes, an external event-subscription lifecycle, a recurring re-subscription
> obligation on every token refresh) and entirely additive, so nothing is lost by
> finishing the foundational chatbot work first. See `CHANGELOG.md` (2026-07-2X entries)
> for the full investigation trail behind this section's design.
>
> **STATUS (audited 2026-08-16): substantially implemented, one item left.** The gate
> (2.1, 2.4, 2.5, 2.6) was satisfied and this section was then built out across commits
> `1e89184`, `cfcd4c1`, `182d915`, `593453b`, `167658f`, plus the refresh-token fix that
> followed the audit of those commits. The scope string, webhook branch,
> `send_supplier_message`, `register_event_subscription`, the post-login registration, the
> reply path, and re-registration on refresh are all in place. **One item remains open:** the
> `/oauth/dev/start` scopes. The `refresh_access_token()` per-seller defect found by the audit
> is fixed — see the resolved-defect note at the end of this section, including the SQLite
> testing limitation on the row lock.
>
> **This is NOT a migration.** The existing chatbot (`conversation.type == "BOT"`,
> `services/divar.py::send_message()`, `api/webhook.py`'s `NEW_CHATBOT_MESSAGE` handling,
> the `/start`-message resolver in 2.1) stays exactly as-is, untouched, and continues
> working via `X-Api-Key` with no OAuth involved. This section adds a **second, parallel**
> conversation system — Divar's general post-chat (`conversation.type == "POST"`) — so
> your bot can also reply to buyers in a seller's ordinary Divar post chats, not just the
> `divar.ir/chat/addon_{slug}` chatbot. Both systems share the same webhook URL and must
> be dispatched by `payload.type`, not replaced.

### Why this is a separate system (confirmed against docs, not inferred)

| | Existing chatbot (untouched) | New: supplier-wide chat (this section) |
|---|---|---|
| `conversation.type` | `BOT` | `POST` |
| Webhook event `type` | `NEW_CHATBOT_MESSAGE` | `NEW_MESSAGE` |
| Webhook payload field | `new_chatbot_message` | `new_message` |
| Reply endpoint | `POST /v1/open-platform/chat/bot/conversations/{id}/messages` | `POST /v2/open-platform/conversations/{id}/messages` |
| Reply auth | `X-Api-Key` only | `X-Api-Key` + seller's OAuth `Authorization: Bearer` |
| Reply body field | `text_message` | `message` |
| Send permission | `CHAT_BOT_SEND_MESSAGE` (API-key, app-level) | `CHAT_SUPPLIER_ALL_CONVERSATIONS_MESSAGE_SEND` (OAuth, per-seller) |
| Client-id resolution | Parse `/start` message (2.1) — no `post_token` on this conversation type | `conversation.post_token` present directly on every message — no `/start` parsing needed |

### New OAuth scopes (real `/oauth/start` flow — `api/oauth.py`)

- [x] Add `CHAT_SUPPLIER_ALL_CONVERSATIONS_MESSAGE_SEND` and
      `CHAT_SUPPLIER_ALL_CONVERSATIONS_READ` to the real `/oauth/start` scope string
      (confirmed both are flat scopes — no `RESOURCE_ID`/`IDENTIFIER` needed, per
      `docs/chat/users_conversations.md` and `docs/events/ReadMe.md`).
- [ ] Add the same two scopes (`CHAT_SUPPLIER_ALL_CONVERSATIONS_MESSAGE_SEND` and
      `CHAT_SUPPLIER_ALL_CONVERSATIONS_READ`) to `/oauth/dev/start` as well, so the
      dev bootstrap tool can be used to manually test this section's endpoints.
      > **Still open (audited 2026-08-16).** `/oauth/dev/start` still requests only
      > `USER_PHONE USER_ID offline_access`. Note this item conflicts with the
      > 2026-07-2X CHANGELOG entry, which recorded the same thing as an *unresolved open
      > question* rather than a decided task — the conflict is unresolved either way, so
      > the box stays open. Consequence while open: the dev bootstrap tool cannot mint a
      > token capable of exercising `send_supplier_message` or `register_event_subscription`.

> **Scope encoding — open question, not yet verified against the live API (2026-08-16).**
> `api/oauth.py` builds the authorize URL with `urlencode(params)`, which defaults to
> `quote_plus` and therefore emits space-separated scopes as `+`
> (`scope=USER_PHONE+USER_ID+...`). `docs/oauth/ReadMe.md` specifies `SCOPE_1 SCOPE_2` or
> `SCOPE_1%20SCOPE_2` literally, and never shows `+`. This predates §2.9 (it also affects
> `/oauth/dev/start`) and has not been observed to fail — Divar's OAuth server appears to be
> Ory (`ory_at_`-prefixed tokens), whose Go query parser decodes `+` as a space, which would
> make the current form work in practice. Do not "fix" this blind: confirm against the live
> authorize endpoint first, then switch to `urlencode(params, quote_via=quote)` only if the
> `+` form is actually rejected.

### New: `services/divar.py` — `send_supplier_message()` (new function, `send_message()` untouched)

- [x] Add `send_supplier_message(conversation_id: str, text: str, access_token: str) -> bool`:
      - `POST {BASE_URL}/v2/open-platform/conversations/{conversation_id}/messages`
      - Headers: `_oauth_headers(access_token)` (already exists from 2.3 — reuse, don't
        duplicate)
      - Body: `{"type": "TEXT", "message": text}` — note the field is `message`, not
        `text_message` (System 2's field name); do not reuse System 2's payload builder
        as-is if one exists.
      - Do **not** modify `send_message()` or its signature. Both functions coexist.

### Webhook: additive branching, not replacement (`api/webhook.py`, `schemas/webhook.py`)

- [x] Extend `schemas/webhook.py`'s `EventType` enum to add `NEW_MESSAGE` alongside the
      existing `NEW_CHATBOT_MESSAGE` member.
- [x] Add a `new_message: Optional[ChatMessage]` field to `WebhookPayload`, alongside the
      existing `new_chatbot_message` field — additive, both fields coexist on the model.
      > **Naming note:** the model is actually called `WebhookSchema` in
      > `schemas/webhook.py`, not `WebhookPayload` as written above. The field was added to
      > the real class; only this spec's name for it was wrong.
- [x] In `api/webhook.py`'s handler, branch explicitly on `payload.type`:
      ```python
      if payload.type == EventType.NEW_CHATBOT_MESSAGE:
          # existing logic, untouched
          ...
      elif payload.type == EventType.NEW_MESSAGE:
          # new logic (see below)
          ...
      ```
      > **Implemented as two sequential `if` blocks that each `return`, not `if`/`elif`.**
      > Behaviourally identical (both branches are terminal) with a final catch-all
      > `{"status": "ignored"}` 200 for unrecognised types. Accepted as-is.
- [x] For `NEW_MESSAGE` events: ignore (200, no-op) any message where
      `sender.side != "BUYER"` — this excludes both the seller's own messages and your
      bot's own sent replies (which Divar echoes back with `sender.side == "SELLER"`,
      confirmed in `docs/events/ReadMe.md`'s own example payload).
- [x] For `NEW_MESSAGE` events from a `BUYER`: resolve `client_id` directly via
      `conversation.post_token` → `posts.client_id` lookup (the existing `posts` table
      from 2.1/2.2 — no new table needed). **No `/start`-message parsing applies here** —
      `post_token` is present on every message of this conversation type, not just a
      one-time launch message.
       - If `post_token` doesn't resolve to a known `client_id` (e.g. seller never
         registered that post, or posts row missing): log a warning with `post_token` and
         `conversation_id` for later investigation, send **no reply** (there is no
         bot-initiated conversation to inject into — the buyer is messaging the seller
         directly), and return 200 to Divar immediately (do not trigger a retry for an
         event we have deliberately chosen not to act on).
       > **Resolution point (2026-08-16):** this closes the second of the two open questions
       > recorded in the 2026-07-2X CHANGELOG entry. The lookup happens in
       > `services/chatbot.py::handle_supplier_message` (inside the background task), not in
       > the webhook handler — so the 200 is returned before resolution is even attempted,
       > which satisfies the "return 200 immediately" requirement by construction. The
       > warning is logged with both `post_token` and `conversation_id` as specified.

### Event subscription registration (new, one-time per seller after login)

- [x] After a successful `/oauth/callback` login (2.3) that includes the new scopes,
      register the event subscription:
      ```
      POST https://open-api.divar.ir/v1/open-platform/events/subscriptions
      X-Api-Key: {api_key}
      Authorization: Bearer {seller's fresh access_token}

      {"event_type": "NEW_MESSAGE_ON_POST"}
      ```
      (no `event_resource_id` → all of that seller's posts, per
      `docs/events/ReadMe.md`; requires the app-level `EVENTS_REGISTER_SUBSCRIPTION`
      permission, already present in this app's Kenar panel permissions.)
      > **Failure handling (2026-08-16):** a failed registration is logged as a warning with
      > `client_id` and does **not** fail the login — the seller is still authenticated and
      > their session issued. There is no automatic retry, so that seller receives no
      > `NEW_MESSAGE` events until a registration succeeds. Accepted deliberately: failing
      > the whole login over a subscription error would be worse. Revisit if it proves
      > common in practice.
- [x] **Mandatory, recurring — do not treat as one-time setup:** per
      `docs/events/ReadMe.md`, this subscription is tied to the specific access token
      used to create it. **Every time a seller's OAuth token is refreshed
      (`refresh_access_token()`), the subscription must be re-registered with the new
      token**, or that seller's buyer messages silently stop being delivered with no
      error surfaced anywhere. This needs to be wired into whatever code path eventually
      handles per-seller token refresh (not yet built — flag this dependency explicitly
      wherever that refresh-scheduling work happens).
      > **Done 2026-08-16, for the one refresh path that exists.**
      > `services/chatbot.py::_refresh_supplier_token` re-registers with the new access
      > token immediately after persisting it. Failure is logged as a warning and
      > swallowed — the reply the refresh was performed for still goes out; the
      > alternative (dropping the buyer's message over a subscription error) is worse.
      > **This is not blanket coverage:** it only fires on the reply-path refresh. If a
      > background refresh *scheduler* is ever added, it must call
      > `register_event_subscription` too — the obligation is per-refresh, not
      > per-code-path.

### Resolved 2026-08-16 — `refresh_access_token()` was not per-seller

> **Fixed.** Kept as a record of the defect, since the shape of it is easy to reintroduce.
>
> `refresh_access_token()` took the current access token as a parameter (per 1.B1) but read
> **`settings.DIVAR_REFRESH_TOKEN`** from `.env` for the `refresh_token` field of the request
> body. Its only per-seller caller then persisted whatever came back onto **that seller's**
> `oauth_tokens` row. So any seller with an expired access token was refreshed against the
> global bootstrap credential, and the result overwrote their stored tokens. Commit `167658f`
> had corrected this function's *return* arity without touching its *input*, which is where
> the defect lived.
>
> **The fix.** `refresh_access_token(current_access_token, refresh_token)` now takes the
> refresh token explicitly — no `settings` read remains in it. Both arguments must belong to
> the same seller, which the docstring states, because Divar rotates the refresh token on
> every call. The refresh/persist logic moved out of `handle_supplier_message` into
> `services/chatbot.py::_refresh_supplier_token(client_id) -> Optional[str]`, which returns
> `None` on failure to mean "send nothing."
>
> **Concurrency, handled in the same pass.** Two buyer messages arriving together for a
> seller with an expired token spawn two background tasks. Since Divar rotates and
> invalidates the refresh token on every call, both refreshing would leave whichever pair
> lost the write unusable — that seller could then never refresh again, with no error
> surfaced. `_refresh_supplier_token` therefore claims the row with `SELECT ... FOR UPDATE`
> and **re-checks the expiry under the lock**, so a task that waited reuses the winner's
> token instead of refreshing again. This follows the `delete(...).returning(...)`
> atomic-claim precedent from the 2026-08-13 app-session refresh work: make the race
> impossible in SQL rather than defending against it afterwards.
>
> **Testing limit — read before trusting the tests here.** The suite runs on SQLite, which
> **silently drops `FOR UPDATE`** from the compiled statement (verified: the clause is absent
> from the SQLite compilation and present in the PostgreSQL one). So no test in this suite
> can observe the lock actually serializing anything, and a two-task `asyncio.gather` test
> was deliberately **removed** rather than left passing for the wrong reason — it would have
> asserted nothing about production. Coverage is instead: a dialect-level test pinning that
> the statement compiles to `... FOR UPDATE` on PostgreSQL and that
> `.with_for_update()` is still in the source, plus a test driving the woken-up-loser branch
> directly. **The lock's real behaviour remains unverified against PostgreSQL** — worth an
> integration check whenever a live DB is available.
>
> **Left alone deliberately.** `settings.DIVAR_ACCESS_TOKEN` and
> `settings.DIVAR_REFRESH_TOKEN` are now unused by all source code (only a test and
> `.env.example` mention them). They were **not** removed — that touches every deployment's
> `.env` plus six test modules, which does not belong in a bug-fix commit. Logged in
> `CHECKLISTS.md` under Config Cleanup next to the existing `admin_token` item.


### Explicitly out of scope for this section

- Modifying, removing, or migrating anything in the existing chatbot's code path
  (`send_message`, `NEW_CHATBOT_MESSAGE` handling, 2.1's `/start` resolver)
- Production Kenar panel scope approval (per the Pre-Production Checklist, broad OAuth
  scopes like this need individual review/approval — expect scrutiny, plan for it
  separately, not assumed automatic)

---