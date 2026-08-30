"""Tests für routes/recipes.py: Rezept anlegen/bearbeiten/löschen samt
Zutaten und Saison-Zuordnung, sowie der chefkoch.de-Import-Preview-Endpunkt."""
from pathlib import Path
from unittest.mock import patch

from services.recipe_import import RecipeImportError

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


def _base_recipe_form(category_id, **overrides):
    # nutrition_override="1" hält bestehende Tests, die feste
    # protein/carbs/fat-Werte erwarten, unabhängig von der automatischen
    # Berechnung aus den Zutaten (siehe services/nutrition.py:
    # compute_recipe_nutrition) - eigene Tests für die Berechnung selbst
    # setzen das Häkchen bewusst NICHT. calories gibt es hier bewusst
    # nicht als Formularfeld - es wird nie aus dem Formular übernommen,
    # sondern immer aus protein/carbs/fat errechnet (services/nutrition.py:
    # compute_calories(), hier also 290 = (20+30)*4 + 10*9).
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
    # tojson escaped Umlaute als \uXXXX statt roher UTF-8-Bytes (gültiges,
    # vom Browser korrekt interpretiertes JS) - hier also auf die
    # escapte Form prüfen, nicht auf die rohen Zeichen.
    assert b"Oliven\\u00f6l" in resp.data
    assert b'id="canonical-names-datalist"' in resp.data
    # Die Datalist rendert denselben Namen dagegen als normalen HTML-Text
    # (kein JSON), dort also die unescapte Form erwarten.
    assert "Öl".encode("utf-8") in resp.data


def test_recipe_create_view_ingredient_row_has_delete_button(client):
    """Jede Zutatenzeile (inkl. der leeren Ausgangszeile) braucht einen
    kleinen Löschen-Button, der die ganze .ingredient-row entfernt - sowohl
    server-seitig gerendert als auch im rformAddIngredientRow()-JS-Template
    in static/recipe_form.js, das später hinzugefügte Zeilen baut."""
    resp = client.get("/manage/recipe/create")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert 'class="ingredient-row' in html  # server-gerendert
    assert "this.closest('.ingredient-row').remove()" in html

    js = (STATIC_DIR / "recipe_form.js").read_text(encoding="utf-8")
    assert "div.className = 'ingredient-row'" in js  # rformAddIngredientRow()-JS-Template
    assert "this.closest('.ingredient-row').remove()" in js


def test_recipe_create_view_alias_hint_spans_full_ingredient_row(client):
    """Der Alias-/Nährwert-Hinweis darf nicht mehr in der schmalen
    Namens-Spalte eingebettet sein (das machte die dortige Inline-
    Nährwert-Eingabe unbrauchbar schmal), sondern muss NACH der kompletten
    Feldzeile (inkl. Löschen-Button ganz rechts) als eigenes Element
    stehen - also erst nach dem Marker für die letzte Spalte im
    HTML-Quelltext auftauchen, nicht schon direkt hinter dem Namensfeld."""
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


def test_recipe_edit_view_ingredient_row_has_delete_button(client, make_recipe):
    """Wie test_recipe_create_view_ingredient_row_has_delete_button, aber
    für die Bearbeiten-Seite eines Rezepts: sowohl die bestehenden
    Zutatenzeilen als auch die leere Ausgangszeile brauchen den
    Löschen-Button. Nutzt dasselbe recipe_form.html/recipe_form.js wie die
    Anlegen-Seite (siehe routes/recipes.py: recipe_edit_view)."""
    recipe_id = make_recipe("Gericht mit Zutat", ingredients=[{"name": "Mehl", "amount": 100, "unit": "g"}])
    resp = client.get(f"/manage/recipe/edit/{recipe_id}")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert html.count('class="ingredient-row') >= 2  # bestehende Zutat + leere Zeile
    assert "this.closest('.ingredient-row').remove()" in html


def test_recipe_edit_view_unknown_id_returns_404(client):
    resp = client.get("/manage/recipe/edit/999999")
    assert resp.status_code == 404


def test_recipe_edit_list_view_links_to_dedicated_edit_page(client, make_recipe):
    """Der "Bearbeiten"-Button verlinkt seit der Formular-Überarbeitung auf
    eine eigene Seite pro Rezept (routes/recipes.py: recipe_edit_view,
    /manage/recipe/edit/<id>) statt ein Modal per JS zu öffnen - vorher gab
    es dafür ein gemeinsames, per JS befülltes Modal (siehe ehemals
    static/recipe_edit_modal.js)."""
    recipe_id = make_recipe("Irgendein Gericht")
    resp = client.get("/manage/recipe/edit-list")
    assert resp.status_code == 200
    # Trägt seit dem Tab-Umschalter (siehe routes/recipes.py:
    # recipe_edit_list_view) zusätzlich ?plan_id=<id> - "in" statt "endet
    # mit" prüft weiterhin dasselbe Ziel, ohne von der genauen
    # Query-String-Form abzuhängen.
    assert f'href="/manage/recipe/edit/{recipe_id}?plan_id='.encode() in resp.data


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


