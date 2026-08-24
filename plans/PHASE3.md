# Phase 3 — Seller Web Platform

> **Agent rule:** Do not begin Phase 3 tasks until `PLAN.md`'s Active Phase reads
> `Phase 3`, and all required Phase 2 tasks/bugfixes are checked off in `PHASE2.md`.
>
> Phase 3 adds the first seller-facing web application to the existing FastAPI
> backend. The web application is intentionally implemented inside the existing
> FastAPI service using server-rendered Jinja2 HTML, static CSS, and vanilla
> JavaScript.
>
> **No React, Vue, Next.js, Vite, separate frontend service, or frontend build
> system is introduced in Phase 3.**
>
> The goal is to provide a production-oriented MVP seller portal without
> introducing unnecessary frontend infrastructure.

---

# 3.0 Phase 3 Scope and Architecture

## Goal

Turn the existing Divar chatbot backend into a seller-facing web platform where
authenticated sellers can:

- visit a public landing page
- log in using the existing OTP authentication system
- access a protected seller dashboard
- manage their products
- import/update product prices
- view their registered Divar listings
- view chatbot usage/conversation information
- view their current chatbot package
- browse available packages
- manage their subscription
- access basic account settings

The seller web application must use the existing authentication and
multi-tenant architecture.

## Explicit non-goals

The following are NOT part of the initial Phase 3 implementation unless a
later task explicitly adds them:

- React/Vue/Next.js
- separate frontend deployment
- separate frontend repository
- frontend Node.js runtime in production
- password-based authentication
- storing plaintext access/refresh tokens in browser localStorage
- exposing `client_id` as a trusted frontend parameter
- arbitrary seller access to another seller's data
- implementing unsupported Divar listing operations without confirming the
  Divar API capability
- production payment gateway integration before the subscription model is
  finalized
- replacing the existing chatbot architecture

---

# 3.1 Existing Architecture Constraints

Phase 3 MUST build on the existing Phase 2 architecture.

## Authentication

The existing authentication system is authoritative.

Seller authentication currently uses:

- OTP-to-phone login
- JWT access token
- HTTP-only refresh token cookie
- `get_current_client_id()` for authenticated API access

Do NOT introduce:

- username/password authentication
- `password_hash`
- a second JWT implementation
- a second session implementation
- frontend-only authentication

The existing `/auth` routes remain the source of truth.

The web layer may provide HTML pages for the existing authentication flow,
but authentication logic must remain in `api/auth.py` / existing auth services.

## Tenant isolation

Every seller-facing operation MUST resolve the seller identity from the
authenticated JWT.

Never trust:

- `client_id` from query parameters
- `client_id` from URL paths
- `client_id` from request bodies
- hidden HTML form fields containing `client_id`
- JavaScript-provided `client_id`

The server must derive:

    client_id = Depends(get_current_client_id)

and every database query must be scoped to that client.

This is a hard security requirement.

## Existing models

Phase 3 builds on:

    clients
    oauth_tokens
    otp_codes
    refresh_tokens
    posts
    products
    conversations
    messages

Do not duplicate these concepts with new parallel models.

---

# 3.2 Web Application Foundation

## 3.2.1 Static files

Add a static directory served by FastAPI.

Recommended structure:

    static/
        css/
            main.css
            auth.css
            dashboard.css
        js/
            main.js
            auth.js
            dashboard.js
            products.js
            listings.js
            conversations.js
            pricing.js
        img/

Use FastAPI/Starlette `StaticFiles`.

Static assets must not contain secrets or server-side credentials.

No API keys, JWT signing keys, Divar tokens, OAuth refresh tokens, or database
credentials may ever be embedded in JavaScript files.

## 3.2.2 Templates

Add a Jinja2 templates directory.

Recommended structure:

    templates/
        base.html

        public/
            home.html
            pricing.html

        auth/
            login.html
            otp.html

        dashboard/
            dashboard.html
            products.html
            listings.html
            conversations.html
            subscription.html
            settings.html

Use a shared `base.html` for:

- HTML document structure
- metadata
- CSS loading
- shared navigation hooks
- common JavaScript
- RTL direction

Do not duplicate the entire HTML document structure in every page.

## 3.2.3 RTL

The seller portal is Persian-first.

The base document MUST use:

    dir="rtl"
    lang="fa"

The UI must remain usable on:

- desktop
- tablet
- mobile

Do not introduce a frontend CSS framework unless explicitly approved.

Prefer maintainable project-owned CSS over pulling a large UI framework into
the application.

---
## 3.2.4 Design System and Visual Direction

Phase 3 is a seller-facing product, not a generic AI/SaaS dashboard.

The visual design MUST feel like a real, mature marketplace management
interface designed specifically for Divar sellers.

The implementation must prioritize:

- usability
- clarity
- information hierarchy
- trust
- Persian/RTL readability
- fast scanning
- practical seller workflows
- consistency across pages

The UI should feel **purpose-built**, not generated from a generic dashboard
template.

### Core Visual Direction

The overall visual language should be:

- Persian-first
- RTL-first
- practical
- information-dense but not crowded
- restrained
- professional
- marketplace-oriented
- familiar to Iranian users
- functional rather than decorative

The interface should communicate that this is a tool for managing real
products, listings, customers, conversations, and subscriptions.

Prefer the visual language of established marketplace/admin products over
modern startup landing-page aesthetics.

