"""Selection logic for generating a whole week (form parsing and saving
live in routes/plan/pages.py: week_generate())."""

from collections import Counter

from models import Category, Recipe
from services.planning import assign_balanced_categories, choose_recipe
from services.recipe_visibility import visible_recipes_query


def generate_week(plan, dates, excluded_days, day_recipe_ids, day_side_recipe_ids):
    """Returns (final_plan, final_side_plan), indexed 0=Friday..6=Thursday.

    Pinned main dishes and sides are kept; every other non-excluded day gets
    a balanced category (counting the pinned days too), then a recipe from
    it - or from any category if that one has nothing left. Sides are never
    generated. Recipe ids arrive as strings from the form.
    """
    all_categories = Category.query.filter_by(plan_id=plan.id).all()

    final_plan = [None] * 7
    used_recipe_ids = set()

    if day_recipe_ids:
        unique_ids = list(set(day_recipe_ids.values()))
        recipes_by_id = {str(r.id): r for r in visible_recipes_query(plan.id).filter(Recipe.id.in_(unique_ids)).all()}
        for day_index, rid in day_recipe_ids.items():
            recipe = recipes_by_id.get(rid)
            if recipe:
                final_plan[day_index] = recipe
                used_recipe_ids.add(recipe.id)

    final_side_plan = [[] for _ in range(7)]

    if day_side_recipe_ids:
        unique_side_ids = list({rid for rids in day_side_recipe_ids.values() for rid in rids})
        side_recipes_by_id = {
            str(r.id): r for r in visible_recipes_query(plan.id).filter(Recipe.id.in_(unique_side_ids)).all()
        }
        for day_index, rids in day_side_recipe_ids.items():
            for rid in rids:
                recipe = side_recipes_by_id.get(rid)
                if recipe:
                    final_side_plan[day_index].append(recipe)

    days_to_fill = [i for i in range(7) if i not in excluded_days and final_plan[i] is None]

    preexisting_counts = Counter(
        final_plan[day_index].category_id
        for day_index in day_recipe_ids
        if final_plan[day_index] is not None
    )
    category_by_day = assign_balanced_categories(
        all_categories, days_to_fill, final_plan, preexisting_counts=preexisting_counts
    )

    for day_index, needed_cat_id in category_by_day.items():
        chosen = choose_recipe(
            is_side_dish=False, exclude_ids=used_recipe_ids, plan_id=plan.id, category_id=needed_cat_id,
            reference_date=dates[day_index]
        )
        if not chosen:
            chosen = choose_recipe(
                is_side_dish=False, exclude_ids=used_recipe_ids, plan_id=plan.id, reference_date=dates[day_index]
            )

        if chosen:
            final_plan[day_index] = chosen
            used_recipe_ids.add(chosen.id)

    return final_plan, final_side_plan
