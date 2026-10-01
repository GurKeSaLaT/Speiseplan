"""/api/ingredient-nutrition/set. There is no reference_amount or calories
input: the amount follows from the unit, calories are computed."""


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


# --- explicit plan_id (used by the autosave on ingredient_aliases_manage.html
# itself, which may be viewing a non-active plan via its own tab switcher) ---

def test_api_set_ingredient_nutrition_accepts_explicit_plan_id_for_a_membership(client, app, make_user):
    from models import PlanMembership, db
    from services.nutrition import get_nutrition_entry

    other_user_id, other_plan_id = make_user("Andere")
    with app.app_context():
        db.session.add(PlanMembership(plan_id=other_plan_id, user_id=client.user_id, is_starred=False))
        db.session.commit()

    resp = client.post("/api/ingredient-nutrition/set", json={
        "name": "Reis", "reference_unit": "g", "protein": 3, "carbs": 28, "fat": 0.3,
        "plan_id": other_plan_id,
    })
    assert resp.status_code == 200

    with app.app_context():
        assert get_nutrition_entry(other_plan_id, "Reis").protein == 3
        assert get_nutrition_entry(client.plan_id, "Reis") is None


def test_api_set_ingredient_nutrition_ignores_plan_id_without_membership(client, app, make_user):
    from services.nutrition import get_nutrition_entry

    _, foreign_plan_id = make_user("Fremd")

    resp = client.post("/api/ingredient-nutrition/set", json={
        "name": "Reis", "reference_unit": "g", "protein": 3, "carbs": 28, "fat": 0.3,
        "plan_id": foreign_plan_id,
    })
    assert resp.status_code == 200

    with app.app_context():
        assert get_nutrition_entry(foreign_plan_id, "Reis") is None
        assert get_nutrition_entry(client.plan_id, "Reis").protein == 3


def _recipe_nutrition(app, recipe_id):
    from models import Recipe, db

    with app.app_context():
        recipe = db.session.get(Recipe, recipe_id)
        return recipe.calories, recipe.protein, recipe.carbs, recipe.fat


def test_api_set_ingredient_nutrition_recomputes_recipes_using_it(client, app, make_recipe):
    recipe_id = make_recipe("Reispfanne", servings=2, ingredients=[
        {"name": "Reis", "amount": 200, "unit": "g"},
        {"name": "Paprika", "amount": 1, "unit": "Stk"},
    ])
    other_id = make_recipe("Salat", servings=1, calories=50, protein=1.0, ingredients=[
        {"name": "Gurke", "amount": 1, "unit": "Stk"},
    ])

    client.post("/api/ingredient-nutrition/set", json={
        "name": "reis", "reference_unit": "g", "protein": 3, "carbs": 28, "fat": 0.3,
    })

    # 200 g for 2 servings = 100 g per serving.
    assert _recipe_nutrition(app, recipe_id) == (127, 3.0, 28.0, 0.3)
    assert _recipe_nutrition(app, other_id)[:2] == (50, 1.0)


def test_api_set_ingredient_nutrition_recomputes_through_alias(client, app, make_recipe):
    from services.ingredient_aliases import set_alias

    with app.app_context():
        set_alias(client.plan_id, "Spaghetti", "Nudeln")
    recipe_id = make_recipe("Spaghetti Bolognese", servings=1, ingredients=[
        {"name": "Spaghetti", "amount": 100, "unit": "g"},
    ])

    client.post("/api/ingredient-nutrition/set", json={
        "name": "Nudeln", "reference_unit": "g", "protein": 12, "carbs": 70, "fat": 1.5,
    })
    assert _recipe_nutrition(app, recipe_id)[1:] == (12.0, 70.0, 1.5)


def test_api_set_ingredient_nutrition_keeps_manual_recipe_values(client, app, make_recipe):
    recipe_id = make_recipe("Handgerechnet", servings=1, nutrition_override=True,
                            calories=500, protein=10.0, carbs=50.0, fat=20.0,
                            ingredients=[{"name": "Reis", "amount": 100, "unit": "g"}])

    client.post("/api/ingredient-nutrition/set", json={
        "name": "Reis", "reference_unit": "g", "protein": 3, "carbs": 28, "fat": 0.3,
    })
    assert _recipe_nutrition(app, recipe_id) == (500, 10.0, 50.0, 20.0)


def test_api_set_ingredient_alias_recomputes_recipe_nutrition(client, app, make_recipe):
    from services.nutrition import set_nutrition

    with app.app_context():
        set_nutrition(client.plan_id, "Nudeln", reference_unit="g", protein=12, carbs=70, fat=1.5)
    recipe_id = make_recipe("Penne Arrabiata", servings=1, ingredients=[
        {"name": "Penne", "amount": 100, "unit": "g"},
    ])

    client.post("/api/ingredient-alias/set", json={"raw_name": "Penne", "canonical_name": "Nudeln"})
    assert _recipe_nutrition(app, recipe_id)[1:] == (12.0, 70.0, 1.5)

    # Removing the alias again drops the reference.
    client.post("/api/ingredient-alias/set", json={"raw_name": "Penne", "canonical_name": "Penne"})
    assert _recipe_nutrition(app, recipe_id) == (0, 0.0, 0.0, 0.0)