### Anti-AI-Slop Rules

The following patterns MUST NOT be used merely because they are common in
AI-generated dashboard designs.

Do NOT use:

- excessive rounded cards
- excessive `border-radius`
- cards nested inside cards
- gradient backgrounds
- decorative gradient text
- purple/blue "AI SaaS" visual palettes without a product-specific reason
- glassmorphism
- frosted-glass panels
- excessive drop shadows
- floating cards everywhere
- excessive pill-shaped UI elements
- decorative KPI cards for every metric
- oversized dashboard headings
- giant empty hero sections
- decorative blobs or abstract background shapes
- unnecessary illustrations
- decorative charts without useful information
- excessive use of icons
- icons used instead of clear Persian labels
- emoji as UI decoration
- excessive animations
- animated counters
- excessive hover effects
- unnecessary loading animations
- generic "AI dashboard" visual patterns
- excessive whitespace that reduces information density
- fake complexity intended to make the product look more sophisticated
- visual elements that do not serve a user task

Do not attempt to make the application look "premium", "futuristic", or
"AI-powered" through decoration.

A simple, well-structured interface is preferred over a visually impressive
but impractical one.

### Cards

Cards may be used when they create a meaningful visual grouping.

Do not turn every piece of information into a card.

Prefer:

- simple sections
- borders/dividers
- table rows
- grouped content
- clear headings
- restrained containers

A card must have a clear semantic purpose.

Bad:

    card
      card
        card
          metric

Preferred:

    section
      heading
      content

Use stronger visual treatment only for genuinely important information such
as the current subscription or a primary action.

### Border Radius

Use a restrained and consistent radius system.

Do not make every element heavily rounded.

In particular:

- tables should remain visually rectangular
- inputs should not look like capsules
- primary actions should not automatically become pill buttons
- navigation items should not all be large rounded pills

Rounded corners should support hierarchy, not become the visual identity of
the entire application.

### Shadows

Shadows should be subtle and used sparingly.

Prefer borders and spacing to communicate hierarchy.

Do not give every card, button, input, and navigation item its own shadow.

### Color

Use a small, coherent color system.

Color should communicate meaning:

- primary actions
- success
- warning
- error
- informational states
- disabled states

Do not use multiple unrelated accent colors simply to make the interface
look visually rich.

The interface should remain usable if decorative color is removed.

Status colors must not be the only way information is communicated.

### Typography

Persian typography is a first-class design requirement.

The selected font stack must provide good Persian glyphs, readable numbers,
and clear distinction between:

- headings
- body text
- labels
- metadata
- prices
- timestamps
- status information

Do not use typography copied from a generic English SaaS dashboard without
checking Persian rendering.

Avoid excessive font-weight variation.

Use typography and spacing to establish hierarchy before adding decorative
elements.

Prices, timestamps, counts, and identifiers should remain easy to scan.

### Spacing

Use a consistent spacing scale throughout the application.

Do not randomly assign margins and padding per component.

The layout should have enough whitespace to remain readable, but seller
workflows should remain information-dense.

In particular:

- product tables should not have excessive vertical padding
- conversation lists should allow many conversations to be scanned quickly
- dashboard summaries should not consume most of the viewport
- mobile layouts may reduce density where necessary

### Icons

Icons are optional and functional.

Use an icon only when it improves recognition or interaction.

Do not add an icon to every navigation item, button, heading, and statistic.

Every important action must remain understandable without relying on an icon.

Do not introduce a large icon library solely for visual decoration.

If icons are needed, use a small consistent set rather than mixing multiple
icon styles.

---

## Page-Specific Design Rules

### Public Home Page

The home page should communicate the product quickly.

Prioritize:

1. what the product does
2. seller benefits
3. how automation works
4. important capabilities
5. clear login/get-started action
6. pricing entry point

Do not create a generic startup landing page with:

- enormous hero typography
- multiple gradient sections
- decorative blobs
- fake customer logos
- invented testimonials
- invented statistics
- meaningless feature cards
- excessive scrolling

Any claim, statistic, testimonial, customer count, or business metric must
come from a real project requirement or verified source.

The page should look like the public website of a real seller product, not an
AI-generated SaaS template.

### Pricing Page

Pricing must optimize for comparison and decision-making.

Prefer:

- clear plan names
- clear prices
- billing period
- important limits
- concise feature comparison
- obvious current/available state
- one clear primary action per plan

Avoid:

- excessively decorative pricing cards
- giant "MOST POPULAR" ribbons
- gradients used only to highlight a plan
- unnecessarily complex feature matrices
- fake urgency
- fake discounts
- invented pricing claims

Plans must come from the configured/domain data rather than being visually
invented inside the template.

### Login Page

The login page should be extremely simple.

Primary focus:

- phone number
- Send OTP
- Login with Divar

Do not add:

- unnecessary marketing sections
- decorative dashboards
- complex illustrations
- social login buttons that do not exist
- unnecessary account creation flows

Authentication UI should feel trustworthy and direct.

### OTP Page

The OTP page should minimize distraction.

Focus on:

- phone context
- OTP input
- verification action
- retry
- expiration/error state

The page should clearly communicate what the seller needs to do next.

Do not turn the OTP screen into a marketing page.

### Dashboard

The dashboard is a management workspace, not a showcase page.

Prioritize:

- current subscription
- important counts
- recent activity
- actionable shortcuts
- seller context

