"""Tests für models.py: Beziehungen, Cascade-Deletes und Constraints, die
sich nicht schon indirekt über die Service-/Routen-Tests abdecken lassen."""
from datetime import date

import pytest
from sqlalchemy.exc import IntegrityError


def test_recipe_ingredient_cascade_delete(app, make_recipe):
    from models import Ingredient, Recipe, db

    recipe_id = make_recipe(
        "Zu löschen",
        ingredients=[{"name": "Salz", "amount": 1, "unit": "TL"}],
    )
    with app.app_context():
        assert Ingredient.query.filter_by(recipe_id=recipe_id).count() == 1
        db.session.delete(db.session.get(Recipe, recipe_id))
        db.session.commit()
        assert Ingredient.query.filter_by(recipe_id=recipe_id).count() == 0


def test_recipe_season_cascade_delete(app, make_recipe):
    from models import Recipe, RecipeSeason, db

    recipe_id = make_recipe("Saisonal")
    with app.app_context():
        db.session.add(RecipeSeason(recipe_id=recipe_id, start_month=6, start_day=1, end_month=8, end_day=31))
        db.session.commit()
        assert RecipeSeason.query.filter_by(recipe_id=recipe_id).count() == 1

        db.session.delete(db.session.get(Recipe, recipe_id))
        db.session.commit()
        assert RecipeSeason.query.filter_by(recipe_id=recipe_id).count() == 0


def test_plan_day_side_cascade_delete(app, make_recipe, make_user):
    from models import PlanDay, PlanDaySide, db

    recipe_id = make_recipe("Beilage", is_side_dish=True)
    _, plan_id = make_user("PlanOwner")
    with app.app_context():
        pd = PlanDay(plan_id=plan_id, date=date(2026, 6, 15), servings=2)
        db.session.add(pd)
        db.session.flush()
        db.session.add(PlanDaySide(plan_day_id=pd.id, recipe_id=recipe_id))
        db.session.commit()

        pd_id = pd.id
        assert PlanDaySide.query.filter_by(plan_day_id=pd_id).count() == 1

        db.session.delete(db.session.get(PlanDay, pd_id))
        db.session.commit()
        assert PlanDaySide.query.filter_by(plan_day_id=pd_id).count() == 0


def test_plan_day_can_have_multiple_sides(app, make_recipe, make_user):
    from models import PlanDay, PlanDaySide, db

    side_a = make_recipe("Beilage A", is_side_dish=True)
    side_b = make_recipe("Beilage B", is_side_dish=True)
    _, plan_id = make_user("PlanOwner")
    with app.app_context():
        pd = PlanDay(plan_id=plan_id, date=date(2026, 6, 16), servings=2)
        db.session.add(pd)
        db.session.flush()
        db.session.add(PlanDaySide(plan_day_id=pd.id, recipe_id=side_a))
        db.session.add(PlanDaySide(plan_day_id=pd.id, recipe_id=side_b))
        db.session.commit()

        reloaded = db.session.get(PlanDay, pd.id)
        assert len(reloaded.sides) == 2


def test_plan_day_date_is_unique_per_plan(app, make_user):
    """(plan_id, date) ist zusammengesetzt eindeutig (siehe models.py:
    PlanDay.__table_args__) - zwei Zeilen für DENSELBEN Plan+Tag sind nicht
    erlaubt, zwei verschiedene Pläne dürfen aber unabhängig voneinander
    jeweils eine eigene Zeile für denselben Kalendertag haben (siehe
    test_plan_day_date_can_repeat_across_different_plans unten)."""
    from models import PlanDay, db

    _, plan_id = make_user("PlanOwner")
    with app.app_context():
        db.session.add(PlanDay(plan_id=plan_id, date=date(2026, 6, 15), servings=2))
        db.session.commit()

        db.session.add(PlanDay(plan_id=plan_id, date=date(2026, 6, 15), servings=2))
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()


def test_plan_day_date_can_repeat_across_different_plans(app, make_user):
    from models import PlanDay, db

    _, plan_a = make_user("PlanA")
    _, plan_b = make_user("PlanB")
    with app.app_context():
        db.session.add(PlanDay(plan_id=plan_a, date=date(2026, 6, 15), servings=2))
        db.session.add(PlanDay(plan_id=plan_b, date=date(2026, 6, 15), servings=2))
        db.session.commit()  # darf NICHT scheitern

        assert PlanDay.query.filter_by(date=date(2026, 6, 15)).count() == 2


def test_category_name_is_unique_per_plan(app, test_plan_id):
    from models import Category, db

    with app.app_context():
        db.session.add(Category(plan_id=test_plan_id, name="Doppelt"))
        db.session.commit()

        db.session.add(Category(plan_id=test_plan_id, name="Doppelt"))
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()


def test_category_name_can_repeat_across_different_plans(app, test_plan_id, make_user):
    from models import Category, db

    _, other_plan_id = make_user("Andere")
    with app.app_context():
        db.session.add(Category(plan_id=test_plan_id, name="Doppelt"))
        db.session.add(Category(plan_id=other_plan_id, name="Doppelt"))
        db.session.commit()  # darf NICHT scheitern
        assert Category.query.filter_by(name="Doppelt").count() == 2


def test_recipe_defaults(app, test_plan_id, make_category):
    from models import Recipe, db

    cat_id = make_category()
    with app.app_context():
        recipe = Recipe(name="Minimal", owner_plan_id=test_plan_id, category_id=cat_id)
        db.session.add(recipe)
        db.session.commit()

        assert recipe.is_side_dish is False
        assert recipe.is_favorite is False
        assert recipe.servings == 2
        assert recipe.calories == 0
        assert recipe.nutrition_override is False


def test_ingredient_nutrition_canonical_name_is_unique_per_plan(app, test_plan_id):
    from models import IngredientNutrition, db

    with app.app_context():
        db.session.add(IngredientNutrition(plan_id=test_plan_id, canonical_name="Nudeln", protein=12))
        db.session.commit()

        db.session.add(IngredientNutrition(plan_id=test_plan_id, canonical_name="Nudeln", protein=99))
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()


def test_ingredient_nutrition_defaults(app, test_plan_id):
    from models import IngredientNutrition, db

    with app.app_context():
        entry = IngredientNutrition(plan_id=test_plan_id, canonical_name="Reis")
        db.session.add(entry)
        db.session.commit()

        assert entry.reference_amount == 100
        assert entry.reference_unit == "g"
        assert entry.protein == 0.0
