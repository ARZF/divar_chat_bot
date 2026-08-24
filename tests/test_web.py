"""Foundation probe tests (Phase 3 step 2).

Cover only the template/static plumbing added in this step: the probe HTML
renders through Jinja2, static CSS/JS are served, and adding the web layer did
not break an existing API route.
"""

from fastapi.testclient import TestClient

from main import app


def test_probe_route_renders_template():
    with TestClient(app) as c:
        response = c.get("/web/probe")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    # Rendered template markers (RTL doc + root-relative static paths, which
    # stay correct behind the production TLS proxy).
    assert 'lang="fa"' in response.text
    assert 'dir="rtl"' in response.text
    assert '"/static/css/main.css"' in response.text
    assert '"/static/js/main.js"' in response.text


def test_static_css_is_served():
    with TestClient(app) as c:
        response = c.get("/static/css/main.css")
    assert response.status_code == 200
    assert "text/css" in response.headers["content-type"]
    assert "#probe" in response.text


def test_static_js_is_served():
    with TestClient(app) as c:
        response = c.get("/static/js/main.js")
    assert response.status_code == 200
    assert "javascript" in response.headers["content-type"]
    assert "jsLoaded" in response.text


def test_existing_api_routes_still_registered():
    # Adding the web router and static mount must not drop existing routers.
    paths = {getattr(route, "path", None) for route in app.routes}
    assert {
        "/api/v1/webhook",
        "/auth/otp/request",
        "/admin/upload-prices",
        "/seller/posts",
        "/oauth/callback",
    } <= paths
