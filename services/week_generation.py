"""Selection logic for generating a whole week (form parsing and saving
live in routes/plan/pages.py: week_generate())."""

from collections import Counter

from models import Category, Recipe
from services.leftovers import ingredient_names_by_recipe
from services.planning import (
    assign_balanced_categories, choose_recipe, recent_usage_counts, weighted_recipe_choice,
)
from services.recipe_visibility import visible_recipes_query
from services.seasons import recipe_available_now


def generate_week(plan, dates, excluded_days, day_recipe_ids, day_side_recipe_ids, leftover_names=None):
    """Returns (final_plan, final_side_plan), indexed 0=Friday..6=Thursday.

    Pinned main dishes and sides are kept. Leftovers (canonical ingredient
    names) not already used by a pinned dish come next: the earliest free
    days get recipes that use them up (see fill_leftover_days). Every other
    non-excluded day gets a balanced category (counting pinned and leftover
    days too), then a recipe from it - or from any category if that one has
    nothing left. Sides are never generated. Recipe ids arrive as strings
    from the form.
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

    if leftover_names:
        fill_leftover_days(plan.id, dates, days_to_fill, final_plan, final_side_plan, used_recipe_ids, leftover_names)
        days_to_fill = [i for i in days_to_fill if final_plan[i] is None]

    preexisting_counts = Counter(
        recipe.category_id for i, recipe in enumerate(final_plan)
        if recipe is not None and i not in excluded_days
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


def fill_leftover_days(plan_id, dates, days_to_fill, final_plan, final_side_plan, used_recipe_ids, leftover_names):
    """Puts recipes that use up leftovers on the earliest free days
    (leftovers don't keep). Greedy: each day gets a recipe covering the most
    still-unused leftovers, ties drawn like choose_recipe() (seasonal
    first, weighted by favorites and recent use). Stops when every leftover
    is used or no recipe uses any of the rest. Leftovers already in a
    pinned main or side dish count as used. Mutates final_plan and
    used_recipe_ids; returns the set of leftovers nothing uses."""
    pinned = [r for r in final_plan if r is not None] + [r for sides in final_side_plan for r in sides]
    pinned_names = ingredient_names_by_recipe(plan_id, {r.id for r in pinned})
    remaining = set(leftover_names)
    for names in pinned_names.values():
        remaining -= names
    if not remaining or not days_to_fill:
        return remaining

    candidates = visible_recipes_query(plan_id).filter(
        Recipe.is_side_dish.is_(False), ~Recipe.id.in_(used_recipe_ids)
    ).all()
    names_by_recipe = ingredient_names_by_recipe(plan_id, {r.id for r in candidates})

    for day_index in sorted(days_to_fill):
        if not remaining:
            break
        scored = [
            (recipe, len(names_by_recipe.get(recipe.id, set()) & remaining))
            for recipe in candidates if recipe.id not in used_recipe_ids
        ]
        best_score = max((score for _, score in scored), default=0)
        if best_score == 0:
            break
        best = [recipe for recipe, score in scored if score == best_score]
        best = [r for r in best if recipe_available_now(r)] or best
        usage_counts = recent_usage_counts([r.id for r in best], dates[day_index], False, plan_id)
        chosen = weighted_recipe_choice(best, usage_counts)

        final_plan[day_index] = chosen
        used_recipe_ids.add(chosen.id)
        remaining -= names_by_recipe.get(chosen.id, set())
    return remaining
