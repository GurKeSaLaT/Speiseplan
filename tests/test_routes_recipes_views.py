"""Recipe pages: create form, edit form and the recipe list."""
from pathlib import Path

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


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
    # tojson escapes umlauts as \uXXXX; the datalist below renders them raw.
    assert b"Oliven\\u00f6l" in resp.data
    assert b'id="canonical-names-datalist"' in resp.data
    assert "Öl".encode("utf-8") in resp.data


def test_recipe_create_view_ingredient_row_has_delete_button(client):
    """Both server-rendered rows and rows added by recipe_form.js need it."""
    resp = client.get("/manage/recipe/create")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert 'class="ingredient-row' in html  # server-rendered
    assert "this.closest('.ingredient-row').remove()" in html

    js = (STATIC_DIR / "recipe_form.js").read_text(encoding="utf-8")
    assert "div.className = 'ingredient-row'" in js  # rformAddIngredientRow() JS template
    assert "this.closest('.ingredient-row').remove()" in js


def test_recipe_create_view_alias_hint_spans_full_ingredient_row(client):
    """The hint comes after the whole field row, not inside the narrow name
    column (where its inline inputs were unusably narrow)."""
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
    # Must use the .search-hidden class: an inline display style would lose
    # against Bootstrap's !important .d-flex on the rows.
    assert b"fuzzy_search.js" in resp.data
    assert b"wireFuzzyFilter" in resp.data
    assert b"row.style.display" not in resp.data


def test_recipe_edit_list_view_no_search_filter_when_empty(client):
    resp = client.get("/manage/recipe/edit-list")
    assert b'id="recipeFilter"' not in resp.data


def test_recipe_edit_view_ingredient_row_has_delete_button(client, make_recipe):
    recipe_id = make_recipe("Gericht mit Zutat", ingredients=[{"name": "Mehl", "amount": 100, "unit": "g"}])
    resp = client.get(f"/manage/recipe/edit/{recipe_id}")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert html.count('class="ingredient-row') >= 2  # existing ingredient + empty row
    assert "this.closest('.ingredient-row').remove()" in html


def test_recipe_edit_view_has_no_save_button(client, make_recipe):
    """Existing recipes autosave; only a status indicator is shown."""
    recipe_id = make_recipe("Bekanntes Gericht")
    resp = client.get(f"/manage/recipe/edit/{recipe_id}")
    assert resp.status_code == 200
    assert b'id="recipeAutosaveIndicator"' in resp.data
    assert b"Save changes" not in resp.data
    assert b"Save recipe" not in resp.data
    assert f'window.RECIPE_ID = {recipe_id};'.encode() in resp.data


def test_recipe_create_view_has_save_button_not_autosave(client):
    """A new recipe has no id to autosave into; one click creates it."""
    resp = client.get("/manage/recipe/create")
    assert resp.status_code == 200
    assert b"Save recipe" in resp.data
    assert b'id="recipeAutosaveIndicator"' not in resp.data
    assert b"window.RECIPE_ID" not in resp.data


def test_recipe_edit_view_unknown_id_returns_404(client):
    resp = client.get("/manage/recipe/edit/999999")
    assert resp.status_code == 404


def test_recipe_edit_view_link_field_is_empty_not_literal_none(client, make_recipe):
    """Regression: value="None" is an invalid URL, so the browser refused to
    submit the form and the optional link field looked mandatory."""
    recipe_id = make_recipe("Ohne Link")
    resp = client.get(f"/manage/recipe/edit/{recipe_id}")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert 'id="sourceUrlInput"' in html
    assert 'value="None"' not in html
    assert 'name="source_url"' in html and 'value=""' in html


def test_recipe_edit_list_view_links_to_dedicated_edit_page(client, make_recipe):
    recipe_id = make_recipe("Irgendein Gericht")
    resp = client.get("/manage/recipe/edit-list")
    assert resp.status_code == 200
    assert f'href="/manage/recipe/edit/{recipe_id}?plan_id='.encode() in resp.data


