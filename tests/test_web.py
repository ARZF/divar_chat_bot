"""Public web tests for Phase 3 steps 2-13.

Cover public pages, login/OTP presentation, shared static assets, the shared
visual-system vocabulary, visible keyboard focus, existing API routers, the
client-side session-restoration module, and the dashboard shell.
"""

from pathlib import Path

from fastapi.testclient import TestClient

from api.web import TEMPLATES_DIR
from main import app



def test_home_renders_public_page_with_base_document_and_shared_assets():
    with TestClient(app) as c:
        response = c.get("/")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert response.text.count("<!doctype html>") == 1
    assert response.text.count("<html") == 1
    assert 'lang="fa"' in response.text
    assert 'dir="rtl"' in response.text
    assert "دستیار فروش دیوار" in response.text
    assert 'href="/static/css/main.css"' in response.text
    assert 'src="/static/js/main.js"' in response.text
    assert 'href="/login"' in response.text
    assert 'href="/pricing"' in response.text


def test_home_uses_shared_public_navigation():
    with TestClient(app) as c:
        response = c.get("/")

    html = response.text
    assert '<nav class="container page-header"' in html
    assert 'aria-label="ناوبری عمومی"' in html
    assert html.count('href="/login"') >= 1
    assert html.count('href="/pricing"') >= 1


def test_home_contains_only_stated_public_capabilities():
    with TestClient(app) as c:
        response = c.get("/")

    html = response.text
    for phrase in (
        "ارتباط خودکار با مشتری",
        "یافتن قیمت",
        "مدیریت کاتالوگ محصول",
        "اتوماسیون چت‌بات",
    ):
        assert phrase in html

    for invented_content in (
        "تخفیف",
        "رضایت مشتری",
        "کاربر فعال",
        "محبوب‌ترین",
        "testimonial",
        "metric",
    ):
        assert invented_content not in html


def test_home_does_not_expose_seller_specific_information():
    with TestClient(app) as c:
        response = c.get("/")

    html = response.text
    assert "client_id" not in html
    assert "access_token" not in html
    assert "refresh_token" not in html
    assert "seller_id" not in html


def test_pricing_renders_honest_public_empty_state_and_shared_navigation():
    with TestClient(app) as c:
        response = c.get("/pricing")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert response.text.count("<!doctype html>") == 1
    assert 'lang="fa"' in response.text
    assert 'dir="rtl"' in response.text
    assert "در حال حاضر بسته‌ای برای نمایش موجود نیست." in response.text
    assert 'aria-label="ناوبری عمومی"' in response.text
    assert 'href="/"' in response.text
    assert 'href="/pricing"' in response.text
    assert 'href="/login"' in response.text


def test_pricing_has_no_plan_or_payment_implication_or_seller_data():
    with TestClient(app) as c:
        response = c.get("/pricing")

    html = response.text.lower()
    for forbidden in (
        "client_id",
        "seller_id",
        "access_token",
        "refresh_token",
        "checkout",
        "پرداخت",
        "خرید",
        "فعال‌سازی",
        "تخفیف",
        "ماهانه",
        "سالانه",
    ):
        assert forbidden not in html


def test_login_loads_auth_script_and_submit_hooks():
    with TestClient(app) as c:
        response = c.get("/login")

    html = response.text
    assert response.status_code == 200
    assert 'lang="fa"' in html
    assert 'dir="rtl"' in html
    assert '<label for="phone-number">شمارهٔ تلفن</label>' in html
    assert 'type="tel"' in html
    assert 'autocomplete="tel"' in html
    assert 'inputmode="tel"' in html
    assert 'aria-describedby="login-help login-feedback"' in html
    assert 'data-auth-form="request"' in html
    assert 'type="submit" class="btn btn-primary" disabled' in html
    assert 'id="login-feedback"' in html
    assert 'aria-live="polite"' in html
    assert 'href="/oauth/start"' in html
    assert 'src="/static/js/auth.js"' in html
    assert "onsubmit=" not in html


