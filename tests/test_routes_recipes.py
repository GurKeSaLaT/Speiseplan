"""Tests for routes/recipes.py: create/edit/delete recipe including
ingredients and season assignment, plus the chefkoch.de import preview endpoint."""
from pathlib import Path
from unittest.mock import patch

from services.recipe_import import RecipeImportError

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


def _base_recipe_form(category_id, **overrides):
    # nutrition_override="1" keeps existing tests that expect fixed
    # protein/carbs/fat values, independent of automatic
    # computation from the ingredients (see services/nutrition.py:
    # compute_recipe_nutrition) - tests for the computation itself
    # deliberately do NOT set this checkbox. calories is deliberately
    # not a form field here - it's never taken from the form,
    # but always computed from protein/carbs/fat (services/nutrition.py:
    # compute_calories(), so here 290 = (20+30)*4 + 10*9).
    form = {
        "name": "Neues Gericht",
        "category_id": str(category_id),
        "nutrition_override": "1",
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
        set_alias(client.plan_id, "Olivenöl", "Öl")

    resp = client.get("/manage/recipe/create")
    assert resp.status_code == 200
    assert b"window.INGREDIENT_ALIASES" in resp.data
    # tojson escapes umlauts as \uXXXX instead of raw UTF-8 bytes (valid
    # JS the browser interprets correctly) - so check for the
    # escaped form here, not the raw characters.
    assert b"Oliven\\u00f6l" in resp.data
    assert b'id="canonical-names-datalist"' in resp.data
    # The datalist, by contrast, renders the same name as plain HTML text
    # (no JSON), so expect the unescaped form there.
    assert "Öl".encode("utf-8") in resp.data


def test_recipe_create_view_ingredient_row_has_delete_button(client):
    """Every ingredient row (including the empty starting row) needs a
    small delete button that removes the whole .ingredient-row - both
    server-rendered and in the rformAddIngredientRow() JS template
    in static/recipe_form.js, which builds rows added later."""
    resp = client.get("/manage/recipe/create")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert 'class="ingredient-row' in html  # server-rendered
    assert "this.closest('.ingredient-row').remove()" in html

    js = (STATIC_DIR / "recipe_form.js").read_text(encoding="utf-8")
    assert "div.className = 'ingredient-row'" in js  # rformAddIngredientRow() JS template
    assert "this.closest('.ingredient-row').remove()" in js


def test_recipe_create_view_alias_hint_spans_full_ingredient_row(client):
    """The alias/nutrition hint must no longer be embedded in the narrow
    name column (that made the inline nutrition input there unusably
    narrow), but must appear AFTER the complete field row (including the
    delete button on the far right) as its own element - i.e. it must
    appear after the marker for the last column in the HTML source, not
    right behind the name field."""
    resp = client.get("/manage/recipe/create")
    html = resp.get_data(as_text=True)
    name_field_index = html.index('name="ing_name[]"')
    delete_btn_index = html.index("this.closest('.ingredient-row').remove()")
    hint_index = html.index('class="ingredient-alias-hint')
    assert name_field_index < delete_btn_index < hint_index


def test_recipe_edit_list_view_has_search_filter(client, make_recipe):
    make_recipe("Suchbares Gericht")
    resp = client.get("/manage/recipe/edit-list")
    assert resp.status_code == 200
    assert b'id="recipeFilter"' in resp.data
    assert b"recipe-list-row" in resp.data
    # Must run via fuzzy_search.js/wireFuzzyFilter, NOT via
    # element.style.display directly - see static/style.css: the
    # .search-hidden comment (the rows also carry Bootstrap's !important
    # .d-flex, which would otherwise silently override a simple inline style).
    assert b"fuzzy_search.js" in resp.data
    assert b"wireFuzzyFilter" in resp.data
    assert b"row.style.display" not in resp.data


def test_recipe_edit_list_view_no_search_filter_when_empty(client):
    resp = client.get("/manage/recipe/edit-list")
    assert b'id="recipeFilter"' not in resp.data


def test_recipe_edit_view_ingredient_row_has_delete_button(client, make_recipe):
    """Like test_recipe_create_view_ingredient_row_has_delete_button, but
    for a recipe's edit page: both the existing ingredient rows and the
    empty starting row need the delete button. Uses the same
    recipe_form.html/recipe_form.js as the create page (see
    routes/recipes.py: recipe_edit_view)."""
    recipe_id = make_recipe("Gericht mit Zutat", ingredients=[{"name": "Mehl", "amount": 100, "unit": "g"}])
    resp = client.get(f"/manage/recipe/edit/{recipe_id}")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert html.count('class="ingredient-row') >= 2  # existing ingredient + empty row
    assert "this.closest('.ingredient-row').remove()" in html


def test_recipe_edit_view_unknown_id_returns_404(client):
    resp = client.get("/manage/recipe/edit/999999")
    assert resp.status_code == 404


def test_recipe_edit_list_view_links_to_dedicated_edit_page(client, make_recipe):
    """Since the form rework, the "Edit" button links to a dedicated page
    per recipe (routes/recipes.py: recipe_edit_view,
    /manage/recipe/edit/<id>) instead of opening a modal via JS - previously
    there was a shared, JS-populated modal for this (see the now-removed
    static/recipe_edit_modal.js)."""
    recipe_id = make_recipe("Irgendein Gericht")
    resp = client.get("/manage/recipe/edit-list")
    assert resp.status_code == 200
    # Since the tab switcher (see routes/recipes.py:
    # recipe_edit_list_view), also carries ?plan_id=<id> - "in" instead of
    # "ends with" still checks the same target without depending on the
    # exact query-string form.
    assert f'href="/manage/recipe/edit/{recipe_id}?plan_id='.encode() in resp.data


def test_recipe_edit_list_view_persists_search_across_page_loads(client, make_recipe):
    """The edit dialog is a normal <form> - saving fully reloads the page
    via routes/recipes.py: edit_recipe()'s redirect(); without this, a
    typed search term would get lost. sessionStorage remembers it across
    the page load instead."""
    make_recipe("Suchbares Gericht")
    resp = client.get("/manage/recipe/edit-list")
    assert resp.status_code == 200
    assert b"sessionStorage" in resp.data
    assert b"speiseplan.recipeEditFilter" in resp.data


def test_recipe_detail_edit_link_points_to_dedicated_edit_page():
    """Since the form rework, the "✏️ Edit recipe" button in the detail
    popup on the plan page (see templates/plan.html) links directly to a
    recipe's own edit page (routes/recipes.py: recipe_edit_view) instead of,
    as before, /manage/recipe/edit-list?edit=<id> (the modal auto-start
    mechanism there no longer exists since static/recipe_edit_modal.js was
    removed)."""
    content = (STATIC_DIR / "plan.js").read_text(encoding="utf-8")
    assert "`/manage/recipe/edit/${recipe.id}`" in content
    assert "edit-list?edit=" not in content


def test_recipe_edit_list_view_search_data_includes_category(client, make_category, make_recipe):
    cat_id = make_category("Beilagen")
    make_recipe("Kartoffelpüree", category_id=cat_id)

    resp = client.get("/manage/recipe/edit-list")
    assert resp.status_code == 200
    # data-search must include the category so that a search for
    # "Beilagen" also finds recipes whose NAME itself doesn't contain
    # "Beilagen" (see static/fuzzy_search.js: wireFuzzyFilter).
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
        assert recipe.calories == 290  # (20+30)*4 + 10*9, see _base_recipe_form()
        assert recipe.servings == 2
        # The empty second ing_name[] row is skipped, only one ingredient remains.
        assert len(recipe.ingredients) == 1
        assert recipe.ingredients[0].name == "Nudeln"
        assert len(recipe.seasons) == 1


def test_recipe_create_view_hides_plan_selector_with_single_plan(client):
    resp = client.get("/manage/recipe/create")
    assert resp.status_code == 200
    assert b'name="plan_id"' in resp.data  # still present as a hidden field
    assert b'<select name="plan_id"' not in resp.data


def test_recipe_create_view_shows_plan_selector_with_starred_preselected(app, client, make_user):
    from models import PlanMembership, db

    other_plan_id = make_user("Zweitplan-Besitzer")[1]
    with app.app_context():
        db.session.add(PlanMembership(plan_id=other_plan_id, user_id=client.user_id, is_starred=False))
        db.session.commit()

    resp = client.get("/manage/recipe/create")
    assert resp.status_code == 200
    assert b'<select name="plan_id"' in resp.data
    # The starred (own) plan is preselected, the other one is not.
    assert f'value="{client.plan_id}" selected'.encode() in resp.data
    assert f'value="{other_plan_id}" selected'.encode() not in resp.data


def test_add_recipe_without_explicit_plan_id_defaults_to_starred_plan(app, client, make_user, make_category):
    """default_plan_id() (services/auth.py) falls back to the starred
    plan WITHOUT ?plan_id=, NOT to current_plan() - additionally tested
    here with a second, non-starred own plan whose mere existence must not
    change the default selection."""
    from models import PlanMembership, Recipe, db

    other_plan_id = make_user("Zweitplan-Besitzer")[1]
    with app.app_context():
        db.session.add(PlanMembership(plan_id=other_plan_id, user_id=client.user_id, is_starred=False))
        db.session.commit()

    cat_id = make_category("Hauptgerichte")
    form = _base_recipe_form(cat_id)
    client.post("/add-recipe", data=form)

    with app.app_context():
        recipe = Recipe.query.filter_by(name="Neues Gericht").first()
        assert recipe.owner_plan_id == client.plan_id


def test_add_recipe_respects_explicit_plan_id_from_selector(app, client, make_user, make_category):
    from models import PlanMembership, Recipe, db

    other_plan_id = make_user("Zweitplan-Besitzer")[1]
    with app.app_context():
        db.session.add(PlanMembership(plan_id=other_plan_id, user_id=client.user_id, is_starred=False))
        db.session.commit()

    cat_id = make_category("Hauptgerichte", plan_id=other_plan_id)
    form = _base_recipe_form(cat_id, plan_id=str(other_plan_id))
    client.post("/add-recipe", data=form)

    with app.app_context():
        recipe = Recipe.query.filter_by(name="Neues Gericht").first()
        assert recipe.owner_plan_id == other_plan_id


def test_add_recipe_sets_updated_at(client, app, make_category):
    """For the "recently edited" list on /manage (routes/manage.py) -
    Recipe.updated_at is set on creation via the column default (see
    models/recipe.py), without add_recipe() having to maintain it itself."""
    from models import Recipe

    cat_id = make_category("Frisch")
    form = _base_recipe_form(cat_id)
    client.post("/add-recipe", data=form, follow_redirects=True)

    with app.app_context():
        recipe = Recipe.query.filter_by(name="Neues Gericht").first()
        assert recipe.updated_at is not None


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
        # "1 kg" -> canonical 1000 g, "2 EL" -> canonical 30 ml.
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


def test_edit_recipe_bumps_updated_at(client, app, make_recipe):
    """edit_recipe() explicitly sets Recipe.updated_at on EVERY save
    (see the comment there - an onupdate=... on the column would only
    trigger if a value actually changes)."""
    from datetime import datetime, timedelta, timezone
    from models import Recipe, db

    recipe_id = make_recipe("Alt")
    with app.app_context():
        recipe = db.session.get(Recipe, recipe_id)
        cat_id = recipe.category_id
        recipe.updated_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=5)
        db.session.commit()
        old_updated_at = recipe.updated_at

    form = _base_recipe_form(cat_id, name="Alt", **{
        "ing_name[]": [""], "ing_amount[]": [""], "ing_unit[]": [""], "ing_category[]": [""],
    })
    client.post(f"/edit-recipe/{recipe_id}", data=form, follow_redirects=True)

    with app.app_context():
        recipe = db.session.get(Recipe, recipe_id)
        assert recipe.updated_at > old_updated_at


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