def test_recipe_edit_list_view_persists_search_across_page_loads(client, make_recipe):
    """The search term survives page reloads via sessionStorage."""
    make_recipe("Suchbares Gericht")
    resp = client.get("/manage/recipe/edit-list")
    assert resp.status_code == 200
    assert b"sessionStorage" in resp.data
    assert b"speiseplan.recipeEditFilter" in resp.data


def test_recipe_detail_edit_link_points_to_dedicated_edit_page():
    """The plan page's recipe detail popup links to the recipe's edit page."""
    content = (STATIC_DIR / "plan-detail.js").read_text(encoding="utf-8")
    assert "`/manage/recipe/edit/${recipe.id}`" in content
    assert "edit-list?edit=" not in content


def test_recipe_edit_list_view_search_data_includes_category(client, make_category, make_recipe):
    cat_id = make_category("Beilagen")
    make_recipe("Kartoffelpüree", category_id=cat_id)

    resp = client.get("/manage/recipe/edit-list")
    assert resp.status_code == 200
    # Searching for a category also finds its recipes.
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
    assert f'value="{client.plan_id}" selected'.encode() in resp.data
    assert f'value="{other_plan_id}" selected'.encode() not in resp.data


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
    """The row displays the alias target, while the hidden real field keeps
    the stored name - so saving without editing never replaces it."""
    from services.ingredient_aliases import set_alias

    recipe_id = make_recipe("Pasta-Gericht", ingredients=[{"name": "Fusilli", "amount": 400, "unit": "g"}])
    with app.app_context():
        set_alias(client.plan_id, "Fusilli", "Nudeln")

    resp = client.get(f"/manage/recipe/edit/{recipe_id}")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert 'class="ing-name-display" tabindex="0" role="button" title="Click to edit">Nudeln</span>' in html
    assert 'class="ing-name-input d-none" value="Fusilli"' in html


def test_recipe_edit_view_shows_own_name_when_no_alias(client, make_recipe):
    recipe_id = make_recipe("Solo-Gericht", ingredients=[{"name": "Radicchio", "amount": 1, "unit": "Stk"}])

    resp = client.get(f"/manage/recipe/edit/{recipe_id}")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert 'ing-name-display" tabindex="0" role="button" title="Click to edit">Radicchio</span>' in html


def test_recipe_edit_view_has_editable_name_wiring_script(client, make_recipe):
    recipe_id = make_recipe("Irgendein Gericht", ingredients=[{"name": "Reis", "amount": 200, "unit": "g"}])
    resp = client.get(f"/manage/recipe/edit/{recipe_id}")
    assert resp.status_code == 200
    assert b"ingredient_alias_hint.js" in resp.data
    assert b"recipe_form.js" in resp.data


def test_recipe_create_view_embeds_ingredient_nutrition_for_hint_js(client, app):
    from services.nutrition import set_nutrition

    with app.app_context():
        set_nutrition(client.plan_id, "Öl", reference_unit="ml", protein=0, carbs=0, fat=100)

    resp = client.get("/manage/recipe/create")
    assert resp.status_code == 200
    assert b"window.INGREDIENT_NUTRITION" in resp.data
    # Computed, not stored: 100 g fat * 9 kcal/g.
    assert b'"calories": 900' in resp.data or b'"calories":900' in resp.data


def test_recipe_create_view_nutrition_inputs_disabled_by_default(client):
    resp = client.get("/manage/recipe/create")
    assert b'name="nutritionOverride"' not in resp.data  # id, not name
    assert b'id="nutritionOverride"' in resp.data
    # The kcal field has no name: it is display-only and never submitted.
    assert b'id="caloriesDisplay" class="rform-field" disabled' in resp.data
    assert b'name="protein" id="proteinInput" class="rform-field" disabled' in resp.data


def test_recipe_edit_view_prefills_override_checkbox(client, make_recipe):
    recipe_id = make_recipe("Übersteuert", nutrition_override=True, calories=555)
    resp = client.get(f"/manage/recipe/edit/{recipe_id}")
    assert resp.status_code == 200
    assert b'id="nutritionOverride"' in resp.data
    assert b'value="555"' in resp.data
    assert b"checked" in resp.data.split(b'id="nutritionOverride"')[1][:80]
