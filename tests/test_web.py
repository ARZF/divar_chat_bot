"""Public web tests for Phase 3 steps 2-12.

Cover public pages, login/OTP presentation, shared static assets, the shared
visual-system vocabulary, visible keyboard focus, existing API routers, and
the client-side session-restoration module.
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
        "/seller/posts",
        "/oauth/callback",
    } <= paths
