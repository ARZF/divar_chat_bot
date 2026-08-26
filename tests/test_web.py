"""Web foundation tests for Phase 3 steps 2-4.

Cover Jinja inheritance, base-level HTML/RTL metadata and hooks, shared static
assets, the shared visual-system vocabulary (§3.2.4), visible keyboard focus,
and preservation of existing API routers.
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
    assert "وب‌اپلیکیشن فعال است" not in response.text  # heading updated in step 4


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


def test_probe_renders_shared_visual_vocabulary():
    with TestClient(app) as c:
        response = c.get("/web/probe")

    html = response.text

    # Layout container + page header
    assert 'class="container"' in html
    assert 'class="page-header"' in html

    # Buttons: default, primary, disabled
    assert 'class="btn"' in html
    assert 'class="btn btn-primary"' in html
    assert 'class="btn btn-sm"' in html
    assert "<button" in html and "disabled" in html

    # Form fields: label association, hint, error text, select
    assert '<label for="probe-name">نام محصول</label>' in html
    assert 'class="hint"' in html
    assert 'class="error-text"' in html
    assert 'class="field has-error"' in html
    assert "<select" in html

    # Table wrapper, semantic table markup, RTL numeric columns
    assert 'class="table-wrap"' in html
    assert "<caption>" in html
    assert 'scope="col"' in html
    assert 'scope="row"' in html
    assert '<th scope="col" class="num">قیمت (تومان)</th>' in html
    assert '<td class="num">18,500,000</td>' in html

    # Alerts (success/warning/error) carry roles
    assert 'class="alert alert-success" role="status"' in html
    assert 'class="alert alert-warning" role="alert"' in html
    assert 'class="alert alert-error" role="alert"' in html

    # Status indicators pair color with Persian labels
    assert 'class="status status-success">فعال' in html
    assert 'class="status status-warning">در انتظار تأیید' in html
    assert 'class="status status-error">خطا' in html
    assert 'class="status status-info">در حال به‌روزرسانی' in html

    # Empty + loading states
    assert 'class="state" role="status"' in html
    assert 'class="state state-loading" role="status"' in html

    # Pagination with current-page marker
    assert 'class="pagination"' in html
    assert 'aria-current="page"' in html


def test_static_css_defines_shared_visual_system():
    with TestClient(app) as c:
        response = c.get("/static/css/main.css")

    css = response.text

    assert response.status_code == 200
    assert "text/css" in response.headers["content-type"]

    # RTL + typography
    assert "direction: rtl" in css
    assert "font-family:" in css
    assert "tabular-nums" in css

    # Token-based vocabulary
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

    # Required primitives
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

    # RTL table overflow is owned by the wrapper, not the page
    assert ".table-wrap" in css and "overflow-x: auto" in css

    # Keyboard focus stays visible
    assert ":focus-visible" in css
    assert "outline:" in css

    # Responsive breakpoints exist
    assert "@media (max-width: 64rem)" in css
    assert "@media (max-width: 40rem)" in css

    # Motion restraint
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
