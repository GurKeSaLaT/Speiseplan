"""Tests for services/nutrition.py: nutrition lookup/storage logic per
canonical ingredient, as well as the automatic recipe nutrition calculation
from the ingredients (compute_recipe_nutrition). Calories are never stored
or entered directly, but always computed from protein/carbs/fat (Atwater
rule of thumb, see compute_calories())."""


def test_compute_calories_applies_atwater_rule():
    from services.nutrition import compute_calories

    # 4 kcal per g protein/carbs, 9 kcal per g fat.
    assert compute_calories(10, 20, 5) == 10 * 4 + 20 * 4 + 5 * 9


def test_compute_calories_treats_none_as_zero():
    from services.nutrition import compute_calories

    assert compute_calories(None, None, None) == 0
    assert compute_calories(10, None, None) == 40


def test_set_and_get_nutrition_entry(app, test_plan_id):
    from services.nutrition import get_nutrition_entry, set_nutrition

    with app.app_context():
        set_nutrition(test_plan_id, "Nudeln", reference_unit="g", protein=12, carbs=70, fat=1.5)
        entry = get_nutrition_entry(test_plan_id, "Nudeln")
        assert entry is not None
        assert entry.protein == 12
        assert entry.reference_unit == "g"


def test_set_nutrition_forces_fixed_reference_basis(app, test_plan_id):
    """reference_amount is no longer a parameter (see services/nutrition.py:
    REFERENCE_BASES) - g/ml -> always 100, Stk -> always 1, regardless of
    what a (manipulated) request might otherwise specify."""
    from services.nutrition import set_nutrition

    with app.app_context():
        entry_g = set_nutrition(test_plan_id, "Mehl", reference_unit="g", protein=10, carbs=70, fat=1)
        assert entry_g.reference_amount == 100

        entry_ml = set_nutrition(test_plan_id, "Milch", reference_unit="ml", protein=3.3, carbs=4.8, fat=3.6)
        assert entry_ml.reference_amount == 100

        entry_stk = set_nutrition(test_plan_id, "Ei", reference_unit="Stk", protein=6.5, carbs=0.6, fat=5.3)
        assert entry_stk.reference_amount == 1


def test_set_nutrition_rejects_unknown_reference_unit(app, test_plan_id):
    """A value outside of g/ml/Stk (e.g. "Becher", "Dose", an empty
    string) falls back to "g" instead of being accepted."""
    from services.nutrition import set_nutrition

    with app.app_context():
        entry = set_nutrition(test_plan_id, "Joghurt", reference_unit="Becher", protein=5, carbs=4, fat=3)
        assert entry.reference_unit == "g"
        assert entry.reference_amount == 100


def test_set_nutrition_is_idempotent_per_canonical_name(app, test_plan_id):
    from models import IngredientNutrition
    from services.nutrition import set_nutrition

    with app.app_context():
        set_nutrition(test_plan_id, "Reis", reference_unit="g", protein=1, carbs=1, fat=1)
        set_nutrition(test_plan_id, "Reis", reference_unit="g", protein=3, carbs=28, fat=0.3)
        assert IngredientNutrition.query.filter_by(canonical_name="Reis").count() == 1
        entry = IngredientNutrition.query.filter_by(canonical_name="Reis").first()
        assert entry.protein == 3
        assert entry.carbs == 28


def test_get_nutrition_entry_resolves_through_alias(app, test_plan_id):
    from services.ingredient_aliases import set_alias
    from services.nutrition import get_nutrition_entry, set_nutrition

    with app.app_context():
        set_alias(test_plan_id, "Spaghetti", "Nudeln")
        set_nutrition(test_plan_id, "Nudeln", reference_unit="g", protein=12, carbs=70, fat=1.5)

        entry = get_nutrition_entry(test_plan_id, "Spaghetti")
        assert entry is not None
        assert entry.canonical_name == "Nudeln"


def test_get_nutrition_entry_missing_returns_none(app, test_plan_id):
    from services.nutrition import get_nutrition_entry

    with app.app_context():
        assert get_nutrition_entry(test_plan_id, "Unbekannt") is None


def test_get_all_nutrition_entries_shape(app, test_plan_id):
    """calories is not a stored value here, but computed for display
    from protein/carbs/fat (see compute_calories())."""
    from services.nutrition import get_all_nutrition_entries, set_nutrition

    with app.app_context():
        set_nutrition(test_plan_id, "Öl", reference_unit="ml", protein=0, carbs=0, fat=100)
        entries = get_all_nutrition_entries(test_plan_id, )
        assert entries["Öl"] == {
            "reference_amount": 100, "reference_unit": "ml",
            "calories": 900,  # 100g fat * 9 kcal/g
            "protein": 0.0, "carbs": 0.0, "fat": 100.0,
        }


