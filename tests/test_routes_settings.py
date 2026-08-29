"""Tests für routes/settings.py: die Einheiten-Einstellungen-Seite."""


def test_units_view_shows_current_defaults(client):
    resp = client.get("/manage/units")
    assert resp.status_code == 200
    assert b"Einheiten" in resp.data


def test_update_units_persists_valid_choice(client, app):
    resp = client.post("/update-units", data={"mass_unit": "kg", "volume_unit": "l"}, follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/manage/units")

    from services.settings import get_display_units
    with app.app_context():
        assert get_display_units() == {"mass": "kg", "volume": "l"}


def test_update_units_ignores_invalid_choice(client, app):
    from services.settings import get_display_units

    resp = client.post("/update-units", data={"mass_unit": "pfund", "volume_unit": "ml"})
    assert resp.status_code == 302
    with app.app_context():
        assert get_display_units() == {"mass": "g", "volume": "ml"}


def test_units_view_reflects_saved_choice_in_radio_state(client):
    client.post("/update-units", data={"mass_unit": "kg", "volume_unit": "ml"})
    resp = client.get("/manage/units")
    assert b'id="mass_kg" value="kg" checked' in resp.data