Do not create a dashboard where every metric is represented by a large
decorative card.

Use a mixture of compact summaries, lists, and sections.

The seller should be able to understand the state of their business quickly
without scrolling through decorative content.

### Products

Products are a data-management workflow.

The product page should prioritize the table/list over decorative cards.

Important information includes:

- product name
- price
- last update
- actions

Search, pagination, import, create, edit, and delete actions must be easy to
find.

Prefer a compact desktop table and a deliberately designed mobile
representation.

Do not convert every product into a large card on desktop merely because cards
are easier to generate.

### Listings

Listings should visually resemble a marketplace/listing management interface.

Important information includes:

- listing identity/title
- availability/status
- price when available
- synchronization information
- supported actions
- Divar link

Do not display unsupported actions merely to make the UI appear complete.

Do not invent listing metadata for visual completeness.

### Conversations

The conversation interface should prioritize scanning and reading.

Prefer a layout conceptually similar to a real messaging/support workspace:

- conversation list
- selected conversation
- message history
- timestamps
- current state/status

Do not build a generic analytics dashboard around conversations.

Do not introduce a WebSocket-style UI merely for visual effect; Phase 3
explicitly allows normal request/response or polling.

### Subscription

Subscription information should be easy to understand.

Prioritize:

- current plan
- status
- expiration
- usage
- available plans
- upgrade action

Do not use decorative financial-dashboard patterns.

Payment-related UI must not imply that a payment flow exists when it has not
been implemented.

### Settings

Settings should be simple and form-oriented.

Prefer:

- clear sections
- labels
- values
- explicit edit/save actions

Do not turn settings into a visually elaborate profile page.

Sensitive credentials and internal identifiers must never be surfaced merely
to make the page appear more complete.

---

## Responsive Design

Responsive behavior must be designed intentionally rather than achieved by
simply stacking desktop elements vertically.

### Desktop

Desktop layouts should take advantage of available horizontal space.

Examples:

- persistent sidebar where appropriate
- data tables
- conversation split-view
- multi-column dashboard sections

### Tablet

Reduce density while preserving important navigation and actions.

### Mobile

Mobile layouts should prioritize the primary workflow.

Examples:

- navigation may collapse
- tables may transform into compact rows or structured cards where necessary
- secondary information may move behind a detail view
- actions must remain reachable
- text must not become unnecessarily tiny

Do not simply shrink desktop UI until it becomes difficult to use.

---

## Component Consistency

Components must use a small, consistent visual vocabulary.

At minimum, establish consistent styles for:

- page headers
- section headers
- buttons
- inputs
- selects
- text areas
- tables
- badges/status indicators
- alerts/errors
- empty states
- loading states
- pagination
- navigation
- modal/dialog patterns if required

Do not create a visually different component style for every page.

Do not create multiple button styles that have no semantic distinction.

Do not create page-specific spacing systems.

---

## Empty, Loading, and Error States

Every data-driven page should have deliberate states for:

- loading
- empty data
- validation error
- API error
- unauthorized session
- successful mutation where appropriate

These states must be useful and concise.

Do not use generic:

    "Oops! Something went wrong."

messages when a more useful Persian explanation can be provided.

Do not fill empty states with decorative illustrations unless they provide
real value.

---

## Design System Before Page Expansion

Before implementing multiple Phase 3 pages, establish a small shared visual
system in the global CSS.

The system should define, at minimum:

- typography
- colors
- spacing
- borders
- radius
- shadows
- buttons
- form controls
- tables
- status indicators
- layout containers
- navigation
- responsive breakpoints

The system should remain small.

Do NOT build a general-purpose frontend component framework inside vanilla
JavaScript/CSS.

The purpose of the design system is consistency, not abstraction for its own
sake.

---

## Design Review Gate

Before considering a frontend milestone complete, review the rendered UI
against these questions:

1. Does this look like a real marketplace seller product rather than a
   generic AI-generated SaaS dashboard?

2. Is every major visual element serving a real user task?

3. Are there unnecessary cards, gradients, shadows, pills, icons, or
   animations?

4. Is the interface information-dense enough for a seller management
   workflow?

5. Is Persian typography readable?

6. Is RTL behavior correct?

7. Does the visual hierarchy work without decorative effects?

8. Are tables, forms, conversations, and settings optimized for their actual
   tasks?

9. Does mobile behavior remain intentional and usable?

10. Did the implementation introduce any visual pattern simply because it is
    common in AI-generated dashboard designs?

If the answer to the last question is yes, simplify it.

### Design Principle

> **Prefer product-specific clarity over generic visual impressiveness.**

When choosing between a more decorative design and a simpler design that makes
the seller workflow clearer, always choose the simpler design.

# 3.3 Public Website

## 3.3.1 Home page

Route:

    GET /

Render:

    templates/public/home.html

The page should communicate:

- what the Divar chatbot does
- how sellers benefit
- automated customer communication
- price lookup
- product catalog management
- chatbot automation
- CTA to login/register
- CTA to pricing

The page must not expose seller-specific information.

## 3.3.2 Pricing page

Route:

    GET /pricing

Render:

    templates/public/pricing.html

The page displays available chatbot packages.

Initially this may use database-backed plans or a clearly isolated
configuration source.

Do not hardcode package logic throughout templates.

The pricing page must be public.

---

# 3.4 Seller Authentication Web Flow

