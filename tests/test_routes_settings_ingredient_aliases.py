"""Tests for routes/settings.py: the combined ingredients & nutrition
page (/manage/ingredient-aliases, /update-ingredients) - merges what used
to be two separate pages/routes (see IDEAS.md)."""


def test_ingredient_aliases_view_lists_unaliased_names_under_other(client, make_recipe):
    make_recipe("Suppe", ingredients=[{"name": "Spaghetti", "amount": 500, "unit": "g"}])
    resp = client.get("/manage/ingredient-aliases")
    assert resp.status_code == 200
    assert b"Spaghetti" in resp.data
    assert b"fuzzy_search.js" in resp.data
    assert b"wireFuzzyFilter" in resp.data


def test_ingredient_aliases_view_empty_state(client):
    resp = client.get("/manage/ingredient-aliases")
    assert resp.status_code == 200
    assert "No ingredients yet.".encode("utf-8") in resp.data


def test_ingredient_aliases_view_query_count_does_not_scale_with_ingredient_count(client, app, make_recipe):
    """Regression test for a real production incident (2026-09-25): a
    page load with ~400 known ingredients took 34 SECONDS. Cause: this
    view called the single-name services/nutrition.py:
    infer_reference_unit() once per row without an existing nutrition
    entry - each call did its own full scan of every visible ingredient
    PLUS one alias-resolving query per ingredient inside that scan. That
    was already wasteful for the old, separate nutrition page (which
    only ever covered the usually-few alias TARGETS), but turned into a
    real O(rows x ingredients) query explosion once this page started
    covering every unaliased "other" ingredient too. Fixed via
    services/nutrition.py: infer_reference_units_for_plan(), which
    computes the guess for every canonical name in ONE pass. Asserts the
    number of SQL statements issued stays a small, bounded constant
    regardless of how many ingredients exist, rather than scaling with
    them - a purely functional/timing-based test wouldn't have caught
    this at all (both the buggy and fixed version return the exact same
    page content, just at wildly different speeds)."""
    from sqlalchemy import event
    from models import db

    for i in range(40):
        make_recipe(f"Rezept {i}", ingredients=[{"name": f"Zutat {i}", "amount": 100, "unit": "g"}])

    queries = []

    def _count(conn, cursor, statement, parameters, context, executemany):
        queries.append(statement)

    with app.app_context():
        engine = db.engine
        event.listen(engine, "before_cursor_execute", _count)
        try:
            resp = client.get("/manage/ingredient-aliases")
        finally:
            event.remove(engine, "before_cursor_execute", _count)

    assert resp.status_code == 200
    # A handful of queries total (aliases/entries/known-names/inferred-units/
    # plan-membership lookups, ...), NOT one extra query per ingredient -
    # comfortably under the 40 "other" rows just created either way.
    assert len(queries) < 25


def test_ingredient_aliases_view_groups_main_ingredient_with_nested_aliases(client, app, make_recipe):
    from services.ingredient_aliases import set_alias

    make_recipe("A", ingredients=[{"name": "Spaghetti", "amount": 500, "unit": "g"}])
    make_recipe("B", ingredients=[{"name": "Fusilli", "amount": 300, "unit": "g"}])
    with app.app_context():
        set_alias(client.plan_id, "Spaghetti", "Nudeln")
        set_alias(client.plan_id, "Fusilli", "Nudeln")

    resp = client.get("/manage/ingredient-aliases")
    assert resp.status_code == 200
    # "Nudeln" is a main ingredient now (something is aliased to it) -
    # "Spaghetti"/"Fusilli" show up nested under it, not as their own
    # "everything else" row.
    assert b"Nudeln" in resp.data
    assert b"Spaghetti" in resp.data
    assert b"Fusilli" in resp.data


def test_ingredient_aliases_view_main_ingredient_has_nutrition_fields(client, app):
    from services.ingredient_aliases import set_alias
    from services.nutrition import set_nutrition

    with app.app_context():
        set_alias(client.plan_id, "Olivenöl", "Öl")
        set_nutrition(client.plan_id, "Öl", reference_unit="ml", protein=0, carbs=0, fat=100)

    resp = client.get("/manage/ingredient-aliases")
    assert resp.status_code == 200
    # 0*4 + 0*4 + 100*9 = 900 - computed, not stored.
    assert b">900<" in resp.data
    assert b'value="ml" selected' in resp.data


