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


def test_plan_day_side_cascade_delete(app, make_recipe):
    from models import PlanDay, PlanDaySide, db

    recipe_id = make_recipe("Beilage", is_side_dish=True)
    with app.app_context():
        pd = PlanDay(date=date(2026, 6, 15), servings=2)
        db.session.add(pd)
        db.session.flush()
        db.session.add(PlanDaySide(plan_day_id=pd.id, recipe_id=recipe_id))
        db.session.commit()

        pd_id = pd.id
        assert PlanDaySide.query.filter_by(plan_day_id=pd_id).count() == 1

        db.session.delete(db.session.get(PlanDay, pd_id))
        db.session.commit()
        assert PlanDaySide.query.filter_by(plan_day_id=pd_id).count() == 0


def test_plan_day_can_have_multiple_sides(app, make_recipe):
    from models import PlanDay, PlanDaySide, db

    side_a = make_recipe("Beilage A", is_side_dish=True)
    side_b = make_recipe("Beilage B", is_side_dish=True)
    with app.app_context():
        pd = PlanDay(date=date(2026, 6, 16), servings=2)
        db.session.add(pd)
        db.session.flush()
        db.session.add(PlanDaySide(plan_day_id=pd.id, recipe_id=side_a))
        db.session.add(PlanDaySide(plan_day_id=pd.id, recipe_id=side_b))
        db.session.commit()

        reloaded = db.session.get(PlanDay, pd.id)
        assert len(reloaded.sides) == 2


def test_plan_day_date_is_unique(app):
    from models import PlanDay, db

    with app.app_context():
        db.session.add(PlanDay(date=date(2026, 6, 15), servings=2))
        db.session.commit()

        db.session.add(PlanDay(date=date(2026, 6, 15), servings=2))
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()


def test_category_name_is_unique(app):
    from models import Category, db

    with app.app_context():
        db.session.add(Category(name="Doppelt"))
        db.session.commit()

        db.session.add(Category(name="Doppelt"))
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()


def test_recipe_defaults(app, make_category):
    from models import Recipe, db

    cat_id = make_category()
    with app.app_context():
        recipe = Recipe(name="Minimal", category_id=cat_id)
        db.session.add(recipe)
        db.session.commit()

        assert recipe.is_side_dish is False
        assert recipe.is_favorite is False
        assert recipe.servings == 2
        assert recipe.calories == 0
        assert recipe.nutrition_override is False


def test_ingredient_nutrition_canonical_name_is_unique(app):
    from models import IngredientNutrition, db

    with app.app_context():
        db.session.add(IngredientNutrition(canonical_name="Nudeln", protein=12))
        db.session.commit()

        db.session.add(IngredientNutrition(canonical_name="Nudeln", protein=99))
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()


def test_ingredient_nutrition_defaults(app):
    from models import IngredientNutrition, db

    with app.app_context():
        entry = IngredientNutrition(canonical_name="Reis")
        db.session.add(entry)
        db.session.commit()

        assert entry.reference_amount == 100
        assert entry.reference_unit == "g"
        assert entry.protein == 0.0