The backend authentication API already exists and must remain authoritative.

The web layer provides the user interface around it.

## 3.4.1 Login page

Route:

    GET /login

Render:

    templates/auth/login.html

UI:

    Phone number
    [Send OTP]
    [Login with Divar]

JavaScript calls the existing OTP request endpoint.

Do not create a new authentication endpoint solely for the HTML UI.

### "Login with Divar" option (maintainer decision, 2026-08-23)

Besides the OTP form, the login page MUST also offer a "Login with Divar"
button so sellers can log in through the EXISTING seller OAuth flow instead
of OTP:

    Button links to:  GET /oauth/start
    Completion via:   GET /oauth/callback  (see §3.4.6)

Rules:

- The button is a plain link/redirect to `/oauth/start`. Do NOT create a new
  OAuth implementation, new endpoints, or a second state store.
- Both login paths converge on the same session mechanics already defined in
  `api/auth.py` (`find_or_create_client` merge-by-phone + `issue_session`);
  the web layer adds UI only.
- After the callback completes, the seller must land on the authenticated
  web destination per §3.4.6 — the access token must never appear in the
  redirect URL/query string.
- Milestone 3.3 includes this button; it is not a separate phase or task.

## 3.4.2 OTP page

Route:

    GET /login/otp

Render:

    templates/auth/otp.html

UI:

    OTP code
    [Verify]

The page must support:

- validation errors
- expired OTP
- rate-limit errors
- retry flow

## 3.4.3 Access token handling

The existing auth implementation returns an access token and sets the refresh
token as an HTTP-only secure cookie.

The Phase 3 frontend MUST NOT persist the refresh token in:

- localStorage
- sessionStorage
- JavaScript variables
- HTML
- query parameters

The refresh token remains cookie-only.

If the access token is stored client-side temporarily for API calls, it must
never be persisted in localStorage.

Prefer an in-memory JavaScript variable.

## 3.4.4 Session restoration

When the seller opens a protected page:

1. attempt to use the current access token
2. if expired, call `/auth/refresh`
3. retry the API request
4. if refresh fails, redirect to `/login`

Do not create a second refresh-token mechanism.

## 3.4.5 Logout

Logout must call the existing:

    POST /auth/logout

Then redirect to:

    /login

The server must invalidate the refresh token and clear the cookie.

## 3.4.6 OAuth callback redirect (closes an existing TODO)

`api/oauth.py`'s `/oauth/callback` currently returns the same JSON
`{"access_token", "expires_in"}` contract as OTP login, with an inline
comment marking it temporary pending a real seller-facing destination.

Once `/dashboard` exists, `oauth_callback` must be changed to issue a
`RedirectResponse` to the dashboard instead of returning raw JSON.

The access token must NOT be passed in the redirect URL/query string in
plaintext. Prefer one of:

- setting a short-lived, HttpOnly, Secure session cookie the dashboard reads
  server-side on first load, or
- redirecting to an intermediate page that immediately exchanges a one-time
  code for the access token via an existing authenticated endpoint

Do not weaken the existing refresh-token-in-cookie-only guarantee to make
this work.

---

# 3.5 Seller Web Routes

Add a dedicated web router.

Recommended:

    api/web.py

or:

    web/routes.py

The exact location may follow existing project conventions.

The web router is responsible for rendering HTML.

Recommended routes:

    GET /
    GET /pricing
    GET /login
    GET /login/otp

    GET /dashboard
    GET /dashboard/products
    GET /dashboard/listings
    GET /dashboard/conversations
    GET /dashboard/subscription
    GET /dashboard/settings

HTML routes must not duplicate business logic from API/services.

They should render templates and let JavaScript consume the existing/new
JSON APIs.

Protected HTML routes must require authentication where appropriate.

---

# 3.6 Seller Dashboard

Route:

    GET /dashboard

Render:

    templates/dashboard/dashboard.html

The dashboard should show:

- seller identity
- current package
- package expiration
- product count
- registered listing count
- conversation count
- chatbot usage
- recent activity
- shortcuts to products/listings/conversations

Example conceptual layout:

    Seller Dashboard

    ┌─────────────────────────────┐
    │ Current Plan                │
    │ Business                    │
    │ 23 days remaining           │
    └─────────────────────────────┘

    Products       Listings       Conversations
    128            17             1,284

The first implementation should favor correctness over complex analytics.

Do not introduce an analytics warehouse or event-streaming system in Phase 3.

---

# 3.7 Products Management

The existing `products` model is the authoritative seller catalog.

Current structure:

    products:
        id
        client_id
        item_name
        normalized_name
        price
        created_at
        updated_at

The uniqueness constraint is:

    UNIQUE(client_id, normalized_name)

This tenant-aware uniqueness MUST be preserved.

## 3.7.1 Product API

Implement seller-scoped CRUD endpoints if not already available.

Recommended:

    GET    /api/v1/seller/products
    POST   /api/v1/seller/products
    GET    /api/v1/seller/products/{product_id}
    PATCH  /api/v1/seller/products/{product_id}
    DELETE /api/v1/seller/products/{product_id}

All endpoints require:

    Depends(get_current_client_id)

Every query must scope by:

    Product.client_id == current_client_id

Never retrieve a product by `id` alone.

Bad:

    SELECT * FROM products WHERE id = :product_id