def test_ingredient_aliases_view_other_row_has_own_nutrition_fields(client, make_recipe):
    """Unlike the old, separate nutrition page, an UNALIASED ingredient
    now also gets its own nutrition editor directly on this page (it's
    its own canonical name, see services/nutrition.py:
    get_nutrition_entry()), not just via the recipe form's inline hint."""
    make_recipe("A", ingredients=[{"name": "Reis", "amount": 200, "unit": "g"}])

    resp = client.get("/manage/ingredient-aliases")
    assert resp.status_code == 200
    assert b"Reis" in resp.data
    # No entry yet -> guessed unit (here "g" for lack of actually used
    # ingredient rows) as the preselected option.
    assert b'value="g" selected' in resp.data


def test_update_ingredients_creates_grouping(client, app, make_recipe):
    from services.ingredient_aliases import normalize_ingredient_name

    make_recipe("A", ingredients=[{"name": "Spaghetti", "amount": 500, "unit": "g"}])
    make_recipe("B", ingredients=[{"name": "Fusilli", "amount": 300, "unit": "g"}])

    resp = client.post("/update-ingredients", data={
        "raw_name[]": ["Spaghetti", "Fusilli"],
        "canonical_name[]": ["Nudeln", "Nudeln"],
    }, follow_redirects=False)
    assert resp.status_code == 302

    with app.app_context():
        assert normalize_ingredient_name(client.plan_id, "Spaghetti") == "Nudeln"
        assert normalize_ingredient_name(client.plan_id, "Fusilli") == "Nudeln"


def test_update_ingredients_unchanged_row_stays_unaliased(client, app, make_recipe):
    from services.ingredient_aliases import get_all_aliases

    make_recipe("A", ingredients=[{"name": "Reis", "amount": 200, "unit": "g"}])

    client.post("/update-ingredients", data={
        "raw_name[]": ["Reis"],
        "canonical_name[]": ["Reis"],
    })
    with app.app_context():
        assert get_all_aliases(client.plan_id) == {}


def test_update_ingredients_removing_alias_via_canonical_equal_to_raw(client, app, make_recipe):
    """The "×" button behind a nested alias (see
    templates/ingredient_aliases_manage.html: removeAliasRow()) works by
    setting canonical_name[] back to the raw name itself before submit -
    exactly like retyping "Counts as" back to the original name."""
    from services.ingredient_aliases import get_all_aliases, set_alias

    make_recipe("A", ingredients=[{"name": "Spaghetti", "amount": 500, "unit": "g"}])
    with app.app_context():
        set_alias(client.plan_id, "Spaghetti", "Nudeln")

    client.post("/update-ingredients", data={
        "raw_name[]": ["Spaghetti"],
        "canonical_name[]": ["Spaghetti"],
    })
    with app.app_context():
        assert get_all_aliases(client.plan_id) == {}


def test_update_ingredients_saves_nutrition_for_main_and_other_rows(client, app, make_recipe):
    from services.ingredient_aliases import set_alias
    from services.nutrition import get_nutrition_entry

    make_recipe("A", ingredients=[{"name": "Reis", "amount": 200, "unit": "g"}])
    with app.app_context():
        set_alias(client.plan_id, "Spaghetti", "Nudeln")

    resp = client.post("/update-ingredients", data={
        "nutrition_name[]": ["Nudeln", "Reis"],
        "reference_unit[]": ["g", "g"],
        "protein[]": ["12", "3"],
        "carbs[]": ["70", "28"],
        "fat[]": ["1.5", "0.3"],
    }, follow_redirects=False)
    assert resp.status_code == 302

    with app.app_context():
        nudeln = get_nutrition_entry(client.plan_id, "Nudeln")
        assert nudeln.protein == 12
        reis = get_nutrition_entry(client.plan_id, "Reis")
        assert reis.protein == 3


def test_update_ingredients_reassigning_alias_and_nutrition_in_one_submit(client, app, make_recipe):
    """Saving a new "counts as" AND a nutrition value for the SAME row in
    one submit must land the nutrition under the NEW canonical name, not
    the old one - alias pairs are applied before nutrition rows (see
    routes/settings.py: update_ingredients())."""
    from models import IngredientNutrition
    from services.nutrition import get_nutrition_entry

    make_recipe("A", ingredients=[{"name": "Tomaten", "amount": 400, "unit": "g"}])

    client.post("/update-ingredients", data={
        "raw_name[]": ["Tomaten"],
        "canonical_name[]": ["Passierte Tomaten"],
        "nutrition_name[]": ["Tomaten"],
        "reference_unit[]": ["g"],
        "protein[]": ["0.9"],
        "carbs[]": ["3.9"],
        "fat[]": ["0.2"],
    })

    with app.app_context():
        assert get_nutrition_entry(client.plan_id, "Passierte Tomaten").protein == 0.9
        # No SEPARATE, stray entry was created directly under the old
        # literal name - get_nutrition_entry("Tomaten") would still find
        # the same row via alias resolution, so check the raw storage
        # instead (no row whose OWN canonical_name is still "Tomaten").
        assert IngredientNutrition.query.filter_by(
            plan_id=client.plan_id, canonical_name="Tomaten"
        ).first() is None


