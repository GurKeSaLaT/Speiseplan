"""Tests für routes/plan/pages.py: Seiten-Routen des Wochenplan-Kalenders
(Übersicht, Erstellen-Formular, automatisches Auffüllen+Speichern)."""
from datetime import date, timedelta

from services.planning import monday_of


def _make_many_recipes(make_recipe, count=7, is_side_dish=False, prefix="Gericht"):
    return [make_recipe(f"{prefix} {i}", is_side_dish=is_side_dish) for i in range(count)]


# --- index ---

def test_index_redirects_to_current_week(client):
    resp = client.get("/")
    assert resp.status_code == 302
    expected_monday = monday_of(date.today()).isoformat()
    assert expected_monday in resp.headers["Location"]


# --- week_view ---

def test_week_view_redirects_non_monday_to_monday(client):
    wednesday = date(2026, 6, 17)
    resp = client.get(f"/plan/{wednesday.isoformat()}")
    assert resp.status_code == 302
    assert "2026-06-15" in resp.headers["Location"]


def test_week_view_invalid_date_returns_404(client):
    resp = client.get("/plan/not-a-date")
    assert resp.status_code == 404


def test_week_view_shows_create_prompt_without_plan(client):
    monday = date(2026, 6, 15)
    resp = client.get(f"/plan/{monday.isoformat()}")
    assert resp.status_code == 200
    assert "noch keinen Plan".encode("utf-8") in resp.data


def test_week_view_shows_full_plan_when_data_exists(client, app, make_recipe):
    from models import PlanDay, db

    monday = date(2026, 6, 15)
    recipe_id = make_recipe("Montagsgericht")
    with app.app_context():
        db.session.add(PlanDay(date=monday, main_recipe_id=recipe_id, servings=2))
        db.session.commit()

    resp = client.get(f"/plan/{monday.isoformat()}")
    assert resp.status_code == 200
    assert "noch keinen Plan".encode("utf-8") not in resp.data
    assert "Dein Wochenplan".encode("utf-8") in resp.data
    assert b'"name": "Montagsgericht"' in resp.data or "Montagsgericht".encode("utf-8") in resp.data
    # Rezept-Detail-Fenster (siehe static/plan.js: openRecipeDetail) muss
    # als Markup vorhanden sein, unabhängig davon, ob für diese Woche
    # bereits ein Plan existiert.
    assert b'id="recipeDetailModal"' in resp.data
    assert b'id="recipeDetailCookedCheckbox"' in resp.data


def test_week_view_has_pantry_list_panel(client, app, make_recipe):
    """Gewürze/Verbrauchsartikel (siehe services/shopping.py:
    PANTRY_CATEGORIES) landen nicht direkt auf der Einkaufsliste, sondern
    auf einer separaten "Vorrat prüfen"-Liste (siehe
    static/plan-shopping.js: renderPantryList) - deren leere Hülle muss
    unabhängig vom Planzustand immer vorhanden sein, JS befüllt sie."""
    from models import PlanDay, db

    monday = date(2026, 6, 15)
    recipe_id = make_recipe("Montagsgericht")
    with app.app_context():
        db.session.add(PlanDay(date=monday, main_recipe_id=recipe_id, servings=2))
        db.session.commit()

    resp = client.get(f"/plan/{monday.isoformat()}")
    assert resp.status_code == 200
    assert b'id="pantryListContainer"' in resp.data
    assert b'id="pantryItemsCount"' in resp.data
    assert "Vorrat prüfen".encode("utf-8") in resp.data


def test_week_view_plan_data_reflects_excluded_and_servings(client, app):
    from models import PlanDay, db

    monday = date(2026, 6, 15)
    with app.app_context():
        db.session.add(PlanDay(date=monday, excluded=True, servings=4))
        db.session.commit()

    resp = client.get(f"/plan/{monday.isoformat()}")
    assert resp.status_code == 200
    import json
    import re

    match = re.search(r"window\.PLAN_DATA = (\{.*?\});", resp.get_data(as_text=True), re.S)
    assert match is not None
    plan_data = json.loads(match.group(1))
    assert plan_data["excludedDays"][0] is True
    assert plan_data["servingsList"][0] == 4
    assert plan_data["plan"][0] is None


def test_week_view_plan_data_reflects_cooked_main(client, app, make_recipe):
    from models import PlanDay, db

    monday = date(2026, 6, 15)
    recipe_id = make_recipe("Gekochtes Gericht")
    with app.app_context():
        db.session.add(PlanDay(date=monday, main_recipe_id=recipe_id, cooked=True))
        db.session.add(PlanDay(date=monday + timedelta(days=1), cooked=False))
        db.session.commit()

    resp = client.get(f"/plan/{monday.isoformat()}")
    assert resp.status_code == 200
    import json
    import re

    match = re.search(r"window\.PLAN_DATA = (\{.*?\});", resp.get_data(as_text=True), re.S)
    plan_data = json.loads(match.group(1))
    assert plan_data["cookedMain"][0] is True
    assert plan_data["cookedMain"][1] is False


