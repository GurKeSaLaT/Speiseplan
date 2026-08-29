"""Tests für routes/recipes.py: Rezept anlegen/bearbeiten/löschen samt
Zutaten und Saison-Zuordnung, sowie der chefkoch.de-Import-Preview-Endpunkt."""
from unittest.mock import patch

from services.recipe_import import RecipeImportError


def _base_recipe_form(category_id, **overrides):
    form = {
        "name": "Neues Gericht",
        "category_id": str(category_id),
        "calories": "400",
        "protein": "20",
        "carbs": "30",
        "fat": "10",
        "servings": "2",
        "ing_name[]": ["Nudeln", ""],
        "ing_amount[]": ["500", ""],
        "ing_unit[]": ["g", ""],
        "ing_category[]": ["Teigwaren", ""],
    }
    form.update(overrides)
    return form


def test_recipe_create_view_lists_categories_and_ingredients(client, make_category, make_recipe):
    make_category("Vegetarisch")
    make_recipe("Bekanntes Gericht", ingredients=[{"name": "Tomaten", "amount": 3, "unit": "Stk"}])

    resp = client.get("/manage/recipe/create")
    assert resp.status_code == 200
    assert b"Vegetarisch" in resp.data
    assert b"Tomaten" in resp.data


def test_recipe_edit_list_view_shows_season_badges(client, app, make_recipe):
    from models import RecipeSeason, db
    from services.seasons import SEASON_PRESETS

    recipe_id = make_recipe("Sommergericht")
    with app.app_context():
        db.session.add(RecipeSeason(recipe_id=recipe_id, start_month=SEASON_PRESETS["Sommer"][0],
                                     start_day=SEASON_PRESETS["Sommer"][1],
                                     end_month=SEASON_PRESETS["Sommer"][2],
                                     end_day=SEASON_PRESETS["Sommer"][3]))
        db.session.commit()

    resp = client.get("/manage/recipe/edit-list")
    assert resp.status_code == 200
    assert b"Sommergericht" in resp.data


def test_add_recipe_creates_recipe_with_ingredients_and_seasons(client, app, make_category):
    from models import Recipe

    cat_id = make_category("Hauptgerichte")
    form = _base_recipe_form(cat_id, seasons=["Sommer"])

    resp = client.post("/add-recipe", data=form, follow_redirects=True)
    assert resp.status_code == 200

    with app.app_context():
        recipe = Recipe.query.filter_by(name="Neues Gericht").first()
        assert recipe is not None
        assert recipe.calories == 400
        assert recipe.servings == 2
        # Die leere zweite ing_name[]-Zeile wird übersprungen, nur eine Zutat bleibt.
        assert len(recipe.ingredients) == 1
        assert recipe.ingredients[0].name == "Nudeln"
        assert len(recipe.seasons) == 1


def test_add_recipe_side_dish_and_favorite_flags(client, app, make_category):
    from models import Recipe

    cat_id = make_category("Beilagen")
    form = _base_recipe_form(cat_id, is_side_dish="1", is_favorite="1")

    client.post("/add-recipe", data=form, follow_redirects=True)
    with app.app_context():
        recipe = Recipe.query.filter_by(name="Neues Gericht").first()
        assert recipe.is_side_dish is True
        assert recipe.is_favorite is True


def test_add_recipe_normalizes_ingredient_units(client, app, make_category):
    from models import Recipe

    cat_id = make_category("Normalisierung")
    form = _base_recipe_form(cat_id, **{
        "ing_name[]": ["Mehl", "Öl", ""],
        "ing_amount[]": ["1", "2", ""],
        "ing_unit[]": ["kg", "EL", ""],
        "ing_category[]": ["", "", ""],
    })

    client.post("/add-recipe", data=form, follow_redirects=True)
    with app.app_context():
        recipe = Recipe.query.filter_by(name="Neues Gericht").first()
        by_name = {i.name: (i.amount, i.unit) for i in recipe.ingredients}
        # "1 kg" -> kanonisch 1000 g, "2 EL" -> kanonisch 30 ml.
        assert by_name["Mehl"] == (1000, "g")
        assert by_name["Öl"] == (30, "ml")