def test_list_alias_canonical_names_only_returns_alias_targets(app, test_plan_id):
    from services.ingredient_aliases import set_alias
    from services.nutrition import list_alias_canonical_names

    with app.app_context():
        set_alias(test_plan_id, "Spaghetti", "Nudeln")
        set_alias(test_plan_id, "Fusilli", "Nudeln")
        set_alias(test_plan_id, "Olivenöl", "Öl")
        assert list_alias_canonical_names(test_plan_id, ) == ["Nudeln", "Öl"]


def test_infer_reference_unit_uses_most_common_unit(app, test_plan_id, make_recipe):
    from services.nutrition import infer_reference_unit

    make_recipe("A", ingredients=[{"name": "Zucker", "amount": 100, "unit": "g"}])
    make_recipe("B", ingredients=[{"name": "Zucker", "amount": 200, "unit": "g"}])
    make_recipe("C", ingredients=[{"name": "Zucker", "amount": 1, "unit": "TL"}])

    with app.app_context():
        assert infer_reference_unit(test_plan_id, "Zucker") == "g"


def test_infer_reference_unit_falls_back_to_stk_for_container_units(app, test_plan_id, make_recipe):
    """Container/count units like "Bund"/"Dose"/an empty unit are not
    suitable for a 100g/100ml reference - infer_reference_unit(test_plan_id, )
    must therefore never return them raw, only g/ml/Stk (see
    services/nutrition.py: REFERENCE_BASES)."""
    from services.nutrition import infer_reference_unit

    make_recipe("A", ingredients=[{"name": "Frühlingszwiebel", "amount": 3, "unit": ""}])
    make_recipe("B", ingredients=[{"name": "Frühlingszwiebel", "amount": 1, "unit": "Bund"}])

    with app.app_context():
        assert infer_reference_unit(test_plan_id, "Frühlingszwiebel") == "Stk"


def test_infer_reference_unit_recognizes_volume_family(app, test_plan_id, make_recipe):
    from services.nutrition import infer_reference_unit

    make_recipe("A", ingredients=[{"name": "Sahne", "amount": 200, "unit": "ml"}])
    make_recipe("B", ingredients=[{"name": "Sahne", "amount": 1, "unit": "EL"}])  # -> 15 ml canonical

    with app.app_context():
        assert infer_reference_unit(test_plan_id, "Sahne") == "ml"


def test_infer_reference_unit_defaults_to_g_when_unused(app, test_plan_id):
    from services.nutrition import infer_reference_unit

    with app.app_context():
        assert infer_reference_unit(test_plan_id, "Nie Verwendet") == "g"


def test_compute_recipe_nutrition_basic(app, test_plan_id):
    from services.nutrition import compute_recipe_nutrition, set_nutrition

    with app.app_context():
        set_nutrition(test_plan_id, "Mehl", reference_unit="g", protein=10, carbs=70, fat=1)
        result = compute_recipe_nutrition(test_plan_id, 
            [{"name": "Mehl", "amount": 200, "unit": "g"}], servings=2
        )
        # 200g @ (10/70/1 per 100g) / 2 servings = 10/70/1 per serving.
        # calories computed from that (Atwater): (10+70)*4 + 1*9 = 329.
        assert result == {"calories": 329, "protein": 10.0, "carbs": 70.0, "fat": 1.0}


def test_compute_recipe_nutrition_sums_multiple_ingredients(app, test_plan_id):
    from services.nutrition import compute_recipe_nutrition, set_nutrition

    with app.app_context():
        set_nutrition(test_plan_id, "Mehl", reference_unit="g", protein=10, carbs=70, fat=1)
        set_nutrition(test_plan_id, "Zucker", reference_unit="g", protein=0, carbs=100, fat=0)
        result = compute_recipe_nutrition(test_plan_id, 
            [
                {"name": "Mehl", "amount": 100, "unit": "g"},
                {"name": "Zucker", "amount": 50, "unit": "g"},
            ],
            servings=1,
        )
        assert result["carbs"] == 120.0  # 70 + 50
        assert result["calories"] == 529  # (10+120)*4 + 1*9


def test_compute_recipe_nutrition_skips_ingredient_without_entry(app, test_plan_id):
    from services.nutrition import compute_recipe_nutrition

    with app.app_context():
        result = compute_recipe_nutrition(test_plan_id, 
            [{"name": "Unbekannt", "amount": 100, "unit": "g"}], servings=1
        )
        assert result == {"calories": 0, "protein": 0.0, "carbs": 0.0, "fat": 0.0}