def test_otp_loads_auth_script_and_accessible_feedback_hooks():
    with TestClient(app) as c:
        response = c.get("/login/otp")

    html = response.text
    assert response.status_code == 200
    assert 'lang="fa"' in html
    assert 'dir="rtl"' in html
    assert 'id="phone-context"' in html
    assert '<label for="otp-code">کد یک‌بارمصرف</label>' in html
    assert 'autocomplete="one-time-code"' in html
    assert 'inputmode="numeric"' in html
    assert 'aria-describedby="otp-help otp-error"' in html
    assert 'data-auth-form="verify"' in html
    assert 'id="otp-error" class="error-text" role="alert" hidden' in html
    assert 'id="otp-feedback"' in html
    assert 'aria-labelledby="feedback-title"' in html
    assert 'aria-live="polite"' in html
    assert '<section id="otp-feedback"' in html and "hidden" in html
    for hook in (
        "otp-expired",
        "otp-rate-limit",
        "otp-retry",
        "otp-retry-button",
        "otp-loading",
        "otp-success",
    ):
        assert f'id="{hook}"' in html
    assert 'type="submit" class="btn btn-primary" disabled' in html
    assert 'src="/static/js/auth.js"' in html
    assert "onsubmit=" not in html


def test_auth_script_uses_only_existing_otp_endpoints_and_safe_storage():
    with TestClient(app) as c:
        response = c.get("/static/js/auth.js")

    js = response.text
    assert response.status_code == 200
    assert "javascript" in response.headers["content-type"]
    assert 'postJSON("/auth/otp/request"' in js
    assert 'postJSON("/auth/otp/verify"' in js
    assert "response.status === 400" in js
    assert "response.status === 422" in js
    assert "response.status === 429" in js
    assert "response.status === 503" in js
    assert 'credentials: "same-origin"' in js
    assert 'const PHONE_STORAGE_KEY = "divar_auth_phone"' in js
    assert "sessionStorage.setItem(PHONE_STORAGE_KEY, phoneNumber)" in js
    assert "sessionStorage.removeItem(PHONE_STORAGE_KEY)" in js
    # The token goes to the shared in-memory session store, never to web storage.
    assert "window.DivarSession.setAccessToken(data.access_token)" in js
    assert "inMemoryAccessToken" not in js
    assert "addEventListener" in js
    assert "textContent" in js
    assert "innerHTML" not in js
    assert "localStorage" not in js
    assert "document.cookie" not in js
    assert "console." not in js
    assert "client_id" not in js

    for forbidden_storage in (
        "setItem(\"access_token\"",
        "setItem('access_token'",
        "setItem(\"refresh_token\"",
        "setItem('refresh_token'",
        "setItem(\"code\"",
        "setItem('code'",
    ):
        assert forbidden_storage not in js


def test_login_pages_expose_no_auth_or_seller_secrets():
    with TestClient(app) as c:
        responses = (c.get("/login"), c.get("/login/otp"))

    for response in responses:
        html = response.text.lower()
        for forbidden in (
            "client_id",
            "seller_id",
            "access_token",
            "refresh_token",
            "otp_hash",
            "client_secret",
            "jwt_secret",
            "localstorage",
            "sessionstorage",
            "password",
        ):
            assert forbidden not in html


def test_base_template_loads_shared_session_module_on_every_page():
    with TestClient(app) as c:
        for path in ("/", "/pricing", "/login", "/login/otp"):
            assert 'src="/static/js/session.js"' in c.get(path).text


def test_session_script_restores_session_with_one_refresh_one_retry_and_redirect():
    with TestClient(app) as c:
        response = c.get("/static/js/session.js")

    js = response.text
    assert response.status_code == 200
    assert "javascript" in response.headers["content-type"]

    # Session restoration: existing endpoints only, exactly one refresh call
    # site, one retry, then the login redirect — no loops, no second attempt.
    assert js.count('"/auth/refresh"') == 1
    assert js.count('"/auth/logout"') == 1
    assert 'method: "POST"' in js
    assert 'window.location.assign("/login")' in js
    assert "response.status !== 401" in js
    # Single-flight refresh: concurrent 401s share one /auth/refresh call
    # because the refresh token rotates.
    assert "refreshInFlight" in js
    # Authenticated calls attach the in-memory Bearer token.
    assert '"Authorization", `Bearer ${accessToken}`' in js
    assert 'credentials: "same-origin"' in js
    assert "let accessToken = null" in js

    for forbidden in (
        "localStorage",
        "sessionStorage",
        "document.cookie",
        "setItem",
        "innerHTML",
        "console.",
        "client_id",
    ):
        assert forbidden not in js