def test_ingredient_aliases_view_prefills_existing_alias(client, app, make_recipe):
    from services.ingredient_aliases import set_alias

    make_recipe("A", ingredients=[{"name": "Spaghetti", "amount": 500, "unit": "g"}])
    with app.app_context():
        set_alias(client.plan_id, "Spaghetti", "Nudeln")

    resp = client.get("/manage/ingredient-aliases")
    assert b'value="Nudeln"' in resp.data


# --- AJAX endpoint for the recipe forms (api_set_ingredient_alias) ---

def test_api_set_ingredient_alias_creates_mapping(client, app):
    from services.ingredient_aliases import normalize_ingredient_name

    resp = client.post("/api/ingredient-alias/set", json={"raw_name": "Olivenöl", "canonical_name": "Öl"})
    assert resp.status_code == 200
    data = resp.get_json()
    # category is None and is_pantry is False because "Öl" isn't yet
    # categorized/flagged on any existing ingredient row (see the
    # dedicated infer_category/infer_is_pantry tests below).
    assert data == {
        "ok": True, "raw_name": "Olivenöl", "canonical_name": "Öl", "category": None, "is_pantry": False,
    }

    with app.app_context():
        assert normalize_ingredient_name(client.plan_id, "Olivenöl") == "Öl"


def test_api_set_ingredient_alias_normalizes_input(client, app):
    from services.ingredient_aliases import normalize_ingredient_name

    resp = client.post("/api/ingredient-alias/set", json={"raw_name": "  fusilli  ", "canonical_name": "nudeln"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data == {
        "ok": True, "raw_name": "Fusilli", "canonical_name": "Nudeln", "category": None, "is_pantry": False,
    }
    with app.app_context():
        assert normalize_ingredient_name(client.plan_id, "Fusilli") == "Nudeln"


def test_api_set_ingredient_alias_returns_inferred_category(client, app, make_recipe):
    """If a categorized ingredient row already exists for the canonical
    ingredient (e.g. "Nudeln" is already filed under "Teigwaren"), setting
    another alias to the same name should return that category directly -
    static/ingredient_alias_hint.js automatically applies it to the
    category field of the current ingredient row (see fillCategoryFromAlias),
    so that all aliased ingredients are filed consistently."""
    make_recipe("Spaghetti-Gericht", ingredients=[
        {"name": "Nudeln", "amount": 500, "unit": "g", "category": "Teigwaren"},
    ])

    resp = client.post("/api/ingredient-alias/set", json={"raw_name": "Penne", "canonical_name": "Nudeln"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["category"] == "Teigwaren"


def test_api_set_ingredient_alias_returns_inferred_pantry_flag(client, app, make_recipe):
    """Mirrors test_api_set_ingredient_alias_returns_inferred_category
    above, but for is_pantry (services/shopping.py: infer_is_pantry) -
    static/ingredient_alias_hint.js: fillPantryFromAlias() applies it to
    the pantry checkbox of the current ingredient row."""
    make_recipe("Gewürztes Gericht", ingredients=[
        {"name": "Salz", "amount": 5, "unit": "g", "is_pantry": True},
    ])

    resp = client.post("/api/ingredient-alias/set", json={"raw_name": "Meersalz", "canonical_name": "Salz"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["is_pantry"] is True


def test_api_set_ingredient_alias_requires_both_fields(client):
    resp = client.post("/api/ingredient-alias/set", json={"raw_name": "Reis"})
    assert resp.status_code == 400
    assert "error" in resp.get_json()

    resp2 = client.post("/api/ingredient-alias/set", json={"canonical_name": "Reis"})
    assert resp2.status_code == 400


def test_api_set_ingredient_alias_rejects_empty_body(client):
    resp = client.post("/api/ingredient-alias/set", json={})
    assert resp.status_code == 400
