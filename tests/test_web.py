"""Web foundation tests for Phase 3 steps 2-3.

Cover Jinja inheritance, base-level HTML/RTL metadata and hooks, shared static
assets, visible keyboard focus, and preservation of existing API routers.
"""

from fastapi.testclient import TestClient

from main import app


def test_probe_inherits_base_document_and_shared_assets():
    with TestClient(app) as c:
        response = c.get("/web/probe")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert response.text.count("<!doctype html>") == 1
    assert response.text.count("<html") == 1
    assert 'lang="fa"' in response.text
    assert 'dir="rtl"' in response.text
    assert "<title>بررسی زیرساخت وب</title>" in response.text
    assert 'href="/static/css/main.css"' in response.text
    assert 'src="/static/js/main.js"' in response.text
    assert "وب‌اپلیکیشن فعال است" in response.text


def test_second_child_inherits_base_and_renders_page_hooks():
    with TestClient(app) as c:
        response = c.get("/web/probe/secondary")

    assert response.status_code == 200
    assert response.text.count("<!doctype html>") == 1
    assert response.text.count("<html") == 1
    assert 'lang="fa"' in response.text
    assert 'dir="rtl"' in response.text
    assert "<title>بررسی هوک‌های قالب</title>" in response.text
    assert '<meta name="probe-hook" content="head">' in response.text
    assert 'id="secondary-probe"' in response.text
    assert 'dataset.pageHook = "true"' in response.text
    assert 'href="/static/css/main.css"' in response.text
    assert 'src="/static/js/main.js"' in response.text


def test_static_css_has_rtl_typography_and_visible_focus():
    with TestClient(app) as c:
        response = c.get("/static/css/main.css")

    assert response.status_code == 200
    assert "text/css" in response.headers["content-type"]
    assert "direction: rtl" in response.text
    assert "font-family:" in response.text
    assert ":focus-visible" in response.text
    assert "outline: 3px solid" in response.text


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