def test_web_router_documents_client_side_protected_route_convention():
    """No server-side HTML auth gate exists (refresh cookie path=/auth makes one
    impossible); the reusable protection is session.js, documented in api/web.py."""
    import inspect

    import api.web

    docstring = inspect.getdoc(api.web)
    assert "path=/auth" in docstring
    assert "session.js" in docstring
    assert "get_current_client_id" in docstring
    # No HTML route reads cookies — the web router never authenticates by cookie.
    source = inspect.getsource(api.web)
    assert "Cookie" not in source


def test_temporary_probe_routes_and_templates_are_removed():
    with TestClient(app) as c:
        assert c.get("/web/probe").status_code == 404
        assert c.get("/web/probe/secondary").status_code == 404

    assert not (Path(TEMPLATES_DIR) / "probe.html").exists()
    assert not (Path(TEMPLATES_DIR) / "probe_secondary.html").exists()


def test_static_css_defines_shared_visual_system():
    with TestClient(app) as c:
        response = c.get("/static/css/main.css")

    css = response.text

    assert response.status_code == 200
    assert "text/css" in response.headers["content-type"]
    assert "direction: rtl" in css
    assert "font-family:" in css
    assert "tabular-nums" in css

    for token in (
        "--accent",
        "--success",
        "--warning",
        "--danger",
        "--info",
        "--space-1",
        "--radius-sm",
        "--container",
    ):
        assert token in css

    for primitive in (
        ".container",
        ".btn",
        ".btn-primary",
        ".field",
        ".table-wrap",
        ".alert",
        ".status",
        ".state",
        ".state-loading",
        ".pagination",
    ):
        assert primitive in css

    assert ".table-wrap" in css and "overflow-x: auto" in css
    assert ":focus-visible" in css
    assert "outline:" in css
    assert "@media (max-width: 64rem)" in css
    assert "@media (max-width: 40rem)" in css
    assert "prefers-reduced-motion" in css


def test_static_css_rejects_ai_slop_patterns():
    with TestClient(app) as c:
        response = c.get("/static/css/main.css")

    css = response.text.lower()

    assert "linear-gradient" not in css
    assert "radial-gradient" not in css
    assert "backdrop-filter" not in css
    assert "box-shadow" not in css or "--shadow-pop" in css


def test_static_js_is_served_and_sets_shared_load_marker():
    with TestClient(app) as c:
        response = c.get("/static/js/main.js")

    assert response.status_code == 200
    assert "javascript" in response.headers["content-type"]
    assert 'dataset.jsLoaded = "true"' in response.text


def test_existing_api_routes_still_registered():
    paths = {getattr(route, "path", None) for route in app.routes}
    assert {
        "/api/v1/webhook",
        "/auth/otp/request",
        "/admin/upload-prices",
        "/oauth/callback",
        "/api/v1/seller/dashboard/summary",
    } <= paths
    # POST /seller/posts was retired in step 20 — listings now enter `posts`
    # only via services/divar_listings.py's sync after Divar OAuth.
    assert "/seller/posts" not in paths


# --------------------------------------------------------------------------------------
# Dashboard shell (Phase 3 step 13)
# --------------------------------------------------------------------------------------

def test_dashboard_renders_anonymously_with_shared_assets_and_states():
    with TestClient(app) as c:
        response = c.get("/dashboard")

    html = response.text
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert response.text.count("<!doctype html>") == 1
    assert 'lang="fa"' in html
    assert 'dir="rtl"' in html
    assert 'src="/static/js/session.js"' in html
    assert 'src="/static/js/dashboard.js"' in html
    # The three UI states exist: loading, error, and data (hidden until JS fills it).
    assert 'id="dashboard-loading"' in html
    assert 'id="dashboard-error"' in html
    assert 'id="dashboard-data"' in html
    assert 'role="alert"' in html


