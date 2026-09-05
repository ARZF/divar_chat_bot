# Phase 3 — Supervised Execution Plan

> **Source of truth:** `plans/PHASE3.md` on `main` at `34cfff11376dc91c70c0537c9eb5bfa29e571475`.
>
> This document sequences that plan for one developer supervising one coding
> agent. It does not add product scope. Where `PHASE3.md` deliberately leaves
> an external capability or business choice open, this plan stops at a decision
> gate rather than filling in the gap.

## How to run this plan

1. Complete **one numbered step only** per agent task/commit. Do not batch a
   milestone into a single prompt.
2. Before coding, the agent reads `plans/PLAN.md`, the named section(s) of
   `plans/PHASE3.md`, and only the existing files needed for that step.
3. The agent reports the files it expects to change and waits if the requested
   work requires a product, API, payment, or security decision not specified in
   `PHASE3.md`.
4. The developer reviews the step's acceptance criteria and its visual checks,
   then explicitly opens the next step. A failed review returns to the same
   step; it never becomes “follow-up work”.
5. Run the step's focused tests and `pytest` before the suggested commit. Do
   not commit unrelated cleanup.

### Mandatory agent envelope (attach to every coding prompt)

```text
Implement only Phase 3 execution step <N>: <title>.

Read plans/PLAN.md, the cited PHASE3.md sections, this execution step, and the
existing files needed to trace the current flow. State the exact files you will
modify before coding. Preserve existing Phase 1/2 behavior and do not refactor
unrelated code.

Constraints: FastAPI + Jinja2 + project-owned CSS + vanilla JavaScript only;
no frontend build system or separate frontend service; reuse existing auth,
price normalization/import, and tenant architecture; derive client_id only
with get_current_client_id; no secrets/tokens in HTML, URLs, logs, or static
assets; all schema changes use Alembic; add the smallest relevant tests.

Stop and report a blocker instead of guessing an unsupported Divar API,
payment decision, schema field, or authentication mechanism. Run focused tests
and pytest. Return changed files, commands/results, and any manual review URL.
```

### Universal review gates

**Security/architecture gate (every server or API step):** verify that no
browser-supplied `client_id` is trusted; every seller query is scoped by the
JWT-derived client; cross-tenant resources return a non-leaking `404`; no
business SQL/Divar calls are placed in templates or JavaScript; no secrets,
refresh token, OAuth token, OTP code/hash, or JWT appears in responses/logs.

**Visual anti-AI-slop gate (every visual step):** the portal is Persian-first,
RTL-first, practical, and information-dense without being crowded. Inspect at
desktop and narrow-mobile widths. Reject generic “startup SaaS” styling:

- no purple/blue gradient hero, glassmorphism, aurora blobs, or decorative
  noise used as a substitute for hierarchy;
- no sea of identical floating rounded cards, excessive shadows, pill-shaped
  controls, or cards nested within cards;
- no huge marketing headline, fake metrics, testimonial carousel, or generic
  AI illustration not requested by `PHASE3.md`;
- no emoji as product icons, no arbitrary icon mixture, and no icon-only
  controls without an accessible Persian label/tooltip;
- use a restrained neutral surface, a small semantic color set, visible focus
  states, readable Persian type, clear table/form density, and status colors
  only when they carry meaning;
- use the same spacing, borders, button hierarchy, empty/loading/error states,
  and sidebar/navigation treatment across pages; do not add a component
  framework to obtain them.

Record the visual review against §3.2.4's ten Design Review Gate questions:
product-specific marketplace feel; task value of visual elements; unnecessary
decoration; information density; Persian typography; RTL; hierarchy without
effects; task-fit for tables/forms/conversations/settings; intentional mobile
behavior; and no pattern selected merely because it is common in generated
SaaS UI. Any “yes” to the last question requires simplification before approval.

**Test gate (every step):** a page rendering is not completion. Run the
smallest tests that can fail for the changed behavior, then `pytest`. Capture
manual browser evidence for a changed HTML/CSS/JS flow. If an unrelated
pre-existing test fails, record it separately and do not mask it.

## Sequence overview

