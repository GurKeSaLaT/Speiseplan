"""Tests for routes/settings.py: the nutrition management page
(/manage/ingredient-nutrition, /update-ingredient-nutrition) as well as the
AJAX endpoint for the inline hint when entering an ingredient
(/api/ingredient-nutrition/set). The reference base is always 100g/100ml/1pc
(services/nutrition.py: REFERENCE_BASES) - so there is deliberately NO
reference_amount form field/property anymore, only reference_unit.
Likewise NO calories field: calories are never entered directly, but always
computed from protein/carbs/fat (compute_calories())."""


def test_ingredient_nutrition_view_empty_state(client):
    resp = client.get("/manage/ingredient-nutrition")
    assert resp.status_code == 200
    assert "No merged ingredients yet.".encode("utf-8") in resp.data


def test_ingredient_nutrition_view_lists_only_alias_targets(client, app):
    from services.ingredient_aliases import set_alias

    with app.app_context():
        set_alias(client.plan_id, "Spaghetti", "Nudeln")
        set_alias(client.plan_id, "Fusilli", "Nudeln")

    resp = client.get("/manage/ingredient-nutrition")
    assert resp.status_code == 200
    assert b"Nudeln" in resp.data
    # Non-aliased individual ingredients (the alias source names themselves)
    # deliberately do NOT show up here as their own row.
    assert b'value="Spaghetti"' not in resp.data
    assert b"fuzzy_search.js" in resp.data
    assert b"wireFuzzyFilter" in resp.data


def test_ingredient_nutrition_view_prefills_existing_entry(client, app):
    from services.ingredient_aliases import set_alias
    from services.nutrition import set_nutrition

    with app.app_context():
        set_alias(client.plan_id, "Olivenöl", "Öl")
        set_nutrition(client.plan_id, "Öl", reference_unit="ml", protein=0, carbs=0, fat=100)

    resp = client.get("/manage/ingredient-nutrition")
    assert resp.status_code == 200
    # 0*4 + 0*4 + 100*9 = 900 - computed, not stored.
    assert b'value="900"' in resp.data
    # The reference base is a <select>, no longer a number field - the
    # chosen option must carry "selected".
    assert b'value="ml" selected' in resp.data


def test_ingredient_nutrition_view_infers_reference_unit_for_new_entry(client, app):
    from services.ingredient_aliases import set_alias

    with app.app_context():
        set_alias(client.plan_id, "Fusilli", "Nudeln")

    resp = client.get("/manage/ingredient-nutrition")
    assert resp.status_code == 200
    # No existing entry -> guessed unit (here "g" for lack of actually
    # used ingredient rows) as the preselected option.
    assert b'value="g" selected' in resp.data


def test_update_ingredient_nutrition_saves_all_rows(client, app):
    from services.ingredient_aliases import set_alias
    from services.nutrition import get_nutrition_entry

    with app.app_context():
        set_alias(client.plan_id, "Spaghetti", "Nudeln")
        set_alias(client.plan_id, "Olivenöl", "Öl")

    resp = client.post("/update-ingredient-nutrition", data={
        "canonical_name[]": ["Nudeln", "Öl"],
        "reference_unit[]": ["g", "ml"],
        "protein[]": ["12", "0"],
        "carbs[]": ["70", "0"],
        "fat[]": ["1.5", "100"],
    }, follow_redirects=False)
    assert resp.status_code == 302

    with app.app_context():
        nudeln = get_nutrition_entry(client.plan_id, "Nudeln")
        assert nudeln.protein == 12
        assert nudeln.reference_amount == 100
        oel = get_nutrition_entry(client.plan_id, "Öl")
        assert oel.fat == 100
        assert oel.reference_unit == "ml"
        assert oel.reference_amount == 100


def test_update_ingredient_nutrition_stk_basis_gets_amount_one(client, app):
    from services.ingredient_aliases import set_alias
    from services.nutrition import get_nutrition_entry

    with app.app_context():
        set_alias(client.plan_id, "Freilandei", "Ei")

    client.post("/update-ingredient-nutrition", data={
        "canonical_name[]": ["Ei"],
        "reference_unit[]": ["Stk"],
        "protein[]": ["6.5"],
        "carbs[]": ["0.6"],
        "fat[]": ["5.3"],
    })

    with app.app_context():
        entry = get_nutrition_entry(client.plan_id, "Ei")
        assert entry.reference_unit == "Stk"
        assert entry.reference_amount == 1


def test_update_ingredient_nutrition_invalid_values_default_to_zero(client, app):
    from services.ingredient_aliases import set_alias
    from services.nutrition import get_nutrition_entry

    with app.app_context():
        set_alias(client.plan_id, "Spaghetti", "Nudeln")

    client.post("/update-ingredient-nutrition", data={
        "canonical_name[]": ["Nudeln"],
        "reference_unit[]": [""],
        "protein[]": [""],
        "carbs[]": [""],
        "fat[]": [""],
    })

    with app.app_context():
        entry = get_nutrition_entry(client.plan_id, "Nudeln")
        assert entry.protein == 0
        assert entry.reference_amount == 100
        assert entry.reference_unit == "g"


# --- AJAX endpoint for the recipe forms (api_set_ingredient_nutrition) ---

def test_api_set_ingredient_nutrition_creates_entry(client, app):
    from services.nutrition import get_nutrition_entry

    resp = client.post("/api/ingredient-nutrition/set", json={
        "name": "Reis", "reference_unit": "g",
        "protein": 3, "carbs": 28, "fat": 0.3,
    })
    assert resp.status_code == 200
    data = resp.get_json()
    assert data == {
        "ok": True, "canonical_name": "Reis", "reference_amount": 100,
        "reference_unit": "g", "calories": 127, "protein": 3.0, "carbs": 28.0, "fat": 0.3,
    }
    with app.app_context():
        assert get_nutrition_entry(client.plan_id, "Reis").protein == 3


def test_api_set_ingredient_nutrition_resolves_through_alias(client, app):
    from services.ingredient_aliases import set_alias

    with app.app_context():
        set_alias(client.plan_id, "Spaghetti", "Nudeln")

    resp = client.post("/api/ingredient-nutrition/set", json={
        "name": "Spaghetti", "reference_unit": "g",
        "protein": 12, "carbs": 70, "fat": 1.5,
    })
    assert resp.status_code == 200
    assert resp.get_json()["canonical_name"] == "Nudeln"


def test_api_set_ingredient_nutrition_rejects_empty_name(client):
    resp = client.post("/api/ingredient-nutrition/set", json={"name": ""})
    assert resp.status_code == 400
    assert "error" in resp.get_json()


def test_api_set_ingredient_nutrition_defaults_missing_fields(client):
    resp = client.post("/api/ingredient-nutrition/set", json={"name": "Zucker"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["reference_amount"] == 100
    assert data["reference_unit"] == "g"
    assert data["calories"] == 0


def test_api_set_ingredient_nutrition_rejects_arbitrary_reference_unit(client, app):
    """A manipulated request with reference_unit="Becher" or similar must NOT
    be accepted unchanged - set_nutrition() enforces g/ml/Stk
    (see services/nutrition.py: REFERENCE_BASES)."""
    resp = client.post("/api/ingredient-nutrition/set", json={
        "name": "Joghurt", "reference_unit": "Becher",
    })
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["reference_unit"] == "g"
    assert data["reference_amount"] == 100