def test_dashboard_nav_lists_all_future_sections_with_current_page_marker():
    with TestClient(app) as c:
        html = c.get("/dashboard").text

    assert 'aria-label="ناوبری میزکار فروشنده"' in html
    for href in (
        "/dashboard",
        "/dashboard/products",
        "/dashboard/listings",
        "/dashboard/conversations",
        "/dashboard/subscription",
        "/dashboard/settings",
    ):
        assert f'href="{href}"' in html
    # Only the current page is marked; future pages are plain links (404 is
    # expected until their steps land — that's the honest state, not a stub).
    assert html.count('aria-current="page"') == 1
    assert 'href="/dashboard" aria-current="page"' in html


def test_dashboard_shows_identity_counts_and_honest_subscription_placeholder():
    with TestClient(app) as c:
        html = c.get("/dashboard").text

    # Identity and the three tenant-scoped count cells.
    assert 'id="seller-phone"' in html
    assert 'id="post-count"' in html
    assert 'id="conversation-count"' in html
    assert 'id="post-conversation-count"' in html
    # Logout is wired to the shared session module (data attribute hook).
    assert "data-dashboard-logout" in html
    # Subscription slot exists and states unavailability honestly — no
    # fabricated plan names, prices, or expiry claims.
    assert "هنوز در دسترس نیست" in html
    for invented in ("بستهٔ تجاری", "اشتراک فعال", "۳۰ روز", "پرکاربردترین"):
        assert invented not in html


def test_dashboard_exposes_no_auth_or_seller_secrets():
    with TestClient(app) as c:
        html = c.get("/dashboard").text.lower()

    for forbidden in (
        "client_id",
        "seller_id",
        "access_token",
        "refresh_token",
        "otp_hash",
        "client_secret",
        "jwt_secret",
        "password",
    ):
        assert forbidden not in html


def test_dashboard_script_uses_authfetch_and_shared_session_module():
    with TestClient(app) as c:
        response = c.get("/static/js/dashboard.js")

    js = response.text
    assert response.status_code == 200
    assert "javascript" in response.headers["content-type"]
    # Data loads through the shared session module only — no raw fetch, no
    # duplicated refresh/retry/redirect logic, no second logout endpoint.
    assert "window.DivarSession.authFetch" in js
    assert "window.DivarSession.logout" in js
    assert "/api/v1/seller/dashboard/summary" in js
    assert "/auth/refresh" not in js
    assert "/auth/logout" not in js
    assert "window.location" not in js
    assert "fetch(" not in js.replace("authFetch(", "")
    for forbidden in (
        "localStorage",
        "sessionStorage",
        "document.cookie",
        "setItem",
        "innerHTML",
        "console.",
        "client_id",
    ):
        assert forbidden not in js


# --------------------------------------------------------------------------------------
# Products page (Phase 3 step 18)
# --------------------------------------------------------------------------------------