| Slice | Steps | Review gate |
| --- | --- | --- |
| Foundation | 1–5 | F1 |
| Public pages | 6–8 | F2 |
| Authentication and shell | 9–13 | F3 |
| Products | 14–18 | F4 |
| Listings | 19–22 | F5 |
| Conversations and settings | 23–25 | F6 |
| Packages/subscriptions | 26–29 | F7 |
| Hardening and release | 30–32 | F8 |

---

## Foundation

### 1. Confirm Phase 3 starting state — **review/decision gate; no coding**

**Depends on:** none. **Read:** `PLAN.md`, `PHASE3.md` §§3.0–3.2, 3.24–3.26,
`STATUS.md`, and the Phase 2 status note routed from `PLAN.md`.

**Agent scope/instructions:** report whether `PLAN.md` still names Phase 3 and
whether any deferred Phase 2 item blocks the first web slice. Inspect the
existing FastAPI router, auth, OAuth, seller, model, and test layout. Do not
edit code or “finish” Phase 2.

**Accept:** the developer has a written start-state note naming the existing
router inclusion pattern, test command, and any blocker. **Stop:** if Phase 3
is not active or a Phase 2 dependency is required. **Commit:** none.

### 2. Add Jinja2/static plumbing

**Depends on:** 1. **Read:** §§3.2.1–3.2.2, 3.5, 3.21.

**Scope:** add only the template/static dependencies and FastAPI configuration
needed to serve project-owned `templates/` and `static/`; include the dedicated
HTML router using existing application conventions. Do not add pages beyond a
minimal renderable probe, authentication, or dashboard behavior.

**Accept:** an HTML route can render a template; a CSS and JS probe are served;
no Node/frontend build setup exists; existing API routes still start. **Review:**
asset paths work behind the app, and no static asset contains credentials.
**Commit:** `feat(web): add template and static asset foundation`.

### 3. Create the base template and global interaction hooks

**Depends on:** 2. **Read:** §§3.2.2–3.2.3, 3.16, 3.18.

**Scope:** create `base.html`, global CSS, and small global JS only. Set
`lang="fa"` and `dir="rtl"`; provide metadata blocks, CSS/JS loading, and
shared navigation/content hooks. Do not create page-specific UI or a giant
application script.

**Accept:** two minimal child templates can share the base without duplicated
document markup; keyboard focus is visible; no console errors. **Review:** run
the universal visual gate on the base typography, spacing, and RTL direction.
**Commit:** `feat(web): add rtl base template and shared assets`.

### 4. Establish responsive layout primitives

**Depends on:** 3. **Read:** §§3.2.3–3.2.4, 3.18, 3.23.

**Scope:** add only reusable CSS primitives required by planned pages: content
container, forms, buttons, alerts, tables, pagination, loading/empty states,
and responsive breakpoints. Define the small shared typography, colour,
spacing, border, radius, shadow, status-indicator, navigation, and form/table
vocabulary required by §3.2.4. Use semantic HTML and CSS custom properties if
helpful; no bespoke component library.

**Accept:** controls are usable at desktop, tablet, and mobile widths and RTL
table overflow has an intentional behavior. The shared system is small and
consistent rather than a general-purpose component framework. **Review:**
apply the visual gate; specifically reject excessive rounded cards/shadows,
poor Persian scanning, and a mobile layout that merely shrinks desktop UI.
**Commit:** `feat(web): add responsive rtl interface primitives`.

### 5. Foundation integration check — **review gate**

**Depends on:** 2–4. **Scope:** tests and fixes limited to the foundation.

**Accept:** template/static routes have focused tests; `pytest` passes; the
developer visually verifies CSS/JS loading in a production-like app run.
**Stop:** do not start public UI until F1 is approved. **Commit:**
`test(web): cover template and static asset serving` (only if tests were not
committed with their feature steps).

---

## Public website

### 6. Build the public navigation and home page

**Depends on:** F1. **Read:** §§3.3.1, 3.18.

**Scope:** implement `GET /` and its template. Communicate only the stated
benefits: automated customer communication, price lookup, product catalogue
management, and chatbot automation. Add login/register and pricing CTAs. Do
not expose seller data or invent social proof/features.

**Accept:** anonymous `GET /` returns 200 and the CTAs lead to `/login` and
`/pricing`. **Review:** visual gate, especially no generic SaaS hero/gradient,
fake metrics, or decorative imagery. **Commit:** `feat(web): add public home page`.

