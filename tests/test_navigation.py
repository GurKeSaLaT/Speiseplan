"""Tests for templates/base.html: the global sidebar (see
static/style.css: .app-shell/.app-rail) - has replaced the former green
top navbar with settings dropdown since the overall redesign. The bar
is rendered identically on EVERY page, with the active state computed
server-side (Jinja/request.path) - no more click/hover JS needed."""


def test_sidebar_present_on_every_page(client):
    for path in ("/", "/manage"):
        resp = client.get(path, follow_redirects=True)
        assert resp.status_code == 200
        assert b'class="app-shell"' in resp.data
        assert b'class="app-rail"' in resp.data
        assert b'class="rail-brand"' in resp.data


def test_sidebar_links_to_all_sections(client):
    resp = client.get("/", follow_redirects=True)
    assert resp.status_code == 200
    for href in (
        "/manage/recipe/create", "/manage/recipe/edit-list", "/manage/categories",
        "/manage/units", "/manage/ingredient-aliases", "/manage/ingredient-nutrition",
    ):
        assert f'href="{href}"'.encode("utf-8") in resp.data


def test_sidebar_brand_links_home(client):
    resp = client.get("/manage")
    assert resp.status_code == 200
    assert b'class="rail-brand" href="/"' in resp.data


def test_sidebar_wochenplan_active_on_plan_page(client):
    resp = client.get("/", follow_redirects=True)
    assert resp.status_code == 200
    assert b'class="nav-link active" href="/"' in resp.data
    assert b'class="nav-link " href="/manage"' in resp.data


def test_sidebar_uebersicht_active_only_on_manage_root(client):
    resp = client.get("/manage")
    assert resp.status_code == 200
    assert b'class="nav-link " href="/"' in resp.data
    assert b'class="nav-link active" href="/manage"' in resp.data


def test_sidebar_rail_link_active_on_manage_subpage(client):
    resp = client.get("/manage/categories")
    assert resp.status_code == 200
    assert b'class="rail-link active" href="/manage/categories"' in resp.data
    # The main targets above deliberately stay inactive on subpages -
    # only the matching shortcut link in the group below gets marked.
    assert b'class="nav-link " href="/manage"' in resp.data


def test_sidebar_theme_switcher_present(client):
    resp = client.get("/", follow_redirects=True)
    assert resp.status_code == 200
    assert b'id="themeSwitcher"' in resp.data
    assert b"speiseplanSetThemePreference" in resp.data