def test_products_page_renders_anonymously_with_shared_assets_and_states():
    with TestClient(app) as c:
        response = c.get("/dashboard/products")

    html = response.text
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert response.text.count("<!doctype html>") == 1
    assert 'lang="fa"' in html
    assert 'dir="rtl"' in html
    assert 'src="/static/js/session.js"' in html
    assert 'src="/static/js/products.js"' in html
    assert 'aria-label="ناوبری میزکار فروشنده"' in html
    # Products is the current page in the shared nav — exactly one marker.
    assert html.count('aria-current="page"') == 1
    assert 'href="/dashboard/products" aria-current="page"' in html
    # The three list states exist (loading, error, data/empty).
    assert 'id="products-loading"' in html
    assert 'id="products-error"' in html
    assert 'id="products-data"' in html
    assert 'role="alert"' in html
    # Compact desktop table with the four §3.7.2 columns, built on the
    # shared .table-wrap primitive and the stacked-mobile table class.
    assert 'id="products-tbody"' in html
    assert 'class="table-wrap"' in html
    assert 'class="table-stack"' in html
    for th in (
        '<th scope="col">نام محصول</th>',
        '<th scope="col" class="num">قیمت (تومان)</th>',
        '<th scope="col">آخرین به‌روزرسانی</th>',
        '<th scope="col">عملیات</th>',
    ):
        assert th in html
    # Search, add/edit form, import, and pagination hooks all present.
    assert 'id="product-search"' in html
    assert 'id="product-form"' in html
    assert 'id="product-form-title"' in html
    assert 'id="import-file"' in html
    assert 'accept=".xlsx"' in html
    assert 'id="import-submit"' in html
    assert 'id="products-pagination"' in html
    assert 'aria-label="صفحه‌بندی محصولات"' in html
    # The replace-all import warning is explicit and visible, not implied.
    assert "همهٔ محصولات فعلی شما را حذف" in html
    assert "جایگزین می‌کند" in html


def test_products_page_exposes_no_auth_or_seller_secrets():
    with TestClient(app) as c:
        html = c.get("/dashboard/products").text.lower()

    for forbidden in (
        "client_id",
        "seller_id",
        "access_token",
        "refresh_token",
        "otp_hash",
        "client_secret",
        "jwt_secret",
        "password",
        "normalized_name",
    ):
        assert forbidden not in html


def test_products_script_uses_authfetch_and_shared_session_module():
    with TestClient(app) as c:
        response = c.get("/static/js/products.js")

    js = response.text
    assert response.status_code == 200
    assert "javascript" in response.headers["content-type"]
    # All authenticated traffic goes through the shared session module only.
    assert "window.DivarSession.authFetch" in js
    assert "window.DivarSession.logout" in js
    assert 'const LIST_URL = "/api/v1/seller/products"' in js
    assert 'const IMPORT_URL = "/api/v1/seller/products/import"' in js
    # No raw fetch, no duplicated refresh/retry/redirect logic.
    assert "fetch(" not in js.replace("authFetch(", "")
    assert "/auth/refresh" not in js
    assert "/auth/logout" not in js
    assert "window.location" not in js
    # Destructive operations are confirmed before anything is sent; the
    # import sends multipart form data built with browser-native APIs.
    assert "confirm(" in js
    assert "FormData" in js
    assert "URLSearchParams" in js
    # Duplicate-name (409) handling exists without echoing any product id.
    assert "response.status === 409" in js
    for forbidden in (
        "localStorage",
        "sessionStorage",
        "document.cookie",
        "setItem",
        "innerHTML",
        "insertAdjacentHTML",
        "console.",
        "client_id",
        "eval(",
    ):
        assert forbidden not in js


def test_products_css_adds_toolbar_and_deliberate_stacked_mobile_table():
    with TestClient(app) as c:
        response = c.get("/static/css/main.css")

    css = response.text
    assert response.status_code == 200
    # Search + actions row (the one genuine gap the products page adds).
    assert ".toolbar" in css
    assert ".toolbar-search" in css
    # JS-driven pagination uses real buttons on the existing primitive.
    assert ".pagination button" in css
    # Deliberate mobile representation: stacked rows with inline labels,
    # inside the existing mobile breakpoint (not a new breakpoint) — the
    # desktop prefix keeps the compact rectangular table untouched.
    assert ".table-stack thead" in css
    assert ".table-stack td[data-label]::before" in css
    assert "attr(data-label)" in css
    assert ".table-stack td.cell-name" in css
    assert ".table-stack" not in css.split("@media (max-width: 40rem)")[0]


# --------------------------------------------------------------------------------------
# Listings page (Phase 3 step 22)
# --------------------------------------------------------------------------------------

