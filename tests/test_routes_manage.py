"""Tests für routes/manage.py: die Verwaltungs-Übersichtsseite mit
Seitenleisten-Navigation und Dashboard-Kennzahlen."""
from datetime import datetime, timedelta, timezone


def test_manage_page_renders(client):
    resp = client.get("/manage")
    assert resp.status_code == 200
    assert "Übersicht".encode("utf-8") in resp.data
    assert b'class="manage-shell"' in resp.data


def test_manage_page_sidebar_links_to_all_sections(client):
    resp = client.get("/manage")
    assert resp.status_code == 200
    for path in (
        "/manage/recipe/create", "/manage/recipe/edit-list", "/manage/categories",
        "/manage/units", "/manage/ingredient-aliases", "/manage/ingredient-nutrition",
    ):
        assert path.encode() in resp.data


def test_manage_page_shows_stats(client, make_category, make_recipe):
    cat_id = make_category("Suppe")
    make_recipe("Testgericht", category_id=cat_id)

    resp = client.get("/manage")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    # Genau 1 Rezept und 1 Kategorie in dieser isolierten Testdatenbank.
    assert html.count('<div class="num">1</div>') >= 2


def test_manage_page_empty_state_has_no_recent_list(client):
    resp = client.get("/manage")
    assert resp.status_code == 200
    assert b'class="recent"' not in resp.data


def test_manage_page_lists_recently_updated_recipes(client, app, make_recipe):
    from models import Recipe, db

    recipe_id = make_recipe("Frisch bearbeitet")
    with app.app_context():
        recipe = db.session.get(Recipe, recipe_id)
        recipe.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        db.session.commit()

    resp = client.get("/manage")
    assert resp.status_code == 200
    assert b"Frisch bearbeitet" in resp.data
    assert "Heute".encode("utf-8") in resp.data


def test_manage_page_recipe_without_updated_at_is_excluded_from_recent(client, app, make_recipe):
    """Rezepte ohne updated_at (sollte nach der Migration eigentlich nicht
    mehr vorkommen, siehe app.py: init_db()) tauchen defensiv trotzdem
    nicht in der "Zuletzt bearbeitet"-Liste auf, statt einen Fehler beim
    Formatieren des Zeitpunkts auszulösen."""
    from models import Recipe, db

    recipe_id = make_recipe("Ohne Zeitstempel")
    with app.app_context():
        recipe = db.session.get(Recipe, recipe_id)
        recipe.updated_at = None
        db.session.commit()

    resp = client.get("/manage")
    assert resp.status_code == 200
    assert b"Ohne Zeitstempel" not in resp.data


def test_format_relative_day():
    from routes.manage import _format_relative_day

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    assert _format_relative_day(now) == "Heute"
    assert _format_relative_day(now - timedelta(days=1)) == "Gestern"
    assert _format_relative_day(now - timedelta(days=5)) == "vor 5 Tagen"


def test_manage_page_has_theme_switcher(client):
    resp = client.get("/manage")
    assert resp.status_code == 200
    assert b'id="themeSwitcher"' in resp.data
    assert b"speiseplanSetThemePreference" in resp.data