def test_edit_recipe_replaces_ingredients_and_fields(client, app, make_recipe):
    from models import Recipe, db

    recipe_id = make_recipe("Altes Gericht", ingredients=[{"name": "Alt", "amount": 1, "unit": "Stk"}])
    with app.app_context():
        cat_id = db.session.get(Recipe, recipe_id).category_id

    form = _base_recipe_form(cat_id, name="Geändertes Gericht", **{
        "ing_name[]": ["Neu"], "ing_amount[]": ["2"], "ing_unit[]": ["Stk"], "ing_category[]": [""],
    })

    resp = client.post(f"/edit-recipe/{recipe_id}", data=form, follow_redirects=True)
    assert resp.status_code == 200

    with app.app_context():
        recipe = db.session.get(Recipe, recipe_id)
        assert recipe.name == "Geändertes Gericht"
        assert [i.name for i in recipe.ingredients] == ["Neu"]


def test_edit_recipe_normalizes_ingredient_units(client, app, make_recipe):
    from models import Recipe, db

    recipe_id = make_recipe("Mengenänderung")
    with app.app_context():
        cat_id = db.session.get(Recipe, recipe_id).category_id

    form = _base_recipe_form(cat_id, **{
        "ing_name[]": ["Milch"], "ing_amount[]": ["1"], "ing_unit[]": ["Liter"], "ing_category[]": [""],
    })
    client.post(f"/edit-recipe/{recipe_id}", data=form, follow_redirects=True)

    with app.app_context():
        recipe = db.session.get(Recipe, recipe_id)
        assert (recipe.ingredients[0].amount, recipe.ingredients[0].unit) == (1000, "ml")


def test_recipe_edit_list_view_shows_ingredients_in_display_unit(client, app, make_recipe):
    from services.settings import update_display_units

    recipe_id = make_recipe(
        "Kilo-Anzeige", ingredients=[{"name": "Zucker", "amount": 1500, "unit": "g"}]
    )
    with app.app_context():
        update_display_units("kg", "ml")

    resp = client.get("/manage/recipe/edit-list")
    assert resp.status_code == 200
    assert b'value="1.5"' in resp.data
    assert b'value="kg"' in resp.data


def test_edit_recipe_unknown_id_returns_404(client, make_category):
    cat_id = make_category()
    resp = client.post(f"/edit-recipe/999999", data=_base_recipe_form(cat_id))
    assert resp.status_code == 404


def test_delete_recipe_removes_it(client, app, make_recipe):
    from models import Recipe, db

    recipe_id = make_recipe("Zu löschen")
    resp = client.post(f"/delete-recipe/{recipe_id}", follow_redirects=True)
    assert resp.status_code == 200
    with app.app_context():
        assert db.session.get(Recipe, recipe_id) is None


def test_delete_recipe_unknown_id_returns_404(client):
    resp = client.post("/delete-recipe/999999")
    assert resp.status_code == 404


@patch("routes.recipes.fetch_recipe_from_url")
def test_import_recipe_preview_success(mock_fetch, client):
    mock_fetch.return_value = {"name": "Importiert", "servings": 4, "ingredients": []}
    resp = client.post("/manage/recipe/import-preview", json={"url": "https://chefkoch.de/x"})
    assert resp.status_code == 200
    assert resp.get_json()["name"] == "Importiert"


def test_import_recipe_preview_missing_url(client):
    resp = client.post("/manage/recipe/import-preview", json={})
    assert resp.status_code == 400
    assert "error" in resp.get_json()


@patch("routes.recipes.fetch_recipe_from_url")
def test_import_recipe_preview_propagates_import_error(mock_fetch, client):
    mock_fetch.side_effect = RecipeImportError("Nicht unterstützt.")
    resp = client.post("/manage/recipe/import-preview", json={"url": "https://example.com/x"})
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "Nicht unterstützt."


@patch("routes.recipes.fetch_recipe_from_url")
def test_import_recipe_preview_converts_ingredients_to_display_unit(mock_fetch, client, app):
    from services.settings import update_display_units

    with app.app_context():
        update_display_units("kg", "l")

    mock_fetch.return_value = {
        "name": "Importiert", "servings": 4,
        "ingredients": [{"name": "Mehl", "amount": 1000, "unit": "g"}, {"name": "Milch", "amount": 500, "unit": "ml"}],
    }
    resp = client.post("/manage/recipe/import-preview", json={"url": "https://chefkoch.de/x"})
    assert resp.status_code == 200
    ingredients = resp.get_json()["ingredients"]
    assert ingredients == [
        {"name": "Mehl", "amount": 1, "unit": "kg"},
        {"name": "Milch", "amount": 0.5, "unit": "l"},
    ]