def test_recipe_edit_view_shows_ingredients_in_display_unit(client, app, make_recipe):
    from services.settings import update_display_units

    recipe_id = make_recipe(
        "Kilo-Anzeige", ingredients=[{"name": "Zucker", "amount": 1500, "unit": "g"}]
    )
    with app.app_context():
        update_display_units(client.plan_id, "kg", "ml")

    resp = client.get(f"/manage/recipe/edit/{recipe_id}")
    assert resp.status_code == 200
    assert b'value="1.5"' in resp.data
    assert b'value="kg"' in resp.data


def test_recipe_edit_view_shows_alias_name_as_display_text(client, app, make_recipe):
    """An ingredient row with an alias set shows the resolved canonical
    name (.ing-name-display) by default, NOT the name actually stored
    for this recipe - that stays untouched in the (hidden) real form
    field, so that saving without deliberate editing doesn't silently
    replace the original name with the alias (see
    static/ingredient_alias_hint.js: openIngredientNameField)."""
    from services.ingredient_aliases import set_alias

    recipe_id = make_recipe("Pasta-Gericht", ingredients=[{"name": "Fusilli", "amount": 400, "unit": "g"}])
    with app.app_context():
        set_alias(client.plan_id, "Fusilli", "Nudeln")

    resp = client.get(f"/manage/recipe/edit/{recipe_id}")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert 'class="ing-name-display" tabindex="0" role="button" title="Click to edit">Nudeln</span>' in html
    # The actual, editable field keeps the real stored name.
    assert 'class="ing-name-input d-none" value="Fusilli"' in html