def test_listings_page_renders_anonymously_with_shared_assets_and_states():
    with TestClient(app) as c:
        response = c.get("/dashboard/listings")

    html = response.text
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert response.text.count("<!doctype html>") == 1
    assert 'lang="fa"' in html
    assert 'dir="rtl"' in html
    assert 'src="/static/js/session.js"' in html
    assert 'src="/static/js/listings.js"' in html
    assert 'aria-label="ناوبری میزکار فروشنده"' in html
    # Listings is the current page in the shared nav — exactly one marker.
    assert html.count('aria-current="page"') == 1
    assert 'href="/dashboard/listings" aria-current="page"' in html
    # The three list states exist (loading, error, data/empty).
    assert 'id="listings-loading"' in html
    assert 'id="listings-error"' in html
    assert 'id="listings-data"' in html
    assert 'role="alert"' in html
    # Sync trigger, its failure/success slots, and the OTP-only guidance
    # (skipped sync) with a direct "Sign in with Divar" path.
    assert 'id="listings-sync-button"' in html
    assert 'id="listings-sync-error"' in html
    assert 'id="listings-sync-feedback"' in html
    assert 'id="listings-sync-skipped"' in html
    assert 'href="/oauth/start"' in html
    # Honest generic empty state (the API cannot distinguish never-synced
    # from synced-but-zero, so no fabricated distinction is rendered).
    assert "دکمهٔ «همگام‌سازی با دیوار» را بزنید" in html
    # Compact desktop table on the shared primitives with ONLY the §3.8.3
    # columns the step 19/21 APIs support.
    assert 'id="listings-tbody"' in html
    assert 'class="table-wrap"' in html
    assert 'class="table-stack"' in html
    for th in (
        '<th scope="col">آگهی</th>',
        '<th scope="col">وضعیت در دیوار</th>',
        '<th scope="col">دستیار چت دیوار</th>',
        '<th scope="col">شمارهٔ تماس</th>',
        '<th scope="col" class="num">آخرین همگام‌سازی</th>',
        '<th scope="col">پاسخ‌گوی خودکار</th>',
        '<th scope="col">لینک</th>',
    ):
        assert th in html
    # Unsupported capabilities are absent, not implied: no price column, no
    # lifecycle status, no edit/delete controls (§3.8.3).
    for unsupported in ("قیمت", "ویرایش", "حذف"):
        assert unsupported not in html
    # The chat_enabled/is_available distinction is explicit visible copy.
    assert "تغییری در خود آگهی دیوار ایجاد نمی‌کند" in html
    assert "تنظیم خود دیوار است" in html
    assert 'aria-label="صفحه‌بندی آگهی‌ها"' in html


def test_listings_page_exposes_no_auth_or_seller_secrets():
    with TestClient(app) as c:
        html = c.get("/dashboard/listings").text.lower()

    for forbidden in (
        "client_id",
        "seller_id",
        "access_token",
        "refresh_token",
        "otp_hash",
        "client_secret",
        "jwt_secret",
        "password",
    ):
        assert forbidden not in html


def test_listings_script_uses_authfetch_and_renders_only_supported_fields():
    with TestClient(app) as c:
        response = c.get("/static/js/listings.js")

    js = response.text
    assert response.status_code == 200
    assert "javascript" in response.headers["content-type"]
    # All authenticated traffic goes through the shared session module only.
    assert "window.DivarSession.authFetch" in js
    assert "window.DivarSession.logout" in js
    assert 'const LIST_URL = "/api/v1/seller/listings"' in js
    assert 'const SYNC_URL = "/api/v1/seller/listings/sync"' in js
    # No raw fetch, no duplicated refresh/retry/redirect logic.
    assert "fetch(" not in js.replace("authFetch(", "")
    assert "/auth/refresh" not in js
    assert "/auth/logout" not in js
    assert "window.location" not in js
    # Exactly the two supported mutations: explicit sync (POST) and the
    # reversible availability toggle (PATCH, JSON body). The toggle is
    # reversible, so unlike products' delete there is no confirmation dialog.
    assert 'method: "POST"' in js
    assert 'method: "PATCH"' in js
    assert "confirm(" not in js
    assert "DELETE" not in js
    # Exactly the step 21 field contract is rendered — nothing fabricated.
    for field in (
        "post_token",
        "title",
        "category",
        "chat_enabled",
        "is_phone_hidden",
        "present_on_divar",
        "last_synced_at",
        "is_available",
    ):
        assert field in js
    # Token-only Divar link — no fabricated seo-slug (step 19 finding).
    assert '"https://divar.ir/v/"' in js
    # present_on_divar=false is visually marked (never hidden) and the
    # OTP-only "skipped" sync is handled as guidance, not an error.
    assert "row-absent" in js
    assert 'data.status === "skipped"' in js
    for forbidden in (
        "localStorage",
        "sessionStorage",
        "document.cookie",
        "setItem",
        "innerHTML",
        "insertAdjacentHTML",
        "console.",
        "client_id",
        "eval(",
        "price",
        "divar_post_id",
    ):
        assert forbidden not in js


