"""Tests für templates/base.html: die Navigationsleiste (kein eigenes
"Wochenplaner"-Element mehr, da der Markenname "Speiseplan" auf dasselbe
Ziel führt; "Einstellungen"-Dropdown mit Direktlinks auf die
Verwaltungs-Unterseiten)."""


def test_nav_has_no_standalone_wochenplaner_link(client):
    resp = client.get("/manage")
    assert "📅 Wochenplaner".encode("utf-8") not in resp.data


def test_nav_settings_dropdown_links_to_all_subpages(client):
    resp = client.get("/manage")
    assert resp.status_code == 200
    assert "⚙️ Einstellungen".encode("utf-8") in resp.data
    for href in [
        "/manage/recipe/create",
        "/manage/recipe/edit-list",
        "/manage/categories",
        "/manage/units",
        "/manage/ingredient-aliases",
    ]:
        assert f'href="{href}"'.encode("utf-8") in resp.data


def test_nav_settings_toggle_still_links_to_manage_overview(client):
    resp = client.get("/manage")
    assert b'id="settingsDropdownToggle"' in resp.data
    assert b'href="/manage" id="settingsDropdownToggle"' in resp.data


def test_nav_settings_active_on_manage_subpages(client):
    resp = client.get("/manage/categories")
    assert b"active-custom" in resp.data