Correct:

    SELECT * FROM products
    WHERE id = :product_id
      AND client_id = :current_client_id

## 3.7.2 Product list UI

Route:

    GET /dashboard/products

Features:

- product table
- search
- pagination
- add product
- edit product
- delete product
- price display
- last updated timestamp

Search must remain tenant-scoped.

## 3.7.3 Product creation

Fields:

    item_name
    price

`normalized_name` must be generated server-side using the existing
normalization logic.

Never trust a client-provided `normalized_name`.

## 3.7.4 Product update

The seller can update:

- item name
- price

If `item_name` changes:

1. normalize the new name
2. check the tenant-scoped uniqueness constraint
3. update both `item_name` and `normalized_name`

## 3.7.5 Product deletion

Deletion must be tenant-scoped.

A seller must never be able to delete another seller's product by guessing
its ID.

## 3.7.6 Excel import

Expose the existing product/price import functionality through the dashboard.
  Reuse `services.price_lookup.load_prices_to_db(db, client_id, df)` — do not
  reimplement the transactional replace logic.
Route:

    POST /api/v1/seller/products/import

The import must:

- authenticate the seller
- validate the uploaded file
- parse the spreadsheet
- normalize product names using existing logic
- upsert only into the authenticated seller's catalog
- report validation errors
- never modify another seller's products

Do not reimplement price normalization separately in the frontend.

---

# 3.8 Divar Listings

## Important architecture constraint

The current `posts` table exists primarily for mapping a Divar `post_token`
to a seller/client for chatbot conversation resolution.

Current conceptual structure:

    posts:
        post_token
        client_id
        created_at

This is NOT sufficient by itself to implement a complete seller listing
management UI.

Do not pretend that `posts` already contains:

    title
    description
    price
    category
    status
    URL

unless those fields are actually added and populated from a confirmed Divar
API source.

## 3.8.1 Listing synchronization

Before implementing listing management, verify the exact Divar API capabilities
for:

- retrieving seller listings
- retrieving listing details
- listing status
- updating listings
- deleting/deactivating listings
- opening listing URLs

Do not invent Divar endpoints.

If Divar provides a supported listing API, create a dedicated service layer:

    services/divar_listings.py

The web/API layer must not contain raw Divar HTTP calls.

## 3.8.2 Listing model

Only add additional DB fields/models after the Divar API contract is verified.

If persistent listing metadata is required, design it as a separate
seller-scoped model rather than corrupting the existing `posts` resolution
model.

Possible future model:

    listings:
        id
        client_id
        post_token
        divar_post_id
        title
        status
        price
        url
        created_at
        updated_at

This is a design direction, not an instruction to implement speculative
fields.

## 3.8.3 Listing UI

Route:

    GET /dashboard/listings

Display:

- title
- status
- price if available
- last synchronization time
- link to Divar
- supported management actions

Unsupported actions must not be displayed as if they work.

## 3.8.4 Listing availability

The `posts.is_available` field (added in Phase 2) is the source of truth for
whether a listing should be treated as available by the chatbot.

Recommended:

    PATCH /api/v1/seller/listings/{post_token}/availability

Body:

    { "is_available": true | false }

Must be tenant-scoped: a seller may only toggle availability on a `post_token`
that resolves to their own `client_id`. Follow the exact ownership pattern
already used in `api/seller.py`'s `register_posts`.

## 3.8.5 Listing images

Before implementing, verify Divar's image upload API contract
(`docs/post/get_media_upload_url_v2.md`) end-to-end from the dashboard —
not from inside chatbot conversations. Uploading an image on behalf of a
seller through the chatbot conversation itself is explicitly out of scope;
this is a dashboard-only feature.

Recommended:

    POST /api/v1/seller/listings/{post_token}/images

Must reuse Divar's existing upload-URL flow, not invent a new one.

---

# 3.9 Conversations

Phase 2 already stores:

    conversations
    messages

The seller dashboard should expose read-only conversation information first.

## 3.9.1 Conversation API

  Both conversation systems must be represented: the chatbot conversations
  (`conversations`/`messages`) and the supplier-wide post conversations
  (`post_conversations`/`post_messages`, per PHASE2.md §2.9). Do not surface
  only one and treat it as complete.
  
Recommended:

    GET /api/v1/seller/conversations
    GET /api/v1/seller/conversations/{conversation_id}
    GET /api/v1/seller/conversations/{conversation_id}/messages

Every query MUST enforce seller ownership.

The server must derive:

    current_client_id

from the authenticated session.

Never accept a client ID from the browser.

## 3.9.2 Conversation UI

Route:

    GET /dashboard/conversations

Display:

- conversation list
- last message
- timestamp
- current state
- unread indicator if supported
- conversation detail
- message history

The first implementation does not need a real-time WebSocket system.

Polling or normal request/response behavior is acceptable for Phase 3.

---

# 3.10 Subscription and Packages

Phase 3 introduces the domain model required for seller packages.

## 3.10.1 Plans

Create:

    plans

Suggested fields:

    id
    name
    description
    price
    billing_period
    message_limit
    listing_limit
    product_limit
    features
    is_active
    created_at
    updated_at

Exact limits and pricing must be configurable and must not be duplicated
throughout application code.

## 3.10.2 Subscriptions

Create:

    subscriptions

Suggested fields:

    id
    client_id
    plan_id
    status
    started_at
    expires_at
    created_at
    updated_at

