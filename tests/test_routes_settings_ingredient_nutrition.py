"""Tests for routes/settings.py: the AJAX endpoint for the inline hint
when entering an ingredient (/api/ingredient-nutrition/set). The page
that used to live here (/manage/ingredient-nutrition,
/update-ingredient-nutrition) was merged into the combined ingredients &
nutrition page - see tests/test_routes_settings_ingredient_aliases.py and
IDEAS.md.

The reference base is always 100g/100ml/1pc (services/nutrition.py:
REFERENCE_BASES) - so there is deliberately NO reference_amount form
field/property anymore, only reference_unit. Likewise NO calories field:
calories are never entered directly, but always computed from
protein/carbs/fat (compute_calories())."""


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