def test_recipe_edit_view_shows_own_name_when_no_alias(client, make_recipe):
    recipe_id = make_recipe("Solo-Gericht", ingredients=[{"name": "Radicchio", "amount": 1, "unit": "Stk"}])

    resp = client.get(f"/manage/recipe/edit/{recipe_id}")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert 'ing-name-display" tabindex="0" role="button" title="Click to edit">Radicchio</span>' in html


def test_recipe_edit_view_has_editable_name_wiring_script(client, make_recipe):
    """static/ingredient_alias_hint.js must be included - it contains
    both the click-to-edit behavior and the initial loading of the
    alias/nutrition hint for already-filled-in ingredient rows (see the
    comments there)."""
    recipe_id = make_recipe("Irgendein Gericht", ingredients=[{"name": "Reis", "amount": 200, "unit": "g"}])
    resp = client.get(f"/manage/recipe/edit/{recipe_id}")
    assert resp.status_code == 200
    assert b"ingredient_alias_hint.js" in resp.data
    assert b"recipe_form.js" in resp.data


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
        update_display_units(client.plan_id, "kg", "l")

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


# --- Automatic nutrition computation from ingredients (services/nutrition.py) ---

def test_add_recipe_computes_nutrition_from_ingredients(client, app, make_category):
    from models import Recipe
    from services.nutrition import set_nutrition

    cat_id = make_category("Berechnet")
    with app.app_context():
        # 10g protein/70g carbs/1g fat per 100g flour.
        set_nutrition(client.plan_id, "Mehl", reference_unit="g", protein=10, carbs=70, fat=1)

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
        # 200g flour @(10/70/1 per 100g) / 2 servings = 10/70/1 per serving
        # (see compute_recipe_nutrition's docstring: Ingredient.amount
        # applies to the whole recipe batch, Recipe.calories per serving).
        # calories computed from that (Atwater): (10+70)*4 + 1*9 = 329.
        assert recipe.calories == 329
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
        # "Nudeln" has no IngredientNutrition entry in this isolated test
        # database - compute_recipe_nutrition() skips the ingredient
        # instead of guessing or erroring.
        assert recipe.calories == 0
        assert recipe.protein == 0.0


