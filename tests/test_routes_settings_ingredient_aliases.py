"""The ingredients & nutrition page and the alias AJAX endpoint."""


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
    """Regression: per-row lookups made this page take 34 s in production.
    Output was identical either way, so only a query count catches it."""
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
    assert b"Nudeln" in resp.data
    assert b"Spaghetti" in resp.data
    assert b"Fusilli" in resp.data


def test_ingredient_aliases_view_rows_carry_a_stable_row_key(client, app, make_recipe):
    """The page's refresh logic uses these keys to leave unchanged rows (and
    any focused field in them) untouched."""
    from services.ingredient_aliases import set_alias

    make_recipe("A", ingredients=[{"name": "Spaghetti", "amount": 500, "unit": "g"}])
    make_recipe("B", ingredients=[{"name": "Reis", "amount": 200, "unit": "g"}])
    with app.app_context():
        set_alias(client.plan_id, "Spaghetti", "Nudeln")

    resp = client.get("/manage/ingredient-aliases")
    assert resp.status_code == 200
    assert b'data-row-key="main:Nudeln"' in resp.data
    assert b'data-row-key="other:Reis"' in resp.data


def test_ingredient_aliases_view_main_ingredient_has_nutrition_fields(client, app, make_recipe):
    from services.ingredient_aliases import set_alias
    from services.nutrition import set_nutrition

    # The alias needs a recipe using it, or it gets pruned as orphaned.
    make_recipe("A", ingredients=[{"name": "Olivenöl", "amount": 30, "unit": "ml"}])
    with app.app_context():
        set_alias(client.plan_id, "Olivenöl", "Öl")
        set_nutrition(client.plan_id, "Öl", reference_unit="ml", protein=0, carbs=0, fat=100)

    resp = client.get("/manage/ingredient-aliases")
    assert resp.status_code == 200
    assert b">900<" in resp.data  # 100 g fat * 9, computed
    assert b'value="ml" selected' in resp.data


def test_ingredient_aliases_view_other_row_has_own_nutrition_fields(client, make_recipe):
    make_recipe("A", ingredients=[{"name": "Reis", "amount": 200, "unit": "g"}])

    resp = client.get("/manage/ingredient-aliases")
    assert resp.status_code == 200
    assert b"Reis" in resp.data
    assert b'value="g" selected' in resp.data  # guessed from the recipe's unit


def test_ingredient_aliases_view_has_no_save_button(client, make_recipe):
    """Everything autosaves. (The sidebar has unrelated forms, so check the
    old batch-save markup specifically.)"""
    make_recipe("A", ingredients=[{"name": "Reis", "amount": 200, "unit": "g"}])
    resp = client.get("/manage/ingredient-aliases")
    assert resp.status_code == 200
    assert b'action="/update-ingredients"' not in resp.data
    assert b'name="raw_name[]"' not in resp.data
    assert b'name="canonical_name[]"' not in resp.data


def test_ingredient_aliases_view_links_single_recipe_name_directly(client, app, make_recipe):
    recipe_id = make_recipe("Nudelauflauf", ingredients=[{"name": "Reis", "amount": 200, "unit": "g"}])

    resp = client.get("/manage/ingredient-aliases")
    assert resp.status_code == 200
    assert f'href="/manage/recipe/edit/{recipe_id}?plan_id={client.plan_id}"'.encode() in resp.data


def test_ingredient_aliases_view_shows_dropdown_for_multiple_recipes(client, make_recipe):
    make_recipe("A", ingredients=[{"name": "Reis", "amount": 200, "unit": "g"}])
    make_recipe("B", ingredients=[{"name": "Reis", "amount": 100, "unit": "g"}])

    resp = client.get("/manage/ingredient-aliases")
    assert resp.status_code == 200
    assert b"dropdown-menu" in resp.data
    assert resp.data.count(b'class="dropdown-item"') == 2