def test_recipe_detail_edit_link_points_to_dedicated_edit_page():
    """Der "✏️ Rezept bearbeiten"-Button im Detail-Fenster auf der
    Plan-Seite (siehe templates/plan.html) verlinkt seit der
    Formular-Überarbeitung direkt auf die eigene Bearbeiten-Seite eines
    Rezepts (routes/recipes.py: recipe_edit_view) statt wie vorher auf
    /manage/recipe/edit-list?edit=<id> (das dortige Modal-Autostart-
    Verfahren gibt es seit static/recipe_edit_modal.js's Entfernung nicht
    mehr)."""
    content = (STATIC_DIR / "plan.js").read_text(encoding="utf-8")
    assert "`/manage/recipe/edit/${recipe.id}`" in content
    assert "edit-list?edit=" not in content


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
        assert recipe.calories == 290  # (20+30)*4 + 10*9, siehe _base_recipe_form()
        assert recipe.servings == 2
        # Die leere zweite ing_name[]-Zeile wird übersprungen, nur eine Zutat bleibt.
        assert len(recipe.ingredients) == 1
        assert recipe.ingredients[0].name == "Nudeln"
        assert len(recipe.seasons) == 1


def test_recipe_create_view_hides_plan_selector_with_single_plan(client):
    resp = client.get("/manage/recipe/create")
    assert resp.status_code == 200
    assert b'name="plan_id"' in resp.data  # als verstecktes Feld weiterhin vorhanden
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
    # Der gesternte (eigene) Plan ist vorausgewählt, der andere nicht.
    assert f'value="{client.plan_id}" selected'.encode() in resp.data
    assert f'value="{other_plan_id}" selected'.encode() not in resp.data


def test_add_recipe_without_explicit_plan_id_defaults_to_starred_plan(app, client, make_user, make_category):
    """default_plan_id() (services/auth.py) fällt OHNE ?plan_id= auf den
    gesternten Plan zurück, NICHT auf current_plan() - hier zusätzlich mit
    einem zweiten, nicht gesternten eigenen Plan geprüft, dessen bloße
    Existenz die Standardauswahl nicht verändern darf."""
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
    """Für die "Zuletzt bearbeitet"-Liste auf /manage (routes/manage.py) -
    Recipe.updated_at wird beim Anlegen über den Spalten-Default gesetzt
    (siehe models.py), ganz ohne dass add_recipe() es selbst pflegen muss."""
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


def test_edit_recipe_bumps_updated_at(client, app, make_recipe):
    """edit_recipe() setzt Recipe.updated_at explizit bei JEDEM Speichern
    (siehe dortigen Kommentar - ein onupdate=... an der Spalte würde nur
    greifen, wenn sich ein Wert tatsächlich ändert)."""
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
    """Eine Zutatenzeile mit gesetztem Alias zeigt standardmäßig den
    aufgelösten kanonischen Namen (.ing-name-display), NICHT den
    tatsächlich für dieses Rezept gespeicherten Namen - der bleibt
    unangetastet im (versteckten) echten Formularfeld, damit ein
    Speichern ohne bewusste Bearbeitung den ursprünglichen Namen nicht
    stillschweigend durch den Alias ersetzt (siehe
    static/ingredient_alias_hint.js: openIngredientNameField)."""
    from services.ingredient_aliases import set_alias

    recipe_id = make_recipe("Pasta-Gericht", ingredients=[{"name": "Fusilli", "amount": 400, "unit": "g"}])
    with app.app_context():
        set_alias(client.plan_id, "Fusilli", "Nudeln")

    resp = client.get(f"/manage/recipe/edit/{recipe_id}")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert 'class="ing-name-display" tabindex="0" role="button" title="Klicken zum Bearbeiten">Nudeln</span>' in html
    # Das eigentliche, editierbare Feld behält den echten gespeicherten Namen.
    assert 'class="ing-name-input d-none" value="Fusilli"' in html


