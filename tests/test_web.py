"""Public web tests for Phase 3 steps 2-9.

Cover public pages, login/OTP presentation, shared static assets, the shared
visual-system vocabulary, visible keyboard focus, and existing API routers.
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


def test_login_renders_safe_accessible_presentation_only():
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
    assert 'aria-describedby="login-help"' in html
    assert 'type="button" class="btn btn-primary" disabled' in html
    assert 'href="/oauth/start"' in html
    assert 'action="#"' in html
    assert 'onsubmit="return false;"' in html
    assert "/auth/otp/request" not in html


def test_otp_renders_safe_accessible_feedback_hooks():
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
    assert 'id="otp-error" class="error-text" role="alert" hidden' in html
    assert 'id="otp-feedback"' in html
    assert 'aria-labelledby="feedback-title"' in html
    assert 'aria-live="polite"' in html
    assert '<section id="otp-feedback"' in html and "hidden" in html
    for hook in (
        "otp-expired",
        "otp-rate-limit",
        "otp-retry",
        "otp-loading",
        "otp-success",
    ):
        assert f'id="{hook}"' in html
    assert 'type="button" class="btn btn-primary" disabled' in html
    assert 'action="#"' in html
    assert 'onsubmit="return false;"' in html
    assert "/auth/otp/verify" not in html


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