### 7. Isolate the public plan source and render pricing

**Depends on:** 6. **Read:** §§3.2.4, 3.3.2, 3.10.1, 3.10.4–3.10.6.

**Scope:** create `GET /pricing` with an isolated source for available packages
that does not spread package logic through templates. Reuse an already present
plan source if it exists; otherwise implement only the smallest temporary,
clearly isolated display source allowed by §3.3.2. Do not create checkout,
fake purchase states, or select a gateway.

**Accept:** anonymous pricing returns 200, has no seller data, and displays no
claim that payment works. It favours clear comparison/one primary action over
decorative plan cards, fake urgency, discounts, or “most popular” ribbons.
**Stop:** if the only viable source requires
inventing plans/prices; request the maintainer’s values instead. **Commit:**
`feat(web): add public pricing page`.

### 8. Public-page review gate — **review gate**

**Depends on:** 6–7. **Scope:** route/template tests and local fixes only.

**Accept:** public page tests pass, pages are responsive/RTL, navigation works,
and the universal visual gate passes. The home page has no invented metrics,
testimonials, logos, or claims and does not resemble a generic startup landing
page. **Stop:** F2 approval is required before
auth work. **Commit:** `test(web): cover public website routes`.

---

## Authentication and dashboard shell

### 9. Render login and OTP pages without changing auth logic

**Depends on:** F2. **Read:** §§3.2.4, 3.4.1–3.4.2, 3.15–3.16.

**Scope:** add `GET /login` and `GET /login/otp`, shared auth presentation,
phone/code fields, validation/error placeholders, resend affordance, and a
plain `/oauth/start` link. Do not add an auth endpoint, a password, or token
storage.

**Accept:** pages render anonymously; the Divar control is an ordinary link;
forms are labelled and keyboard usable. **Review:** the login/OTP workflow is
direct and distraction-free—no marketing section, fictional social login,
dashboard preview, or decorative illustration. **Commit:**
`feat(web): add seller login pages`.

### 10. Wire existing OTP APIs in browser code

**Depends on:** 9. **Read:** §§3.4.1–3.4.3, 3.14–3.16; existing `api/auth.py`.

**Scope:** JavaScript calls only existing OTP request/verify endpoints; map
validation, expiry, rate-limit, and service failures into the UI. Keep the
access token in memory only as needed for authenticated API calls; never
persist it or touch the refresh cookie.

**Accept:** request/verify success, 400, 429, and unavailable-SMS states are
handled; refresh token is absent from page/script/storage. **Tests:** preserve
auth API tests and add only web-flow coverage feasible in the existing suite.
**Commit:** `feat(web): connect login pages to existing otp flow`.

### 11. Resolve OAuth web handoff securely — **security implementation gate**

**Depends on:** 9. **Read:** §3.4.1, §3.4.6, §3.15; existing `api/oauth.py` and
`api/auth.py`.

**Scope:** change only the existing OAuth callback's final app-session handoff
so successful OAuth login reaches `/dashboard` without an access token in a
URL/query string and without weakening refresh-cookie guarantees. Reuse
`find_or_create_client` and `issue_session`; do not add a second OAuth/state or
session system.

**Accept:** valid OAuth callback redirects to dashboard; invalid/missing/used
state behavior remains tested; raw app access token is never in redirect,
HTML, log, or static asset. **Stop:** if the existing auth contract cannot
support a secure handoff without a new, unspecified mechanism—present options
to the maintainer rather than designing one. **Commit:**
`fix(oauth): redirect completed seller login to dashboard`.

### 12. Add protected-route/session restoration and logout behavior

**Depends on:** 10–11. **Read:** §§3.4.3–3.4.5, 3.5, 3.15.

**Scope:** make protected HTML routes require the existing authentication
semantics; implement in-memory access-token use, one refresh/retry through
`POST /auth/refresh`, redirect to `/login` when it fails, and existing
`POST /auth/logout` followed by redirect. Do not make a cookie-authenticated
mutation endpoint or expose tokens server-side accidentally.

**Accept:** anonymous protected request is rejected/redirected consistently;
expired access token refreshes once; failed refresh logs out; logout clears and
invalidates the session. **Commit:** `feat(web): add protected session handling`.