def test_compute_recipe_nutrition_skips_mismatched_unit_family(app, test_plan_id):
    from services.nutrition import compute_recipe_nutrition, set_nutrition

    with app.app_context():
        # Reference in ml (e.g. a liquid), but the recipe states the
        # ingredient in g - deliberately skipped conservatively instead of
        # guessed/wrongly converted (see the compute_recipe_nutrition
        # docstring).
        set_nutrition(test_plan_id, "Öl", reference_unit="ml", protein=0, carbs=0, fat=100)
        result = compute_recipe_nutrition(test_plan_id, 
            [{"name": "Öl", "amount": 100, "unit": "g"}], servings=1
        )
        assert result["calories"] == 0


def test_compute_recipe_nutrition_treats_piece_spellings_as_stk(app, test_plan_id):
    """Various spellings for piece counts (chefkoch import: "Stück",
    "Zehe", "Scheibe", an empty unit) should all match against a
    "Stk" reference (see services/nutrition.py: _PIECE_LIKE_UNITS) -
    only for nutrition matching, not for the shopping list."""
    from services.nutrition import compute_recipe_nutrition, set_nutrition

    with app.app_context():
        set_nutrition(test_plan_id, "Ei", reference_unit="Stk", protein=6.5, carbs=0.6, fat=5.3)
        for spelling in ("Stk", "stk", "Stück", "STÜCK", "", "  "):
            result = compute_recipe_nutrition(test_plan_id, 
                [{"name": "Ei", "amount": 2, "unit": spelling}], servings=1
            )
            assert result["calories"] == 152, f"Einheit {spelling!r} sollte matchen"


def test_compute_recipe_nutrition_treats_container_units_as_stk(app, test_plan_id):
    """"Stk" is deliberately defined broadly (see services/nutrition.py:
    module docstring) - Dose/Becher/Bund/Prise/Päckchen also count as 1 Stk,
    calibrated to this specific ingredient (e.g. "1 Stk Kidneybohnen" = 1 can)."""
    from services.nutrition import compute_recipe_nutrition, set_nutrition

    with app.app_context():
        set_nutrition(test_plan_id, "Kidneybohnen", reference_unit="Stk", protein=21, carbs=55, fat=1.2)
        for spelling in ("Dose", "dose", "Becher", "Bund", "Prise", "Msp.", "Päckchen", "Packung"):
            result = compute_recipe_nutrition(test_plan_id, 
                [{"name": "Kidneybohnen", "amount": 1, "unit": spelling}], servings=1
            )
            assert result["calories"] == 315, f"Einheit {spelling!r} sollte matchen"


def test_compute_recipe_nutrition_stk_reference_does_not_match_mass_unit(app, test_plan_id):
    from services.nutrition import compute_recipe_nutrition, set_nutrition

    with app.app_context():
        set_nutrition(test_plan_id, "Ei", reference_unit="Stk", protein=6.5, carbs=0.6, fat=5.3)
        result = compute_recipe_nutrition(test_plan_id, 
            [{"name": "Ei", "amount": 100, "unit": "g"}], servings=1
        )
        assert result["calories"] == 0


def test_compute_recipe_nutrition_resolves_alias(app, test_plan_id):
    from services.ingredient_aliases import set_alias
    from services.nutrition import compute_recipe_nutrition, set_nutrition

    with app.app_context():
        set_alias(test_plan_id, "Spaghetti", "Nudeln")
        set_nutrition(test_plan_id, "Nudeln", reference_unit="g", protein=12, carbs=70, fat=1.5)
        result = compute_recipe_nutrition(test_plan_id, 
            [{"name": "Spaghetti", "amount": 100, "unit": "g"}], servings=1
        )
        assert result["calories"] == 342


def test_compute_recipe_nutrition_defaults_servings_to_one(app, test_plan_id):
    from services.nutrition import compute_recipe_nutrition, set_nutrition

    with app.app_context():
        set_nutrition(test_plan_id, "Mehl", reference_unit="g", protein=10, carbs=70, fat=1)
        result = compute_recipe_nutrition(test_plan_id, 
            [{"name": "Mehl", "amount": 100, "unit": "g"}], servings=0
        )
        assert result["calories"] == 329


def test_compute_recipe_nutrition_accepts_ingredient_objects(app, test_plan_id, make_recipe):
    from models import Recipe, db
    from services.nutrition import compute_recipe_nutrition, set_nutrition

    with app.app_context():
        set_nutrition(test_plan_id, "Reis", reference_unit="g", protein=3, carbs=28, fat=0.3)

    recipe_id = make_recipe("Reisgericht", ingredients=[{"name": "Reis", "amount": 200, "unit": "g"}])
    with app.app_context():
        recipe = db.session.get(Recipe, recipe_id)
        result = compute_recipe_nutrition(test_plan_id, recipe.ingredients, servings=1)
        assert result["calories"] == 253