Tenant relationship:

    subscriptions.client_id -> clients.id

A seller can only access their own subscription.

## 3.10.3 Subscription status

Recommended statuses:

    active
    expired
    cancelled
    pending

Do not create unnecessary status values without a business requirement.

## 3.10.4 Subscription API

Recommended:

    GET /api/v1/plans
    GET /api/v1/seller/subscription

Later, when payment is implemented:

    POST /api/v1/seller/subscription/checkout
    POST /api/v1/payments/callback

Do not implement fake payment success logic.

## 3.10.5 Package UI

Route:

    GET /pricing

Authenticated sellers may select a package.

Dashboard route:

    GET /dashboard/subscription

Display:

- current plan
- status
- start date
- expiration date
- usage
- available plans
- upgrade CTA

## 3.10.6 Payment gateway — explicitly deferred, not to be inferred

No payment gateway (Zarinpal, IDPay, Shaparak-based providers, etc.) has been
selected. This is a business decision outside Phase 3's technical scope.

Do NOT:
- guess a gateway and wire up its SDK
- implement a "generic" gateway abstraction speculatively
- hardcode a specific provider's callback URL shape

`POST /api/v1/seller/subscription/checkout` and `POST /api/v1/payments/callback`
remain stubs (or unimplemented) until this decision is made explicitly by the
maintainer.

---

# 3.11 Usage Tracking

Package limits require measurable usage.

Phase 3 should define the usage contract before enforcing hard limits.

Initial usage metrics may include:

    chatbot_messages
    active_listings
    products

Do not introduce a high-volume event architecture just for counters.

Where possible, derive current usage from existing database records.

If persistent monthly usage counters are required, create a dedicated model
only after defining:

- billing period
- reset behavior
- concurrency requirements
- idempotency
- timezone rules

---

# 3.12 Seller Settings

Route:

    GET /dashboard/settings

Display/edit only safe seller information.

Possible fields:

    phone_number
    Divar account status

Do not expose:

- JWT secrets
- refresh tokens
- Divar OAuth access tokens
- Divar OAuth refresh tokens
- OTP hashes
- internal database identifiers unless required

The `oauth_tokens` table contains credentials that must never appear in an
API response or HTML page.

---

# 3.13 API Design Rules

All seller JSON APIs should use:

    /api/v1/seller/...

except existing routes whose public contract is already established.

Example:

    /api/v1/seller/products
    /api/v1/seller/listings
    /api/v1/seller/conversations
    /api/v1/seller/subscription

Authentication:

    Authorization: Bearer <access_token>

Identity:

    client_id = get_current_client_id()

Never:

    /seller/{client_id}/products

Never trust:

    {
        "client_id": 123
    }

in a seller request body.

---

# 3.14 Error Handling

JSON APIs must return predictable HTTP errors.

Minimum expected cases:

    400 invalid input
    401 missing/invalid authentication
    403 authenticated but forbidden
    404 resource not found for current seller
    409 tenant-scoped uniqueness conflict
    413 upload too large
    422 validation error
    429 rate limit
    500 unexpected server error

Do not reveal whether another seller owns a resource.

For example, requesting another seller's product by ID should normally behave
as:

    404 Not Found

rather than:

    403 You do not own product 123

This avoids leaking cross-tenant resource existence.

---

# 3.15 Security Requirements

## Mandatory

- JWT authentication for seller APIs
- HTTP-only refresh token cookie
- Secure refresh cookie
- SameSite=Lax unless the deployment architecture requires otherwise
- no tokens in URLs
- no refresh token in JavaScript
- no secrets in static files
- no `client_id` trust from browser input
- tenant-scoped DB queries
- server-side input validation
- upload validation
- CSRF protection for cookie-authenticated state-changing web endpoints
- secure headers where appropriate
- production HTTPS

## CSRF

Because refresh authentication uses cookies, state-changing browser requests
must be protected against CSRF.

If seller mutations are performed through:

    Authorization: Bearer ...

and the access token is not automatically attached by the browser, CSRF risk
is reduced for those API calls.

However, any state-changing endpoint authenticated through cookies must have
an explicit CSRF defense.

Do not disable CSRF protection simply to make the frontend work.

---

# 3.16 Frontend JavaScript Rules

Vanilla JavaScript only.

Do not introduce:

- React
- Vue
- Angular
- jQuery unless explicitly justified
- Redux
- Zustand
- frontend router packages
- npm build pipeline

Use browser-native APIs:

    fetch()
    FormData
    URLSearchParams
    DOM APIs
    addEventListener()

JavaScript should be organized by feature.

Example:

    static/js/auth.js
    static/js/products.js
    static/js/listings.js

Do not create one 3000-line `app.js`.

---

# 3.17 Backend Separation

HTML rendering and API business logic must remain separate.

Recommended conceptual separation:

    api/
        auth.py
        seller.py
        webhook.py
        oauth.py
        admin.py
        web.py

    services/
        chatbot.py
        chatbot_engine.py
        divar.py
        divar_listings.py
        price_lookup.py
        ...

The HTML router must not contain:

- SQL queries for business operations
- Divar API calls
- price matching logic
- subscription calculation logic

Business logic belongs in services.

---

# 3.18 Templates and Components

Use Jinja2 includes/macros where useful.