### 13. Implement dashboard shell and safe overview

**Depends on:** 12. **Read:** §§3.5–3.6, 3.11, 3.12, 3.23.

**Scope:** add protected dashboard routes and shared sidebar; render seller
identity plus lightweight, tenant-scoped counts for products, registered posts,
and conversations, and only subscription/usage information actually available.
Use links/placeholders for later pages without faking data or building an
analytics system.

**Accept:** a seller sees only their own data; no unbounded queries; sidebar is
usable on mobile; unavailable subscription data is honestly represented.
**Review:** use compact summaries, sections, and actionable recent activity
rather than a wall of decorative KPI cards; table/card hierarchy passes visual
gate. **Commit:**
`feat(web): add seller dashboard shell`.

### F3. Authentication and shell review gate — **review gate**

**Depends on:** 9–13. **Accept:** login, OTP, OAuth redirect, refresh, logout,
and protected-page tests pass; manually inspect no storage/URL token leakage;
`pytest` passes. **Stop:** no domain page starts before approval. **Commit:**
`test(web): cover seller authentication and dashboard access`.

---

## Products

### 14. Inventory existing product behavior — **review/decision gate; no coding**

**Depends on:** F3. **Read:** §§3.7.1–3.7.6, 3.13–3.14 and current product,
price-lookup, schemas, migrations, and tests.

**Scope:** identify precisely which CRUD/import pieces already exist and their
normalization/cache effects. Choose the smallest extension point. Do not
duplicate `load_prices_to_db` or normalization.

**Accept:** a short mapping of existing reusable functions/endpoints and the
needed missing endpoints/tests. **Commit:** none.

### 15. Add tenant-scoped product read API

**Depends on:** 14. **Scope:** add only missing seller-scoped list/detail API
with server-side search, pagination, bounded results, and predictable errors.
Every select filters `Product.client_id == current_client_id`.

**Accept:** list/search/pagination work; another seller's ID returns 404; no
client ID is accepted. **Commit:** `feat(products): add seller catalog read api`.

### 16. Add tenant-scoped product mutations

**Depends on:** 15. **Scope:** add/create reuse only missing POST/PATCH/DELETE
handlers. Generate normalized name server-side using existing logic; preserve
tenant-aware uniqueness and return 409 for a duplicate in the same tenant.
Refresh/reuse the existing lookup-cache behavior so chatbot lookup remains
correct.

**Accept:** create/update/delete are owner-scoped; renamed products re-normalize;
cross-tenant mutation is a non-leaking 404; price lookup remains correct.
**Commit:** `feat(products): add seller catalog mutations`.

### 17. Expose existing spreadsheet import safely

**Depends on:** 16. **Read:** §3.7.6, §3.14–3.15.

**Scope:** add the dashboard/API import path using
`services.price_lookup.load_prices_to_db(db, client_id, df)` unchanged for its
transactional replace behavior. Validate type/content/size before parsing and
report validation errors. Do not parse/normalize in JavaScript.

**Accept:** valid import changes only the authenticated seller catalogue;
invalid and oversized files fail predictably; another seller is untouched.
**Commit:** `feat(products): add seller price spreadsheet import`.

### 18. Build and review products UI — **review gate**

**Depends on:** 15–17. **Scope:** product table, search, pagination, add/edit/
delete, import, and loading/empty/error states using the APIs only.

**Accept:** all stated operations work in RTL/mobile; destructive deletion has
a clear confirmation; UI never renders a client ID/normalized name control;
product, tenant-isolation, import, and existing chatbot tests pass. **Review:**
compact desktop table plus a deliberately designed mobile representation—not
a card grid generated for convenience. **Commit:**
`feat(web): add seller product management page`.

---

## Listings

### 19. Verify Divar listing capabilities — **external research/decision gate; no coding**

**Depends on:** F4. **Read:** §§3.8.1–3.8.5 and the referenced Divar media-upload
documentation; verify against official/current Divar documentation and a safe
authorized test if available.

**Scope:** document supported endpoints, fields, permissions, ownership model,
and limits for retrieval, details, status, update/delete/deactivate, URL, and
dashboard image upload. Explicitly mark unsupported operations. Do not guess.