def test_add_recipe_override_ignores_computed_nutrition(client, app, make_category):
    from models import Recipe
    from services.nutrition import set_nutrition

    cat_id = make_category("Überschrieben")
    with app.app_context():
        set_nutrition(client.plan_id, "Nudeln", reference_unit="g", protein=1, carbs=1, fat=1)

    # _base_recipe_form() sets nutrition_override="1" and fixed
    # protein/carbs/fat values by default - these must be taken over
    # unchanged despite existing IngredientNutrition data for "Nudeln"
    # (and calories computed from those, not from the IngredientNutrition
    # data for "Nudeln" - 290 = (20+30)*4 + 10*9, see _base_recipe_form()).
    form = _base_recipe_form(cat_id)
    client.post("/add-recipe", data=form, follow_redirects=True)

    with app.app_context():
        recipe = Recipe.query.filter_by(name="Neues Gericht").first()
        assert recipe.nutrition_override is True
        assert recipe.calories == 290


def test_edit_recipe_recomputes_nutrition_when_ingredients_change(client, app, make_recipe):
    from models import Recipe, db
    from services.nutrition import set_nutrition

    recipe_id = make_recipe("Neu berechnen", ingredients=[{"name": "Alt", "amount": 1, "unit": "Stk"}])
    with app.app_context():
        cat_id = db.session.get(Recipe, recipe_id).category_id
        set_nutrition(client.plan_id, "Reis", reference_unit="g", protein=3, carbs=28, fat=0.3)

    form = _base_recipe_form(cat_id, servings="1", **{
        "nutrition_override": "",
        "ing_name[]": ["Reis"], "ing_amount[]": ["200"], "ing_unit[]": ["g"], "ing_category[]": [""],
    })
    client.post(f"/edit-recipe/{recipe_id}", data=form, follow_redirects=True)

    with app.app_context():
        recipe = db.session.get(Recipe, recipe_id)
        assert recipe.nutrition_override is False
        # 200g rice @(3/28/0.3 per 100g), 1 serving -> 6/56/0.6.
        # calories computed from that: (6+56)*4 + 0.6*9 = 253.
        assert recipe.calories == 253
        assert recipe.carbs == 56.0


