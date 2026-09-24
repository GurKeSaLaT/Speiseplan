"""Tests for routes/settings.py: the combined ingredients & nutrition
page (/manage/ingredient-aliases) - merges what used to be two separate
pages/routes (see IDEAS.md). Every field on the page autosaves via the
AJAX endpoints (api_set_ingredient_alias()/api_set_ingredient_nutrition())
rather than a batch form submit - see the "AJAX endpoint" sections below
for those, and services/ingredient_aliases.py: recipes_by_ingredient_name()
for the "click a name to open its recipe" tests."""


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


def test_ingredient_aliases_view_has_no_save_button(client, make_recipe):
    """Everything on this page autosaves via AJAX (see the "AJAX
    endpoint" sections below) - there is deliberately no batch-save form/
    Save button to click anymore (formerly update_ingredients(), see
    IDEAS.md). The sidebar's OWN plan-switch <form>s are unrelated and
    still expected to be present, so this checks for the specific
    batch-save markup rather than "<form" globally."""
    make_recipe("A", ingredients=[{"name": "Reis", "amount": 200, "unit": "g"}])
    resp = client.get("/manage/ingredient-aliases")
    assert resp.status_code == 200
    assert b'action="/update-ingredients"' not in resp.data
    assert b'name="raw_name[]"' not in resp.data
    assert b'name="canonical_name[]"' not in resp.data


def test_ingredient_aliases_view_links_single_recipe_name_directly(client, app, make_recipe):
    """A name used in exactly one recipe links straight to it (see
    services/ingredient_aliases.py: recipes_by_ingredient_name())."""
    recipe_id = make_recipe("Nudelauflauf", ingredients=[{"name": "Reis", "amount": 200, "unit": "g"}])

    resp = client.get("/manage/ingredient-aliases")
    assert resp.status_code == 200
    assert f'href="/manage/recipe/edit/{recipe_id}?plan_id={client.plan_id}"'.encode() in resp.data


def test_ingredient_aliases_view_shows_dropdown_for_multiple_recipes(client, make_recipe):
    """A name used in more than one recipe gets a dropdown listing each,
    instead of a single ambiguous link."""
    make_recipe("A", ingredients=[{"name": "Reis", "amount": 200, "unit": "g"}])
    make_recipe("B", ingredients=[{"name": "Reis", "amount": 100, "unit": "g"}])

    resp = client.get("/manage/ingredient-aliases")
    assert resp.status_code == 200
    assert b"dropdown-menu" in resp.data
    assert resp.data.count(b'class="dropdown-item"') == 2


def test_ingredient_aliases_view_links_group_heading_via_its_aliases(client, app, make_recipe):
    """A main group's canonical name is often an invented umbrella (e.g.
    "Nudeln" for "Spaghetti") that was never itself typed as an
    ingredient anywhere - the heading must still link to the recipe(s)
    its ALIASES belong to, not come back empty just because the literal
    canonical string isn't used anywhere (see routes/settings.py:
    _merged_recipes(), a real bug reported live: many main ingredients
    showed no recipe link at all before this fix)."""
    from services.ingredient_aliases import set_alias

    recipe_id = make_recipe("Nudelauflauf", ingredients=[{"name": "Spaghetti", "amount": 500, "unit": "g"}])
    with app.app_context():
        set_alias(client.plan_id, "Spaghetti", "Nudeln")

    resp = client.get("/manage/ingredient-aliases")
    assert resp.status_code == 200
    assert f'href="/manage/recipe/edit/{recipe_id}?plan_id={client.plan_id}"'.encode() in resp.data


def test_ingredient_aliases_view_nests_existing_alias_under_its_group(client, app, make_recipe):
    """An ingredient with an alias set shows up as a nested alias item
    under its canonical name's main-ingredient group (not as an editable
    "counts as" input - that only exists for rows still in "Everything
    else", see the other_rows loop in the template)."""
    from services.ingredient_aliases import set_alias

    make_recipe("A", ingredients=[{"name": "Spaghetti", "amount": 500, "unit": "g"}])
    with app.app_context():
        set_alias(client.plan_id, "Spaghetti", "Nudeln")

    resp = client.get("/manage/ingredient-aliases")
    assert resp.status_code == 200
    assert b"Nudeln" in resp.data
    # The raw name travels to the "x" button via a plain, auto-escaped
    # data attribute rather than an inline onclick="..." with the name
    # interpolated straight in via tojson - see the JS comment above
    # removeAlias's addEventListener wiring for why that combination is
    # unsafe (a real bug: ANY name broke it, since tojson always wraps a
    # string in literal, unescaped double quotes).
    assert b'class="alias-remove-btn" data-raw-name="Spaghetti"' in resp.data


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


# --- explicit plan_id (used by the autosave on ingredient_aliases_manage.html
# itself, which may be viewing a non-active plan via its own tab switcher) ---

def test_api_set_ingredient_alias_accepts_explicit_plan_id_for_a_membership(client, app, make_user):
    """The active plan (current_plan()) is client.plan_id - explicitly
    targeting a DIFFERENT plan the same user is ALSO a member of must
    still work (not silently fall back to the active one)."""
    from models import PlanMembership, db
    from services.ingredient_aliases import normalize_ingredient_name

    other_user_id, other_plan_id = make_user("Andere")
    with app.app_context():
        db.session.add(PlanMembership(plan_id=other_plan_id, user_id=client.user_id, is_starred=False))
        db.session.commit()

    resp = client.post("/api/ingredient-alias/set", json={
        "raw_name": "Reis", "canonical_name": "Getreide", "plan_id": other_plan_id,
    })
    assert resp.status_code == 200

    with app.app_context():
        assert normalize_ingredient_name(other_plan_id, "Reis") == "Getreide"
        # Did NOT leak into the active plan.
        assert normalize_ingredient_name(client.plan_id, "Reis") == "Reis"


def test_api_set_ingredient_alias_ignores_plan_id_without_membership(client, app, make_user):
    """A plan_id the user has no access to must be ignored, not silently
    grant write access - falls back to the active plan instead, exactly
    like an absent plan_id would."""
    from services.ingredient_aliases import normalize_ingredient_name

    _, foreign_plan_id = make_user("Fremd")

    resp = client.post("/api/ingredient-alias/set", json={
        "raw_name": "Reis", "canonical_name": "Getreide", "plan_id": foreign_plan_id,
    })
    assert resp.status_code == 200

    with app.app_context():
        assert normalize_ingredient_name(foreign_plan_id, "Reis") == "Reis"
        assert normalize_ingredient_name(client.plan_id, "Reis") == "Getreide"
