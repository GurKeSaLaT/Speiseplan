"""Tests für services/nutrition.py: Nährwert-Nachschlage/-Speicher-Logik
je kanonischer Zutat sowie die automatische Rezept-Nährwert-Berechnung
aus den Zutaten (compute_recipe_nutrition)."""


def test_set_and_get_nutrition_entry(app):
    from services.nutrition import get_nutrition_entry, set_nutrition

    with app.app_context():
        set_nutrition("Nudeln", reference_amount=100, reference_unit="g", calories=350, protein=12, carbs=70, fat=1.5)
        entry = get_nutrition_entry("Nudeln")
        assert entry is not None
        assert entry.calories == 350
        assert entry.reference_unit == "g"


def test_set_nutrition_is_idempotent_per_canonical_name(app):
    from models import IngredientNutrition
    from services.nutrition import set_nutrition

    with app.app_context():
        set_nutrition("Reis", reference_amount=100, reference_unit="g", calories=100, protein=1, carbs=1, fat=1)
        set_nutrition("Reis", reference_amount=100, reference_unit="g", calories=130, protein=3, carbs=28, fat=0.3)
        assert IngredientNutrition.query.filter_by(canonical_name="Reis").count() == 1
        assert IngredientNutrition.query.filter_by(canonical_name="Reis").first().calories == 130


def test_get_nutrition_entry_resolves_through_alias(app):
    from services.ingredient_aliases import set_alias
    from services.nutrition import get_nutrition_entry, set_nutrition

    with app.app_context():
        set_alias("Spaghetti", "Nudeln")
        set_nutrition("Nudeln", reference_amount=100, reference_unit="g", calories=350, protein=12, carbs=70, fat=1.5)

        entry = get_nutrition_entry("Spaghetti")
        assert entry is not None
        assert entry.canonical_name == "Nudeln"


def test_get_nutrition_entry_missing_returns_none(app):
    from services.nutrition import get_nutrition_entry

    with app.app_context():
        assert get_nutrition_entry("Unbekannt") is None


def test_get_all_nutrition_entries_shape(app):
    from services.nutrition import get_all_nutrition_entries, set_nutrition

    with app.app_context():
        set_nutrition("Öl", reference_amount=100, reference_unit="ml", calories=884, protein=0, carbs=0, fat=100)
        entries = get_all_nutrition_entries()
        assert entries["Öl"] == {
            "reference_amount": 100, "reference_unit": "ml",
            "calories": 884, "protein": 0.0, "carbs": 0.0, "fat": 100.0,
        }


def test_list_alias_canonical_names_only_returns_alias_targets(app):
    from services.ingredient_aliases import set_alias
    from services.nutrition import list_alias_canonical_names

    with app.app_context():
        set_alias("Spaghetti", "Nudeln")
        set_alias("Fusilli", "Nudeln")
        set_alias("Olivenöl", "Öl")
        assert list_alias_canonical_names() == ["Nudeln", "Öl"]


def test_infer_reference_unit_uses_most_common_unit(app, make_recipe):
    from services.nutrition import infer_reference_unit

    make_recipe("A", ingredients=[{"name": "Zucker", "amount": 100, "unit": "g"}])
    make_recipe("B", ingredients=[{"name": "Zucker", "amount": 200, "unit": "g"}])
    make_recipe("C", ingredients=[{"name": "Zucker", "amount": 1, "unit": "TL"}])

    with app.app_context():
        assert infer_reference_unit("Zucker") == "g"


def test_infer_reference_unit_defaults_to_g_when_unused(app):
    from services.nutrition import infer_reference_unit

    with app.app_context():
        assert infer_reference_unit("Nie Verwendet") == "g"