def test_edit_recipe_keeps_manual_nutrition_when_override_set(client, app, make_recipe):
    from models import Recipe, db

    recipe_id = make_recipe("Manuell bleibt")
    with app.app_context():
        cat_id = db.session.get(Recipe, recipe_id).category_id

    form = _base_recipe_form(cat_id, **{
        "nutrition_override": "1", "protein": "77", "carbs": "7", "fat": "7",
        "ing_name[]": [""], "ing_amount[]": [""], "ing_unit[]": [""], "ing_category[]": [""],
    })
    client.post(f"/edit-recipe/{recipe_id}", data=form, follow_redirects=True)

    with app.app_context():
        recipe = db.session.get(Recipe, recipe_id)
        assert recipe.nutrition_override is True
        # calories is NEVER taken from the form, not even in the
        # override case - computed from protein/carbs/fat:
        # (77+7)*4 + 7*9 = 399.
        assert recipe.calories == 399


def test_recipe_create_view_embeds_ingredient_nutrition_for_hint_js(client, app):
    from services.nutrition import set_nutrition

    with app.app_context():
        set_nutrition(client.plan_id, "Öl", reference_unit="ml", protein=0, carbs=0, fat=100)

    resp = client.get("/manage/recipe/create")
    assert resp.status_code == 200
    assert b"window.INGREDIENT_NUTRITION" in resp.data
    # calories is not a stored value here, but is computed for embedding
    # from protein/carbs/fat: 100g fat * 9 kcal/g = 900.
    assert b'"calories": 900' in resp.data or b'"calories":900' in resp.data


def test_recipe_create_view_nutrition_inputs_disabled_by_default(client):
    resp = client.get("/manage/recipe/create")
    assert b'name="nutritionOverride"' not in resp.data  # id, not name
    assert b'id="nutritionOverride"' in resp.data
    # Kcal deliberately has NO name attribute (never submitted, see
    # services/nutrition.py: compute_calories()) - only the display
    # is always disabled.
    assert b'id="caloriesDisplay" class="rform-field" disabled' in resp.data
    assert b'name="protein" id="proteinInput" class="rform-field" disabled' in resp.data


def test_recipe_edit_view_prefills_override_checkbox(client, make_recipe):
    recipe_id = make_recipe("Übersteuert", nutrition_override=True, calories=555)
    resp = client.get(f"/manage/recipe/edit/{recipe_id}")
    assert resp.status_code == 200
    assert b'id="nutritionOverride"' in resp.data
    assert b'value="555"' in resp.data
    # When the override checkbox is already set, the fields must NOT
    # be disabled (the user should be able to keep editing their manual
    # values directly) - the checkbox input itself must carry "checked"
    # (attribute order in the template is a detail, so just check
    # presence here rather than exact attribute order).
    assert b"checked" in resp.data.split(b'id="nutritionOverride"')[1][:80]