**Accept:** developer approves a capability matrix with citations/test evidence.
**Stop:** without this approval, steps 20–22 do not begin. **Commit:**
`docs(plans): record verified divar listing capabilities`.

**As built (2026-08-29):** matrix approved in-session — only
`GET /v1/open-platform/finder/user-posts` (scope `USER_POSTS_GET`) is
supported, returning token/title/images/`is_phone_hidden`/
`supplier_chat_assistant_enabled`/category. No details, status, update,
delete/deactivate, or URL/seo-slug endpoint exists. Image upload (§3.8.5) was
not verified end-to-end and stays deferred. The matrix was recorded in the
CHANGELOG step 20/21 entries and `docs/post/get_user_posts.md`, not as a
separate plan document, so the `docs(plans)` commit above never happened.

### 20. Implement only supported listing data/service behavior

**Depends on:** 19. **Scope:** add a `services/divar_listings.py` service only
for verified operations. Add a new seller-scoped persistent model/migration
only if verified data requires persistence; never repurpose `posts`, whose role
is conversation resolution. Include indexes and reversible migration handling.

**Accept:** no raw Divar HTTP in route/template/JS; persisted metadata matches
the approved contract only; existing posts semantics remain intact. **Commit:**
`feat(listings): add verified divar listing service`.

**As built (2026-08-29), maintainer-approved deviation:** the "never repurpose
`posts`" instruction was superseded the same day — the listing metadata
columns (`title`, `category`, `chat_enabled`, `is_phone_hidden`,
`last_synced_at`, later `present_on_divar`) were folded into `posts` via the
squashed baseline migration instead of a new `listings` table; `posts`'
conversation-resolution role is unchanged. `POST /seller/posts` was retired:
`post_token` rows now enter `posts` only through
`services/divar_listings.sync_listings`, which requires a completed OAuth
login and reuses the `ON CONFLICT (post_token) DO NOTHING` ownership pattern.
`/oauth/start` gained the `USER_POSTS_GET` scope. See CHANGELOG 2026-08-29
(step 20 and the migration-squash entry).

### 21. Add availability and supported listing APIs

**Depends on:** 20. **Scope:** implement the owner-scoped listing read API and
the documented availability patch using `posts.is_available`; follow the
existing `register_posts` ownership pattern. Implement image upload only if
step 19 confirms the end-to-end dashboard flow.

**Accept:** seller can never read/toggle another seller's post token; unsupported
actions are absent; upload has validation/limits if present. **Commit:**
`feat(listings): add seller listing api`.

**As built (2026-08-30):** `register_posts` no longer exists (retired in step
20); the availability PATCH scopes its lookup as `post_token AND client_id`,
so missing and cross-tenant both return the same non-leaking 404 — the same
ownership guarantee the retired endpoint provided. A `present_on_divar`
column splits listing presence from `is_available`: sync writes only
`present_on_divar`, the PATCH writes only `is_available` (the seller's
chatbot on/off toggle), and conversation resolution requires both flags.
Three endpoints shipped: `GET /api/v1/seller/listings` (read-only, never
calls Divar — per-app rate limits forbid sync-on-read),
`POST /api/v1/seller/listings/sync` (the explicit refresh trigger the
read-only design requires), and the availability PATCH. Image upload was not
implemented — step 19 did not verify the end-to-end flow. See CHANGELOG
2026-08-30 (step 21).

### 22. Build listings UI and approve capabilities — **review gate**

**Depends on:** 21. **Scope:** list title/status/price only when supplied by the
verified source, last sync time, Divar link, availability toggle, and only
approved management controls.

**Accept:** no fake listing data/actions; state/error/loading states are clear;
tenant tests pass; visual design uses a scan-friendly marketplace-management
table/list. **Stop:** do
not silently broaden the verified capability matrix. **Commit:**
`feat(web): add seller listings page`.

**As built (2026-08-31, commit `eab1780`):** the page renders only verified
fields — title, Divar presence, Divar chat-assistant flag, phone-hidden,
last sync, the availability toggle, and a token-only Divar link
(`https://divar.ir/v/{post_token}`, because no seo-slug endpoint was
verified in step 19). Price, lifecycle status, edit, and delete are not
rendered. Data loads client-side through the step 21 APIs (step 12
convention). **The F5 review gate is not yet recorded** — complete the
universal visual/security gates and the Supervisor closeout record below
before opening step 23, which depends on F5.

