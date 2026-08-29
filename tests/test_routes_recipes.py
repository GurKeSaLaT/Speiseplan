"""Tests für routes/recipes.py: Rezept anlegen/bearbeiten/löschen samt
Zutaten und Saison-Zuordnung, sowie der chefkoch.de-Import-Preview-Endpunkt."""
from unittest.mock import patch

from services.recipe_import import RecipeImportError


def _base_recipe_form(category_id, **overrides):
    # nutrition_override="1" hält bestehende Tests, die feste
    # calories/protein/carbs/fat-Werte erwarten, unabhängig von der
    # automatischen Berechnung aus den Zutaten (siehe
    # services/nutrition.py: compute_recipe_nutrition) - eigene Tests
    # für die Berechnung selbst setzen das Häkchen bewusst NICHT.
    form = {
        "name": "Neues Gericht",
        "category_id": str(category_id),
        "nutrition_override": "1",
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


def test_recipe_create_view_embeds_ingredient_aliases_for_hint_js(client, app):
    from services.ingredient_aliases import set_alias

    with app.app_context():
        set_alias("Olivenöl", "Öl")

    resp = client.get("/manage/recipe/create")
    assert resp.status_code == 200
    assert b"window.INGREDIENT_ALIASES" in resp.data
    # tojson escaped Umlaute als \uXXXX statt roher UTF-8-Bytes (gültiges,
    # vom Browser korrekt interpretiertes JS) - hier also auf die
    # escapte Form prüfen, nicht auf die rohen Zeichen.
    assert b"Oliven\\u00f6l" in resp.data
    assert b'id="canonical-names-datalist"' in resp.data
    # Die Datalist rendert denselben Namen dagegen als normalen HTML-Text
    # (kein JSON), dort also die unescapte Form erwarten.
    assert "Öl".encode("utf-8") in resp.data


def test_recipe_edit_list_view_has_search_filter(client, make_recipe):
    make_recipe("Suchbares Gericht")
    resp = client.get("/manage/recipe/edit-list")
    assert resp.status_code == 200
    assert b'id="recipeFilter"' in resp.data
    assert b"recipe-list-row" in resp.data
    # Muss ueber fuzzy_search.js/wireFuzzyFilter laufen, NICHT ueber
    # element.style.display direkt - siehe static/style.css: .search-hidden-
    # Kommentar (die Zeilen tragen auch Bootstraps !important .d-flex, das
    # einen einfachen Inline-Style sonst stillschweigend ueberstimmt).
    assert b"fuzzy_search.js" in resp.data
    assert b"wireFuzzyFilter" in resp.data
    assert b"row.style.display" not in resp.data


def test_recipe_edit_list_view_no_search_filter_when_empty(client):
    resp = client.get("/manage/recipe/edit-list")
    assert b'id="recipeFilter"' not in resp.data


def test_recipe_edit_list_view_persists_search_across_page_loads(client, make_recipe):
    """Der Bearbeiten-Dialog ist ein normales <form> - ein Speichern lädt
    die Seite über routes/recipes.py: edit_recipe()'s redirect() komplett
    neu, ohne das würde ein eingetippter Suchbegriff dabei verloren gehen.
    sessionStorage merkt ihn sich stattdessen über den Seitenaufruf hinweg."""
    make_recipe("Suchbares Gericht")
    resp = client.get("/manage/recipe/edit-list")
    assert resp.status_code == 200
    assert b"sessionStorage" in resp.data
    assert b"speiseplan.recipeEditFilter" in resp.data


def test_recipe_edit_list_view_search_data_includes_category(client, make_category, make_recipe):
    cat_id = make_category("Beilagen")
    make_recipe("Kartoffelpüree", category_id=cat_id)

    resp = client.get("/manage/recipe/edit-list")
    assert resp.status_code == 200
    # data-search muss die Kategorie mit enthalten, damit eine Suche nach
    # "Beilagen" auch Rezepte findet, deren NAME selbst nicht "Beilagen"
    # enthält (siehe static/fuzzy_search.js: wireFuzzyFilter).
    assert b'data-search="kartoffelp\xc3\xbcree beilagen"' in resp.data


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


# --- Automatische Nährwert-Berechnung aus den Zutaten (services/nutrition.py) ---

def test_add_recipe_computes_nutrition_from_ingredients(client, app, make_category):
    from models import Recipe
    from services.nutrition import set_nutrition

    cat_id = make_category("Berechnet")
    with app.app_context():
        # 350 kcal/100g Mehl.
        set_nutrition("Mehl", reference_unit="g", calories=350, protein=10, carbs=70, fat=1)

    form = _base_recipe_form(cat_id, servings="2", **{
        "nutrition_override": "",
        "ing_name[]": ["Mehl", ""],
        "ing_amount[]": ["200", ""],
        "ing_unit[]": ["g", ""],
        "ing_category[]": ["", ""],
    })
    client.post("/add-recipe", data=form, follow_redirects=True)

    with app.app_context():
        recipe = Recipe.query.filter_by(name="Neues Gericht").first()
        assert recipe.nutrition_override is False
        # 200g Mehl @350kcal/100g = 700 kcal insgesamt, geteilt durch 2
        # Portionen = 350 kcal/Portion (siehe Docstring von
        # compute_recipe_nutrition: Ingredient.amount gilt für den ganzen
        # Rezept-Batch, Recipe.calories je Portion).
        assert recipe.calories == 350
        assert recipe.protein == 10.0
        assert recipe.carbs == 70.0
        assert recipe.fat == 1.0


def test_add_recipe_without_nutrition_data_computes_zero(client, app, make_category):
    from models import Recipe

    cat_id = make_category("Ohne Nährwerte")
    form = _base_recipe_form(cat_id, **{"nutrition_override": ""})
    client.post("/add-recipe", data=form, follow_redirects=True)

    with app.app_context():
        recipe = Recipe.query.filter_by(name="Neues Gericht").first()
        # "Nudeln" hat in dieser isolierten Testdatenbank keinen
        # IngredientNutrition-Eintrag - compute_recipe_nutrition()
        # überspringt die Zutat statt zu raten oder zu fehlern.
        assert recipe.calories == 0
        assert recipe.protein == 0.0


def test_add_recipe_override_ignores_computed_nutrition(client, app, make_category):
    from models import Recipe
    from services.nutrition import set_nutrition

    cat_id = make_category("Überschrieben")
    with app.app_context():
        set_nutrition("Nudeln", reference_unit="g", calories=999, protein=1, carbs=1, fat=1)

    # _base_recipe_form() setzt nutrition_override="1" und feste
    # calories="400" etc. per Default - diese müssen trotz vorhandener
    # IngredientNutrition-Daten für "Nudeln" unverändert übernommen werden.
    form = _base_recipe_form(cat_id)
    client.post("/add-recipe", data=form, follow_redirects=True)

    with app.app_context():
        recipe = Recipe.query.filter_by(name="Neues Gericht").first()
        assert recipe.nutrition_override is True
        assert recipe.calories == 400


def test_edit_recipe_recomputes_nutrition_when_ingredients_change(client, app, make_recipe):
    from models import Recipe, db
    from services.nutrition import set_nutrition

    recipe_id = make_recipe("Neu berechnen", ingredients=[{"name": "Alt", "amount": 1, "unit": "Stk"}])
    with app.app_context():
        cat_id = db.session.get(Recipe, recipe_id).category_id
        set_nutrition("Reis", reference_unit="g", calories=130, protein=3, carbs=28, fat=0.3)

    form = _base_recipe_form(cat_id, servings="1", **{
        "nutrition_override": "",
        "ing_name[]": ["Reis"], "ing_amount[]": ["200"], "ing_unit[]": ["g"], "ing_category[]": [""],
    })
    client.post(f"/edit-recipe/{recipe_id}", data=form, follow_redirects=True)

    with app.app_context():
        recipe = db.session.get(Recipe, recipe_id)
        assert recipe.nutrition_override is False
        # 200g Reis @130kcal/100g = 260 kcal, 1 Portion.
        assert recipe.calories == 260
        assert recipe.carbs == 56.0


def test_edit_recipe_keeps_manual_nutrition_when_override_set(client, app, make_recipe):
    from models import Recipe, db

    recipe_id = make_recipe("Manuell bleibt")
    with app.app_context():
        cat_id = db.session.get(Recipe, recipe_id).category_id

    form = _base_recipe_form(cat_id, **{
        "nutrition_override": "1", "calories": "777", "protein": "77", "carbs": "7", "fat": "7",
        "ing_name[]": [""], "ing_amount[]": [""], "ing_unit[]": [""], "ing_category[]": [""],
    })
    client.post(f"/edit-recipe/{recipe_id}", data=form, follow_redirects=True)

    with app.app_context():
        recipe = db.session.get(Recipe, recipe_id)
        assert recipe.nutrition_override is True
        assert recipe.calories == 777


def test_recipe_create_view_embeds_ingredient_nutrition_for_hint_js(client, app):
    from services.nutrition import set_nutrition

    with app.app_context():
        set_nutrition("Öl", reference_unit="ml", calories=884, protein=0, carbs=0, fat=100)

    resp = client.get("/manage/recipe/create")
    assert resp.status_code == 200
    assert b"window.INGREDIENT_NUTRITION" in resp.data
    assert b'"calories": 884' in resp.data or b'"calories":884' in resp.data


def test_recipe_create_view_nutrition_inputs_disabled_by_default(client):
    resp = client.get("/manage/recipe/create")
    assert b'name="nutritionOverride"' not in resp.data  # id, nicht name
    assert b'id="nutritionOverride"' in resp.data
    assert b'name="calories" class="form-control" disabled' in resp.data


def test_recipe_edit_list_view_prefills_override_checkbox(client, make_recipe):
    recipe_id = make_recipe("Übersteuert", nutrition_override=True, calories=555)
    resp = client.get("/manage/recipe/edit-list")
    assert resp.status_code == 200
    assert f'id="nutritionOverride{recipe_id}"'.encode() in resp.data
    assert b'value="555"' in resp.data
    # Bei bereits gesetztem Override-Häkchen duerfen die Felder NICHT
    # deaktiviert sein (der Nutzer soll seine manuellen Werte direkt
    # weiter bearbeiten koennen) - das Checkbox-Input selbst muss "checked"
    # tragen (Attribut-Reihenfolge im Template ist ein Detail, daher hier
    # nur auf Vorhandensein prüfen statt exakter Attribut-Reihenfolge).
    assert b"checked" in resp.data.split(f'id="nutritionOverride{recipe_id}"'.encode())[1][:80]