def test_week_view_extra_items_use_display_unit(client, app):
    from models import ExtraShoppingItem, db
    from services.settings import update_display_units

    monday = date(2026, 6, 15)
    with app.app_context():
        update_display_units("kg", "ml")
        db.session.add(ExtraShoppingItem(week_start=monday, name="Mehl", amount=2000, unit="g"))
        db.session.commit()

    resp = client.get(f"/plan/{monday.isoformat()}")
    import json
    import re

    match = re.search(r"window\.PLAN_DATA = (\{.*?\});", resp.get_data(as_text=True), re.S)
    plan_data = json.loads(match.group(1))
    assert plan_data["extraItems"] == [{"id": plan_data["extraItems"][0]["id"], "name": "Mehl", "amount": 2, "unit": "kg", "category": None}]


# --- week_create_view ---

def test_week_create_view_lists_recipes_with_category_badge(client, make_category, make_recipe):
    cat_id = make_category("Vegan")
    make_recipe("Erstellbares Gericht", category_id=cat_id)
    resp = client.get("/plan/2026-06-15/create")
    assert resp.status_code == 200
    assert b"Erstellbares Gericht" in resp.data
    # "categories" wird an create_week.html durchgereicht, aber dort NICHT
    # separat gerendert - nur ueber das data-category-Attribut/Badge jedes
    # einzelnen Suchtreffers taucht der Kategorie-Name im HTML auf.
    assert b"Vegan" in resp.data


def test_week_create_view_invalid_date_returns_404(client):
    resp = client.get("/plan/garbage/create")
    assert resp.status_code == 404


def test_week_create_view_normalizes_non_monday_without_redirect(client):
    resp = client.get("/plan/2026-06-17/create")
    assert resp.status_code == 200  # kein Redirect, siehe Docstring in pages.py


# --- week_generate ---

def test_week_generate_invalid_date_returns_404(client):
    resp = client.post("/plan/garbage/generate", data={})
    assert resp.status_code == 404


def test_week_generate_fixed_assignment_is_respected(client, app, make_recipe):
    from models import PlanDay, db

    fixed_id = make_recipe("Fest zugewiesen")
    _make_many_recipes(make_recipe, count=6)

    form = {"day_recipe_0": str(fixed_id)}
    resp = client.post("/plan/2026-06-15/generate", data=form, follow_redirects=False)
    assert resp.status_code == 302

    with app.app_context():
        monday_row = PlanDay.query.filter_by(date=date(2026, 6, 15)).first()
        assert monday_row.main_recipe_id == fixed_id


def test_week_generate_fills_all_seven_days(client, app, make_recipe):
    from models import PlanDay, db

    _make_many_recipes(make_recipe, count=7)
    client.post("/plan/2026-06-15/generate", data={})

    with app.app_context():
        rows = PlanDay.query.filter(
            PlanDay.date.in_([date(2026, 6, 15) + timedelta(days=i) for i in range(7)])
        ).all()
        assert len(rows) == 7
        assert all(r.main_recipe_id is not None for r in rows)


def test_week_generate_excluded_day_has_no_main_recipe(client, app, make_recipe):
    from models import PlanDay, db

    _make_many_recipes(make_recipe, count=7)
    form = {"day_excluded_0": "1"}
    client.post("/plan/2026-06-15/generate", data=form)

    with app.app_context():
        monday_row = PlanDay.query.filter_by(date=date(2026, 6, 15)).first()
        assert monday_row.excluded is True
        assert monday_row.main_recipe_id is None


def test_week_generate_assigns_fixed_side_dishes(client, app, make_recipe):
    from models import PlanDay, PlanDaySide, db

    _make_many_recipes(make_recipe, count=7)
    side_a = make_recipe("Beilage A", is_side_dish=True)
    side_b = make_recipe("Beilage B", is_side_dish=True)

    form = {"day_side_recipes_0[]": [str(side_a), str(side_b)]}
    client.post("/plan/2026-06-15/generate", data=form)

    with app.app_context():
        monday_row = PlanDay.query.filter_by(date=date(2026, 6, 15)).first()
        side_recipe_ids = {s.recipe_id for s in PlanDaySide.query.filter_by(plan_day_id=monday_row.id).all()}
        assert side_recipe_ids == {side_a, side_b}


def test_week_generate_rerun_replaces_previous_sides(client, app, make_recipe):
    from models import PlanDay, PlanDaySide, db

    _make_many_recipes(make_recipe, count=7)
    side_a = make_recipe("Beilage A", is_side_dish=True)
    side_b = make_recipe("Beilage B", is_side_dish=True)

    client.post("/plan/2026-06-15/generate", data={"day_side_recipes_0[]": [str(side_a)]})
    client.post("/plan/2026-06-15/generate", data={"day_side_recipes_0[]": [str(side_b)]})

    with app.app_context():
        monday_row = PlanDay.query.filter_by(date=date(2026, 6, 15)).first()
        side_recipe_ids = {s.recipe_id for s in PlanDaySide.query.filter_by(plan_day_id=monday_row.id).all()}
        assert side_recipe_ids == {side_b}