---

## Conversations and settings

### 23. Map both conversation systems — **review/decision gate; no coding**

**Depends on:** F5. **Read:** §§3.9.1–3.9.2 and PHASE2 §2.9 as routed from the
plan, plus existing conversation models/services.

**Scope:** identify how chatbot `conversations/messages` and supplier-wide
`post_conversations/post_messages` are related, owned, and paginated. Decide
the smallest truthful unified or clearly separated presentation based solely on
existing data. Do not surface one system as “all conversations”.

**Accept:** developer approves the data mapping and API response shape.
**Stop:** if ownership/linkage is ambiguous. **Commit:** none.

### 24. Add tenant-scoped conversation APIs

**Depends on:** 23. **Scope:** add list/detail/message history endpoints for
both approved conversation sources with bounded pagination and owner-scoped
queries. Read-only only; no WebSocket/realtime system.

**Accept:** A cannot view B's list/detail/messages in either system; only
available unread/state metadata is returned; webhook behavior is unchanged.
**Commit:** `feat(conversations): add seller conversation read api`.

### 25. Build conversations and settings pages — **review gate**

**Depends on:** 24. **Read:** §§3.9, 3.12.

**Scope:** build readable list/detail/history UI plus safe settings display/edit
only for actually supported safe fields (such as phone and Divar account
status). Never show OAuth credentials, refresh tokens, OTP data, JWT data, or
internal IDs unless needed.

**Accept:** no sensitive values in HTML/API; mobile message history is usable;
both conversation systems are represented; the workspace prioritises list,
selected conversation, readable messages, timestamps, and state over analytics
decoration; tenant tests and `pytest` pass.
**Commit:** `feat(web): add conversations and seller settings pages`.

---

## Packages and subscription

### 26. Resolve packages/payment boundary — **business decision gate; no coding**

**Depends on:** F6. **Read:** §§3.10–3.11, especially §3.10.6.

**Scope:** obtain the maintainer's package catalogue/configuration source and
the decision required by §3.24 before beginning the package milestone. Record
whether checkout remains intentionally unavailable. Do not choose a gateway or
invent prices, limits, periods, callbacks, or success flows.

**Accept:** written decision gives exact plan data source and confirms the
payment boundary. **Stop:** if absent; subscription implementation is deferred,
while earlier completed slices remain deployable. **Commit:**
`docs(plans): record subscription implementation decision`.

**As decided (2026-09-02, revised same day — buyer quota is per
post-conversation, plus a per-conversation message cap):** Free Trial =
**7 days / 50 buyer conversations / 500 buyer-generated messages, one trial
per client, first limit reached ends it**. The quota counts
**buyer-generated usage only** — a seller's own messages are never
quota-limited, and the message quota is independent of the conversation
quota. A **buyer conversation** is scoped to a seller's post: the unit is
the existing seller-scoped `post_conversations` row, so the same buyer
contacting several of one seller's posts consumes **one unit per post
conversation** (intentional). Cross-post buyer identity is intentionally
irrelevant — no buyer-identity model, cross-post dedup, or
`COUNT(DISTINCT buyer)` is needed; that Divar's webhook payload carries no
buyer identity is a non-issue under these semantics, not a gap. One inbound
BUYER-side message = one message unit; bot replies and seller messages
never count. Independently of the three seller-level limits, each
`post_conversation` has its own **50 inbound BUYER-message cap (abuse
protection — not a package quota)**: once a conversation reaches 50 buyer
messages, further buyer messages in it are not processed by the chatbot,
open no new conversation unit, and consume no remaining global
buyer-message unit; each post conversation gets its own fresh cap, so one
buyer cannot exhaust the seller's 500-message allowance through a single
post. Both levels — seller-level quotas and the per-conversation cap —
must be enforced atomically (never read-check-write; see the CHANGELOG
race analysis). Checkout/payment stays intentionally unavailable and the
paid catalogue is deferred — no authoritative package source exists in the
repo. Both quotas derive from existing seller-scoped rows, with the
atomic/idempotent seams already in place (`post_conversations.
divar_conversation_id` and `post_messages.divar_message_id` globally unique
+ `ON CONFLICT DO NOTHING`); quota is defined over the POST system — the
BOT path persists no buyer messages today. Architecture impact map and
race-condition analysis: **CHANGELOG.md 2026-09-02** (steps 27–29 consume
it).

