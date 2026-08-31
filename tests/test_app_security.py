"""Tests for app.py: the security headers (after_request) added after
the 2026-08-28 pentest, and the CSRF protection of all writing
endpoints. The other route tests deliberately run with
WTF_CSRF_ENABLED=False (see conftest.py) - here it is specifically
re-enabled for the duration of each test to check that behavior itself."""
import re


def test_security_headers_present_on_every_response(client):
    resp = client.get("/manage")
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    assert resp.headers["X-Frame-Options"] == "DENY"
    assert resp.headers["Referrer-Policy"] == "same-origin"
    assert "geolocation=()" in resp.headers["Permissions-Policy"]
    csp = resp.headers["Content-Security-Policy"]
    assert "default-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp


def test_no_hsts_header_since_app_is_http_only(client):
    resp = client.get("/manage")
    assert "Strict-Transport-Security" not in resp.headers


def test_post_without_csrf_token_is_rejected(client, app):
    app.config["WTF_CSRF_ENABLED"] = True
    try:
        resp = client.post("/add-category", data={"category_name": "Ohne Token"})
        assert resp.status_code == 400
    finally:
        app.config["WTF_CSRF_ENABLED"] = False


def test_post_with_valid_csrf_token_succeeds(client, app):
    app.config["WTF_CSRF_ENABLED"] = True
    try:
        page = client.get("/manage/categories")
        match = re.search(rb'name="csrf_token" value="([^"]+)"', page.data)
        assert match is not None
        token = match.group(1).decode()

        resp = client.post("/add-category", data={"category_name": "Mit Token", "csrf_token": token})
        assert resp.status_code == 302
    finally:
        app.config["WTF_CSRF_ENABLED"] = False


def test_ajax_post_without_csrf_token_is_rejected(client, app):
    app.config["WTF_CSRF_ENABLED"] = True
    try:
        resp = client.post("/day/2026-06-15/servings", json={"servings": 3})
        assert resp.status_code == 400
    finally:
        app.config["WTF_CSRF_ENABLED"] = False


def test_ajax_post_with_valid_csrf_header_succeeds(client, app):
    app.config["WTF_CSRF_ENABLED"] = True
    try:
        page = client.get("/manage")
        match = re.search(r'window\.CSRF_TOKEN = "([^"]+)"', page.get_data(as_text=True))
        assert match is not None
        token = match.group(1)

        resp = client.post(
            "/day/2026-06-15/servings", json={"servings": 3}, headers={"X-CSRFToken": token}
        )
        assert resp.status_code == 200
    finally:
        app.config["WTF_CSRF_ENABLED"] = False