def test_compute_recipe_nutrition_basic(app):
    from services.nutrition import compute_recipe_nutrition, set_nutrition

    with app.app_context():
        set_nutrition("Mehl", reference_amount=100, reference_unit="g", calories=350, protein=10, carbs=70, fat=1)
        result = compute_recipe_nutrition(
            [{"name": "Mehl", "amount": 200, "unit": "g"}], servings=2
        )
        # 200g @350kcal/100g = 700 kcal insgesamt / 2 Portionen = 350.
        assert result == {"calories": 350, "protein": 10.0, "carbs": 70.0, "fat": 1.0}


def test_compute_recipe_nutrition_sums_multiple_ingredients(app):
    from services.nutrition import compute_recipe_nutrition, set_nutrition

    with app.app_context():
        set_nutrition("Mehl", reference_amount=100, reference_unit="g", calories=350, protein=10, carbs=70, fat=1)
        set_nutrition("Zucker", reference_amount=100, reference_unit="g", calories=400, protein=0, carbs=100, fat=0)
        result = compute_recipe_nutrition(
            [
                {"name": "Mehl", "amount": 100, "unit": "g"},
                {"name": "Zucker", "amount": 50, "unit": "g"},
            ],
            servings=1,
        )
        assert result["calories"] == 550  # 350 + 200
        assert result["carbs"] == 120.0  # 70 + 50


def test_compute_recipe_nutrition_skips_ingredient_without_entry(app):
    from services.nutrition import compute_recipe_nutrition

    with app.app_context():
        result = compute_recipe_nutrition(
            [{"name": "Unbekannt", "amount": 100, "unit": "g"}], servings=1
        )
        assert result == {"calories": 0, "protein": 0.0, "carbs": 0.0, "fat": 0.0}


def test_compute_recipe_nutrition_skips_mismatched_unit_family(app):
    from services.nutrition import compute_recipe_nutrition, set_nutrition

    with app.app_context():
        # Referenz in ml (z.B. eine Flüssigkeit), Rezept nennt die Zutat
        # aber in g - bewusst konservativ übersprungen statt geraten/
        # falsch umgerechnet (siehe compute_recipe_nutrition-Docstring).
        set_nutrition("Öl", reference_amount=100, reference_unit="ml", calories=884, protein=0, carbs=0, fat=100)
        result = compute_recipe_nutrition(
            [{"name": "Öl", "amount": 100, "unit": "g"}], servings=1
        )
        assert result["calories"] == 0


def test_compute_recipe_nutrition_resolves_alias(app):
    from services.ingredient_aliases import set_alias
    from services.nutrition import compute_recipe_nutrition, set_nutrition

    with app.app_context():
        set_alias("Spaghetti", "Nudeln")
        set_nutrition("Nudeln", reference_amount=100, reference_unit="g", calories=350, protein=12, carbs=70, fat=1.5)
        result = compute_recipe_nutrition(
            [{"name": "Spaghetti", "amount": 100, "unit": "g"}], servings=1
        )
        assert result["calories"] == 350


def test_compute_recipe_nutrition_defaults_servings_to_one(app):
    from services.nutrition import compute_recipe_nutrition, set_nutrition

    with app.app_context():
        set_nutrition("Mehl", reference_amount=100, reference_unit="g", calories=350, protein=10, carbs=70, fat=1)
        result = compute_recipe_nutrition(
            [{"name": "Mehl", "amount": 100, "unit": "g"}], servings=0
        )
        assert result["calories"] == 350


def test_compute_recipe_nutrition_accepts_ingredient_objects(app, make_recipe):
    from models import Recipe, db
    from services.nutrition import compute_recipe_nutrition, set_nutrition

    with app.app_context():
        set_nutrition("Reis", reference_amount=100, reference_unit="g", calories=130, protein=3, carbs=28, fat=0.3)

    recipe_id = make_recipe("Reisgericht", ingredients=[{"name": "Reis", "amount": 200, "unit": "g"}])
    with app.app_context():
        recipe = db.session.get(Recipe, recipe_id)
        result = compute_recipe_nutrition(recipe.ingredients, servings=1)
        assert result["calories"] == 260