### 27. Define usage contract — **research/decision gate; no coding**

**Depends on:** 26. **Read:** §3.11.

**Scope:** document which existing records derive chatbot messages, active
listings, and products; billing period/reset/timezone/concurrency/idempotency
only if persistent counters are genuinely required. Prefer derived counts.

**Accept:** developer approves a usage contract; no high-volume event system is
proposed without need. **Stop:** persistent counter requirements unresolved.
**Commit:** `docs(plans): define initial subscription usage contract`.

**As decided (2026-09-03):** all five usage dimensions derive from existing
rows — buyer conversations from `post_conversations`, buyer messages from
`post_messages` (`sender_type = 'buyer'`; no SELLER value exists in the
enum), the per-conversation 50-message abuse cap from the same rows scoped
to one conversation, active listings from `posts.present_on_divar`
(`is_available`/`chat_enabled` are not listing status), products from
`products` — no counters, no usage-event table, no new infrastructure.
Every entitlement is a **half-open UTC interval `[period_start,
period_end)`** (trial end = trial start + 7 × 24 h, precise instant, no
local-calendar-day rule; UTC per the repository's `timezone=True`
convention) and usage is always the **window-scoped derived count** —
lifetime `COUNT`s are explicitly rejected for entitlement, and period
boundaries "reset" usage by definition of the window, with no reset
operation. A buyer message **counts toward usage only when its `post_messages` row is
successfully committed**: send failures roll the row back and quota-blocked
messages are never inserted, so both automatically consume nothing. Derived counts
are the source of truth for reporting; concurrent admission in step 28
needs transactional serialization (advisory-lock or conditional-statement
family — never read-check-write), while redelivery idempotency is already
guaranteed by the two existing unique constraints. Full contract with
query shapes, verification evidence, concurrency analysis, and deferred
items: **CHANGELOG.md 2026-09-03**.

### 28. Add plans/subscriptions model and read APIs

**Depends on:** 26–27. **Scope:** create only the models/fields in §3.10,
Alembic migration, central plan configuration, public plans API, and owner-
scoped current-subscription API. Use only stated statuses. Do not add checkout
or fake payment success.

**Accept:** inactive plans are not purchasable/represented as available where
applicable; expired status is correct; A cannot read B's subscription; migration
preserves existing data and indexes relationships. **Commit:**
`feat(subscriptions): add plans and seller subscription read model`.

**As decided (2026-09-04, maintainer architecture correction):** a dedicated
central service (`services/subscriptions.py`) owns all subscription logic —
`ensure_default_subscription` returns the seller's existing row (any status —
an expired trial is never re-issued; one trial per client) or creates
exactly one default Free Trial subscription, LAZY and idempotent: no
startup seeding and **no subscription/plan business logic in `main.py`**,
no eager creation at client signup, no bulk backfill of existing clients.
The Free Trial *Plan catalogue* row is created idempotently from the
central config (`config.py` FREE_TRIAL_* constants — the only source of
7 days / 50 buyer conversations / 500 buyer messages) on first need by the
same service; before any seller needs it the public `/api/v1/plans` list
is honestly empty (the pricing page already renders its "nothing to show"
state for that case). Plan (shared catalogue) and Subscription (one row
per client, `uq_subscriptions_client_id`) are fully separate; each seller
gets an independent Subscription row referencing the one Plan row.
`GET /api/v1/seller/subscription` routes through the service (lazy default
assignment on first read, persisted by the endpoint's commit; existing
rows returned untouched), `client_id` only ever from the JWT. Read-time
effective status: stored-ACTIVE + elapsed `expires_at` (half-open
[started_at, expires_at), UTC) → presented EXPIRED, never a GET-time
mutation; other stored statuses pass through. Schema in the squashed
baseline `0001` only (no new migration file, per project policy): `plans`
(§3.10.1 fields + `conversation_limit`/`duration_days`, which the step 26
trial semantics require; `uq_plans_name`) and `subscriptions` (§3.10.2
fields, §3.10.3 statuses only, plan FK without ON DELETE). No checkout,
no quota enforcement, no usage counters — Step 27's derived-usage contract
stands.