def test_listings_css_marks_absent_rows_informationally():
    with TestClient(app) as c:
        response = c.get("/static/css/main.css")

    css = response.text
    assert response.status_code == 200
    # Absent-from-Divar rows: muted and informational — never danger-colored,
    # and never hidden (the soft-sync design keeps them and their toggle).
    assert ".row-absent td" in css
    # Per-toggle failure text and the secondary category line.
    assert ".toggle-error" in css
    assert ".toggle-error[hidden]" in css
    assert ".cell-sub" in css


# --------------------------------------------------------------------------------------
# Conversations page (Phase 3 step 25)
# --------------------------------------------------------------------------------------

def test_conversations_page_renders_anonymously_with_shared_assets_and_states():
    with TestClient(app) as c:
        response = c.get("/dashboard/conversations")

    html = response.text
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert response.text.count("<!doctype html>") == 1
    assert 'lang="fa"' in html
    assert 'dir="rtl"' in html
    assert 'src="/static/js/session.js"' in html
    assert 'src="/static/js/conversations.js"' in html
    assert 'aria-label="ناوبری میزکار فروشنده"' in html
    # Conversations is the current page in the shared nav — exactly one marker.
    assert html.count('aria-current="page"') == 1
    assert 'href="/dashboard/conversations" aria-current="page"' in html
    # The list states exist: loading, error (with retry), data, empty.
    assert 'id="conversations-loading"' in html
    assert 'id="conversations-error"' in html
    assert 'id="conversations-retry"' in html
    assert 'id="conversations-data"' in html
    assert 'id="conversation-list"' in html
    assert 'role="alert"' in html
    # Useful generic empty state — not an error implication.
    assert "هنوز گفتگویی وجود ندارد" in html
    assert "گفتگوهای خریداران دربارهٔ آگهی‌های شما اینجا نمایش داده می‌شود" in html
    # Detail pane states: placeholder, loading, error with retry, open area.
    assert 'id="conversation-placeholder"' in html
    assert "یک گفتگو را از فهرست انتخاب کنید" in html
    assert 'id="conversation-loading"' in html
    assert 'id="conversation-error"' in html
    assert 'id="conversation-retry"' in html
    assert 'id="conversation-open"' in html
    assert 'id="conversation-back"' in html
    assert "بازگشت به فهرست" in html
    # Listing context, state, and message history hooks.
    assert 'id="conversation-listing-title"' in html
    assert 'id="conversation-state"' in html
    assert 'id="messages-list"' in html
    assert 'id="messages-empty"' in html
    assert 'aria-label="صفحه‌بندی گفتگوها"' in html
    assert 'aria-label="صفحه‌بندی پیام‌ها"' in html
    # Read-only viewer: no compose/send box, no mark-read, no archive/delete.
    for mutation in ("ارسال پیام", "پاسخ", "خوانده شد", "بایگانی", "حذف"):
        assert mutation not in html


def test_conversations_page_exposes_no_auth_or_seller_secrets():
    with TestClient(app) as c:
        html = c.get("/dashboard/conversations").text.lower()

    for forbidden in (
        "client_id",
        "seller_id",
        "access_token",
        "refresh_token",
        "otp_hash",
        "client_secret",
        "jwt_secret",
        "password",
    ):
        assert forbidden not in html