def test_recipe_edit_view_shows_own_name_when_no_alias(client, make_recipe):
    recipe_id = make_recipe("Solo-Gericht", ingredients=[{"name": "Radicchio", "amount": 1, "unit": "Stk"}])

    resp = client.get(f"/manage/recipe/edit/{recipe_id}")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert 'ing-name-display" tabindex="0" role="button" title="Klicken zum Bearbeiten">Radicchio</span>' in html


def test_recipe_edit_view_has_editable_name_wiring_script(client, make_recipe):
    """static/ingredient_alias_hint.js muss eingebunden sein - es enthält
    sowohl das Klick-zum-Bearbeiten-Verhalten als auch das initiale
    Nachladen des Alias-/Nährwert-Hinweises für bereits ausgefüllte
    Zutatenzeilen (siehe dortige Kommentare)."""
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


# --- Automatische Nährwert-Berechnung aus den Zutaten (services/nutrition.py) ---

def test_add_recipe_computes_nutrition_from_ingredients(client, app, make_category):
    from models import Recipe
    from services.nutrition import set_nutrition

    cat_id = make_category("Berechnet")
    with app.app_context():
        # 10g Eiweiß/70g Kohlenhydrate/1g Fett je 100g Mehl.
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
        # 200g Mehl @(10/70/1 je 100g) / 2 Portionen = 10/70/1 pro Portion
        # (siehe Docstring von compute_recipe_nutrition: Ingredient.amount
        # gilt für den ganzen Rezept-Batch, Recipe.calories je Portion).
        # calories daraus errechnet (Atwater): (10+70)*4 + 1*9 = 329.
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
        set_nutrition(client.plan_id, "Nudeln", reference_unit="g", protein=1, carbs=1, fat=1)

    # _base_recipe_form() setzt nutrition_override="1" und feste
    # protein/carbs/fat-Werte per Default - diese müssen trotz vorhandener
    # IngredientNutrition-Daten für "Nudeln" unverändert übernommen werden
    # (und calories daraus errechnet, nicht aus den IngredientNutrition-
    # Daten für "Nudeln" - 290 = (20+30)*4 + 10*9, siehe _base_recipe_form()).
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
        # 200g Reis @(3/28/0.3 je 100g), 1 Portion -> 6/56/0.6.
        # calories daraus errechnet: (6+56)*4 + 0.6*9 = 253.
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
        # calories NIE aus dem Formular übernommen, auch nicht im
        # Override-Fall - errechnet aus protein/carbs/fat:
        # (77+7)*4 + 7*9 = 399.
        assert recipe.calories == 399


def test_recipe_create_view_embeds_ingredient_nutrition_for_hint_js(client, app):
    from services.nutrition import set_nutrition

    with app.app_context():
        set_nutrition(client.plan_id, "Öl", reference_unit="ml", protein=0, carbs=0, fat=100)

    resp = client.get("/manage/recipe/create")
    assert resp.status_code == 200
    assert b"window.INGREDIENT_NUTRITION" in resp.data
    # calories ist hier kein gespeicherter Wert, sondern wird für die
    # Einbettung aus protein/carbs/fat errechnet: 100g Fett * 9 kcal/g = 900.
    assert b'"calories": 900' in resp.data or b'"calories":900' in resp.data


def test_recipe_create_view_nutrition_inputs_disabled_by_default(client):
    resp = client.get("/manage/recipe/create")
    assert b'name="nutritionOverride"' not in resp.data  # id, nicht name
    assert b'id="nutritionOverride"' in resp.data
    # Kcal hat bewusst KEIN name-Attribut (wird nie mitgeschickt, siehe
    # services/nutrition.py: compute_calories()) - nur die Anzeige ist
    # immer deaktiviert.
    assert b'id="caloriesDisplay" class="rform-field" disabled' in resp.data
    assert b'name="protein" id="proteinInput" class="rform-field" disabled' in resp.data


def test_recipe_edit_view_prefills_override_checkbox(client, make_recipe):
    recipe_id = make_recipe("Übersteuert", nutrition_override=True, calories=555)
    resp = client.get(f"/manage/recipe/edit/{recipe_id}")
    assert resp.status_code == 200
    assert b'id="nutritionOverride"' in resp.data
    assert b'value="555"' in resp.data
    # Bei bereits gesetztem Override-Häkchen duerfen die Felder NICHT
    # deaktiviert sein (der Nutzer soll seine manuellen Werte direkt
    # weiter bearbeiten koennen) - das Checkbox-Input selbst muss "checked"
    # tragen (Attribut-Reihenfolge im Template ist ein Detail, daher hier
    # nur auf Vorhandensein prüfen statt exakter Attribut-Reihenfolge).
    assert b"checked" in resp.data.split(b'id="nutritionOverride"')[1][:80]