### 29. Build pricing/subscription displays — **review gate**

**Depends on:** 28. **Scope:** connect public pricing and protected subscription
page to the central source; show current plan, status, dates, derived usage,
available plans, and an honest upgrade CTA. If checkout is unimplemented, CTA
must state/request the approved non-payment next action rather than imply a
purchase succeeds.

**Accept:** UI matches API, no duplicated plan logic, no payment claim, and
the subscription view is a clear status/usage/form workflow rather than a
decorative financial dashboard; subscription/tenant tests plus `pytest` pass.
**Commit:**
`feat(web): add subscription status and package displays`.

**As decided (2026-09-05):** the public `/pricing` page renders whatever
`GET /api/v1/plans` returns at runtime (`static/js/pricing.js`, plain fetch —
public catalogue), keeping its honest "nothing to show" state for an empty
list; no plan name/price/limit/duration is ever hard-coded in templates or
JS. The protected `/dashboard/subscription` page follows the step 12
client-side convention (`static/js/subscription.js` via
`DivarSession.authFetch`): current plan, status (the four §3.10.3 values,
read-time EXPIRED included — never recomputed in JS), dates, usage, and
available plans from the same public plans API. Derived usage was added as
the minimal read-only extension of the existing
`GET /api/v1/seller/subscription` response (step 29 instruction §12):
`services/subscriptions.py::get_subscription_usage` computes the step 27
window-scoped COUNTs (buyer conversations from `post_conversations`, buyer
messages from `post_messages` `sender_type='buyer'`) over
`[started_at, expires_at)` — no counters, no enforcement, and `usage: null`
while a PENDING subscription has no window. The upgrade CTA is
informational only (contact support; checkout deliberately absent per step
26) — no checkout/payment endpoint, no fake success. The dashboard's stale
"not yet available" placeholder became a link to the new page.

---

## Hardening and release

### 30. Security and error-handling audit

**Depends on:** F7. **Read:** §§3.13–3.15, 3.22.

**Scope:** audit and fix only Phase 3 surfaces for predictable 400/401/403/404/
409/413/422/429/500 handling, CSRF for any cookie-authenticated mutation,
security headers, upload limits, validation, and safe logs. Do not add a broad
new security framework if existing platform features suffice.

**Accept:** cross-tenant 404 behavior verified; state-changing cookie route has
explicit CSRF defense; no sensitive logging; headers and limits are tested.
**Commit:** `fix(web): harden seller portal security boundaries`.

### 31. Performance, accessibility, and visual pass

**Depends on:** 30. **Read:** §§3.2.3, 3.14, 3.18, 3.23.

**Scope:** correct only observed Phase 3 issues: unbounded data loads, missing
labels/focus/error associations, poor contrast, mobile overflow, RTL defects,
and inconsistent shared UI. Preserve small/simple implementation.

**Accept:** all large lists paginate/filter server-side; keyboard path works;
desktop/tablet/mobile visual gate passes on every page; loading/empty/error
states are present. **Commit:** `fix(web): polish seller portal usability`.

### 32. Railway production verification and Phase 3 closeout — **release gate**

**Depends on:** 31. **Read:** §§3.19–3.25.

**Scope:** verify deployment remains one FastAPI/Railway service and Docker
includes templates/static. In the production environment, verify `/`, `/login`,
`/pricing`, `/dashboard`, and static assets; execute final test suite and the
Phase 3 definition-of-done checklist. Do not modify production schema manually.

**Accept:** every applicable checklist item is checked with evidence; deferred
items remain explicitly deferred (not claimed complete); all tests are green;
existing chatbot behavior is smoke-tested. **Stop:** Phase 3 is not complete
until failures are fixed in their owning step and re-reviewed. **Commit:**
`chore(web): verify phase three production readiness` (only if a code/config
change is actually required; otherwise no commit).

## Supervisor closeout record

For every approved gate, record: date, commit SHA, reviewer, focused/full test
results, manual URL/device widths checked, security findings, and deferred
decisions. This record prevents “the page looked fine” from being mistaken for
functional, tenant-safe completion.