Recommended:

    templates/
        base.html

        partials/
            navbar.html
            sidebar.html
            flash.html
            pagination.html
            product_table.html
            loading.html

        public/
            home.html
            pricing.html

        auth/
            login.html
            otp.html

        dashboard/
            dashboard.html
            products.html
            listings.html
            conversations.html
            subscription.html
            settings.html

Avoid duplicating:

- sidebar
- navigation
- authentication UI
- common buttons
- pagination markup

---

# 3.19 Testing

Phase 3 must preserve the existing test suite.

Before each milestone:

    pytest

must remain green.

## Backend tests

Add tests for:

### Authentication

- login page
- OTP request flow
- OTP verification flow
- refresh
- logout
- expired access token
- invalid access token

### Tenant isolation

For two clients A and B:

- A cannot read B's products
- A cannot modify B's products
- A cannot delete B's products
- A cannot read B's conversations
- A cannot read B's subscription
- A cannot access B's listings

### Products

- create
- read
- update
- delete
- duplicate normalized name
- normalization
- pagination
- search
- Excel import
- invalid spreadsheet
- oversized spreadsheet

### Subscriptions

- seller can read own subscription
- seller cannot read another seller's subscription
- inactive plan cannot be purchased
- expired subscription is represented correctly

### Web routes

- public pages return 200
- protected pages reject unauthenticated access
- authenticated seller can access own dashboard
- login redirects correctly

---

# 3.20 Database Migration Rules

Any schema changes must use Alembic.

Never manually modify production PostgreSQL schema.

Every migration must:

- be reversible where practical
- preserve existing Phase 2 data
- preserve tenant relationships
- include appropriate indexes
- avoid destructive changes without explicit migration planning

Do not alter the existing `posts` semantics merely to support the dashboard.

If full listing metadata is required, introduce a separate model after the
Divar API contract is confirmed.

---

# 3.21 Deployment

Phase 3 must deploy as part of the existing Railway service.

No separate frontend service is required.

The production process remains conceptually:

    Railway
       |
       +-- FastAPI
       |     |
       |     +-- HTML/Jinja2
       |     +-- Static CSS/JS
       |     +-- REST API
       |
       +-- PostgreSQL

The Docker image/process must include:

    templates/
    static/

The deployment must verify that:

    GET /
    GET /login
    GET /pricing
    GET /dashboard

work correctly in production.

Static assets must also be reachable.

---

# 3.22 Logging

Do not log:

- OTP codes
- JWTs
- refresh tokens
- Divar OAuth access tokens
- Divar OAuth refresh tokens
- authorization headers

Useful web logs may include:

    route
    status_code
    response_time
    client_id

provided that sensitive information is excluded.

Seller-specific logs should remain compatible with the existing logging
configuration.

---

# 3.23 Performance

Phase 3 is not expected to require a SPA or frontend build system for
performance reasons.

Use:

- pagination
- indexed queries
- server-side filtering where appropriate
- bounded result sets
- lazy loading for expensive dashboard data

Do not load every:

- product
- conversation
- message
- listing

into one HTML response.

Dashboard cards should use lightweight queries.

---

# 3.24 Phase 3 Milestones

## Recommended execution order (not strictly sequential per the list below)

Given single-developer bandwidth, prioritize in this order:

1. **3.1 Web Foundation** + **3.3 Authentication UI** + **3.4 Dashboard shell**
   (no listings/subscriptions yet) — these unblock everything else and build
   on infrastructure that already exists (JWT, OTP).
2. **3.5 Product Management** — APIs mostly exist already
   (`services/price_lookup.py`); this milestone is primarily UI + thin CRUD
   wrappers.
3. **3.6 Divar Listings** (including 3.8.4/3.8.5 above) — requires the Divar
   API capability verification called out in 3.8.1 before any code is written.
4. **3.8 Packages and Subscription** — requires the payment-gateway decision
   (3.10.6) and is lowest priority for an MVP seller experience.

This ordering is a recommendation, not a hard gate — but 3.8 (Packages) should
not begin before the gateway decision exists, per 3.10.6.

## 3.1 Web Foundation

- [ ] Add Jinja2 template support
- [ ] Add StaticFiles
- [ ] Create base template
- [ ] Create global CSS
- [ ] Create global JS
- [ ] Add web router
- [ ] Verify static assets in production
- [ ] Add RTL support
- [ ] Add responsive base layout

Acceptance:

- `/` renders HTML
- CSS loads
- JavaScript loads
- no frontend build step exists
- existing backend tests remain green

---

## 3.2 Public Website

- [ ] Home page
- [ ] Pricing page
- [ ] Navigation
- [ ] Login CTA
- [ ] Responsive layout

Acceptance:

- public pages require no authentication
- no seller data is exposed

---

## 3.3 Authentication UI

- [ ] Login page
- [ ] Login with Divar button on login page (§3.4.1)
- [ ] OTP page
- [ ] OTP request integration
- [ ] OTP verification integration
- [ ] refresh handling
- [ ] logout
- [ ] protected-page handling

Acceptance:

- seller can login using existing OTP flow
- refresh works
- logout invalidates the session
- refresh token is never exposed to JavaScript

---

## 3.4 Seller Dashboard

- [ ] Dashboard layout
- [ ] Sidebar
- [ ] Overview
- [ ] Seller information
- [ ] Product count
- [ ] Listing count
- [ ] Conversation count
- [ ] Subscription status

Acceptance:

- only authenticated seller data is displayed
- all queries are tenant-scoped

---

## 3.5 Product Management

- [ ] Product list API
- [ ] Product CRUD API
- [ ] Product list UI
- [ ] Search
- [ ] Pagination
- [ ] Create product
- [ ] Edit product
- [ ] Delete product
- [ ] Excel import UI/API
- [ ] Tenant-isolation tests

Acceptance:

- seller can fully manage own products
- seller cannot access another seller's products
- existing chatbot price lookup continues to work

---

## 3.6 Divar Listings

- [ ] Verify Divar listing API capabilities
- [ ] Implement listing service only for supported APIs
- [ ] Define persistent listing model if required
- [ ] Listing API
- [ ] Listing UI
- [ ] Listing synchronization
- [ ] Supported management operations

Acceptance:

- seller can see their own listings
- listing information comes from a verified Divar source
- no unsupported fake operations are exposed
- tenant isolation is tested

---

## 3.7 Conversations

- [ ] Conversation list API
- [ ] Conversation detail API
- [ ] Message history API
- [ ] Conversation UI
- [ ] Message UI
- [ ] Tenant isolation tests

Acceptance:

- seller can only see their own conversations
- existing chatbot webhook behavior is unchanged

---

## 3.8 Packages and Subscription

- [ ] Plan model
- [ ] Subscription model
- [ ] Alembic migration
- [ ] Public pricing API/page
- [ ] Current subscription API
- [ ] Subscription dashboard
- [ ] Usage display
- [ ] Upgrade flow design

Acceptance:

- plans are centrally configured
- seller can see their current plan
- seller cannot access another seller's subscription
- no fake payment success is implemented

---

## 3.9 Production Hardening

- [ ] CSRF protection
- [ ] security headers
- [ ] upload limits
- [ ] input validation
- [ ] error handling
- [ ] logging review
- [ ] authentication review
- [ ] tenant-isolation audit
- [ ] mobile UI review
- [ ] Railway production verification

Acceptance:

    pytest

is green and all Phase 3 acceptance criteria pass in production.

---

# 3.25 Definition of Done

Phase 3 is complete when:

- [ ] Seller can visit the public website
- [ ] Seller can login using OTP
- [ ] Seller can logout
- [ ] Seller can recover a session after access-token expiry
- [ ] Seller can access a protected dashboard
- [ ] Seller can manage their own products
- [ ] Seller can import product prices
- [ ] Seller can view their Divar listings where supported by the API
- [ ] Seller can view their chatbot conversations
- [ ] Seller can view their current package
- [ ] Seller can view available packages
- [ ] Seller data is strictly tenant-isolated
- [ ] No frontend framework is required
- [ ] No separate frontend deployment is required
- [ ] HTML/CSS/JS are served by the existing FastAPI service
- [ ] Existing Phase 1/Phase 2 chatbot functionality remains intact
- [ ] Existing test suite remains green
- [ ] Phase 3 tests are green
- [ ] Production deployment on Railway serves both API and web UI
- [ ] No secrets or tokens are exposed to frontend/static assets

---

# 3.26 Agent Rules

Agents implementing Phase 3 MUST follow these rules:

1. Do not introduce React, Vue, Next.js, Vite, or another frontend framework.

2. Do not create a separate frontend deployment.

3. Do not create a second authentication system.

4. Do not add passwords to `clients`.

5. Do not trust `client_id` supplied by the frontend.

6. Every seller database query must be tenant-scoped.

7. Do not expose OAuth tokens, refresh tokens, OTP hashes, JWT secrets, or
   authorization headers.

8. Do not put business logic in Jinja templates.

9. Do not put SQL or Divar API calls in JavaScript.

10. Do not duplicate existing price normalization/matching logic.

11. Do not modify the meaning of the existing `posts` model merely to support
    the dashboard.

12. Do not invent Divar API endpoints.

13. Verify external API capabilities before implementing listing-management
    operations.

14. All database schema changes require Alembic migrations.

15. All new seller APIs require authentication and tenant-isolation tests.

16. Preserve all existing chatbot behavior.

17. Run the full test suite after each milestone.

18. Do not mark a task complete merely because the page renders. Its API,
    authorization, tenant isolation, error handling, and tests must also be
    complete.

19. Prefer the smallest implementation that satisfies the acceptance criteria.
    Do not introduce infrastructure that Phase 3 does not require.

20. Do not refactor unrelated Phase 1/Phase 2 code while implementing Phase 3
    unless the change is required for correctness, security, or integration.

21. Follow §3.2.4 Design System and Anti-AI-Slop rules for all frontend
    implementation. Do not introduce visual patterns that contradict the
    defined product-specific design direction merely because they are common
    in AI-generated SaaS interfaces.
    
---

# 3.27 Final Architecture

After Phase 3, the application should conceptually look like:

    Browser
       |
       | HTTPS
       v
    FastAPI
       |
       +--------------------+
       |                    |
       v                    v
    Web Layer             API Layer
       |                    |
       v                    v
    Jinja2              Services
    HTML                 |
    CSS                  +---- chatbot
    Vanilla JS           +---- Divar
                         +---- products
                         +---- subscriptions
                         |
                         v
                      PostgreSQL

There is intentionally no separate frontend application in Phase 3.

The architecture must remain ready for a future frontend migration because
the seller UI communicates with well-defined APIs rather than embedding
business logic in templates.