def test_conversations_script_uses_only_post_conversation_apis():
    with TestClient(app) as c:
        response = c.get("/static/js/conversations.js")

    js = response.text
    assert response.status_code == 200
    assert "javascript" in response.headers["content-type"]
    # All authenticated traffic goes through the shared session module only.
    assert "window.DivarSession.authFetch" in js
    assert "window.DivarSession.logout" in js
    assert 'const LIST_URL = "/api/v1/seller/post-conversations"' in js
    # The step 24 cleanup: ONLY the supplier-side (post_conversations) APIs
    # are consumed — the removed Buyer↔Bot seller APIs must not reappear.
    assert "/seller/conversations" not in js
    # No raw fetch, no duplicated refresh/retry/redirect logic, no page-level
    # navigation (the ?conversation= deep link uses history.replaceState).
    assert "fetch(" not in js.replace("authFetch(", "")
    assert "/auth/refresh" not in js
    assert "/auth/logout" not in js
    assert "window.location.assign" not in js
    assert "window.location.replace" not in js
    # Read-only viewer: GET requests only — no message sending, no state
    # mutation, no realtime transport of any kind.
    assert 'method: "POST"' not in js
    assert 'method: "PATCH"' not in js
    assert 'method: "PUT"' not in js
    assert "DELETE" not in js
    assert "WebSocket" not in js
    assert "EventSource" not in js
    assert "sendMessage" not in js
    # Exactly the step 24 field contract is rendered — nothing fabricated,
    # no sensitive or internal fields.
    for field in (
        "conversation_id",
        "listing_title",
        "current_state",
        "created_at",
        "updated_at",
        "last_message",
        "sender_type",
        "text_content",
        "sent_at",
        "page_count",
    ):
        assert field in js
    # A conversation with no valid listing mapping is still displayed, with
    # a neutral fallback — never hidden, never fabricated.
    assert "آگهی در دسترس نیست" in js
    # Chronological backend order is rendered as received — never reversed.
    assert "reverse()" not in js
    # Backend pagination contract respected: page numbers are requested, the
    # default page_size is used (no oversized/unbounded fetch).
    assert 'params.set("page"' in js
    assert "page_size" not in js
    # Missing/invalid conversation: same non-leaking 404 message, selection
    # cleared, nothing exposed about *why* it is missing (§3.14).
    assert "response.status === 404" in js
    assert "این گفتگو پیدا نشد." in js
    # Selected conversation state is representable in the URL without a
    # router (deep link via query param, replaceState not pushState).
    assert 'new URLSearchParams(window.location.search)' in js
    assert "history.replaceState" in js
    assert "history.pushState" not in js
    for forbidden in (
        "localStorage",
        "sessionStorage",
        "document.cookie",
        "setItem",
        "innerHTML",
        "insertAdjacentHTML",
        "console.",
        "client_id",
        "eval(",
        "post_token",
        "divar_conversation_id",
    ):
        assert forbidden not in js


def test_conversations_css_adds_split_view_and_mobile_navigation():
    with TestClient(app) as c:
        response = c.get("/static/css/main.css")

    css = response.text
    assert response.status_code == 200
    # Desktop split view: list pane + detail pane on the shared grid language.
    assert ".conversations-layout" in css
    assert "grid-template-columns: minmax(16rem, 22rem) 1fr" in css
    # Selected conversation rows use the existing accent treatment.
    assert ".conversation-item[aria-current]" in css
    # Sender sides are distinguished with logical (RTL-safe) properties.
    assert ".message-buyer" in css
    assert ".message-bot" in css
    assert "justify-content: flex-start" in css
    assert "justify-content: flex-end" in css
    # The list → detail mobile navigation lives INSIDE the existing 40rem
    # breakpoint (no new breakpoint), and the desktop prefix stays two-pane.
    mobile_block = css.split("@media (max-width: 40rem)")[1]
    assert ".conversations-layout.conversations-selected .conversation-list-pane" in mobile_block
    assert ".conversations-layout.conversations-selected .conversation-detail-pane" in mobile_block
    assert ".conversation-back" in mobile_block
    desktop_block = css.split("@media (max-width: 40rem)")[0]
    assert ".conversations-selected" not in desktop_block