def test_ingredient_aliases_view_prunes_orphaned_aliases(client, app, make_recipe):
    """Real case: the alias survived after the ingredient was renamed."""
    from services.ingredient_aliases import get_all_aliases, set_alias

    make_recipe("Obstsalat", ingredients=[{"name": "Ananasstuecke (approx)", "amount": 200, "unit": "g"}])
    with app.app_context():
        set_alias(client.plan_id, "Ananasstuecke", "Ananas")
        assert "Ananasstuecke" in get_all_aliases(client.plan_id)

    resp = client.get("/manage/ingredient-aliases")
    assert resp.status_code == 200
    # "Ananas" had only this alias, so no group may remain. (A substring
    # check on the name wouldn't work: the renamed ingredient contains it.)
    assert b"main-ingredient-row" not in resp.data

    with app.app_context():
        assert "Ananasstuecke" not in get_all_aliases(client.plan_id)


def test_ingredient_aliases_view_keeps_aliases_still_in_use(client, app, make_recipe):
    from services.ingredient_aliases import get_all_aliases, set_alias

    make_recipe("Nudelauflauf", ingredients=[{"name": "Spaghetti", "amount": 500, "unit": "g"}])
    with app.app_context():
        set_alias(client.plan_id, "Spaghetti", "Nudeln")

    resp = client.get("/manage/ingredient-aliases")
    assert resp.status_code == 200
    assert b"Spaghetti" in resp.data

    with app.app_context():
        assert get_all_aliases(client.plan_id).get("Spaghetti") == "Nudeln"


def test_ingredient_aliases_view_links_group_heading_via_its_aliases(client, app, make_recipe):
    """A group name is often never typed as an ingredient itself; its
    heading still links to its aliases' recipes."""
    from services.ingredient_aliases import set_alias

    recipe_id = make_recipe("Nudelauflauf", ingredients=[{"name": "Spaghetti", "amount": 500, "unit": "g"}])
    with app.app_context():
        set_alias(client.plan_id, "Spaghetti", "Nudeln")

    resp = client.get("/manage/ingredient-aliases")
    assert resp.status_code == 200
    assert f'href="/manage/recipe/edit/{recipe_id}?plan_id={client.plan_id}"'.encode() in resp.data


def test_ingredient_aliases_view_nests_existing_alias_under_its_group(client, app, make_recipe):
    from services.ingredient_aliases import set_alias

    make_recipe("A", ingredients=[{"name": "Spaghetti", "amount": 500, "unit": "g"}])
    with app.app_context():
        set_alias(client.plan_id, "Spaghetti", "Nudeln")

    resp = client.get("/manage/ingredient-aliases")
    assert resp.status_code == 200
    assert b"Nudeln" in resp.data
    # Name in an escaped data attribute: tojson inside onclick="..." broke
    # for every name (its quotes end the attribute).
    assert b'class="alias-remove-btn" data-raw-name="Spaghetti"' in resp.data


# --- /api/ingredient-alias/set ---

def test_api_set_ingredient_alias_creates_mapping(client, app):
    from services.ingredient_aliases import normalize_ingredient_name

    resp = client.post("/api/ingredient-alias/set", json={"raw_name": "Olivenöl", "canonical_name": "Öl"})
    assert resp.status_code == 200
    data = resp.get_json()
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
    """The recipe form applies the returned category to the row."""
    make_recipe("Spaghetti-Gericht", ingredients=[
        {"name": "Nudeln", "amount": 500, "unit": "g", "category": "Teigwaren"},
    ])

    resp = client.post("/api/ingredient-alias/set", json={"raw_name": "Penne", "canonical_name": "Nudeln"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["category"] == "Teigwaren"


def test_api_set_ingredient_alias_returns_inferred_pantry_flag(client, app, make_recipe):
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


# --- explicit plan_id (the ingredients page may show a non-active plan) ---

def test_api_set_ingredient_alias_accepts_explicit_plan_id_for_a_membership(client, app, make_user):
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
        assert normalize_ingredient_name(client.plan_id, "Reis") == "Reis"


def test_api_set_ingredient_alias_ignores_plan_id_without_membership(client, app, make_user):
    """A foreign plan_id falls back to the active plan, never grants access."""
    from services.ingredient_aliases import normalize_ingredient_name

    _, foreign_plan_id = make_user("Fremd")

    resp = client.post("/api/ingredient-alias/set", json={
        "raw_name": "Reis", "canonical_name": "Getreide", "plan_id": foreign_plan_id,
    })
    assert resp.status_code == 200

    with app.app_context():
        assert normalize_ingredient_name(foreign_plan_id, "Reis") == "Reis"
        assert normalize_ingredient_name(client.plan_id, "Reis") == "Getreide"
