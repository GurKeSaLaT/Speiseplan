"""Core planning logic: week/date helpers, category balancing for
auto-filled weeks, and weighted recipe selection. Used by routes/plan/."""

import random
from collections import Counter
from datetime import date, timedelta

from flask_babel import lazy_gettext as _l

from models import db, Recipe, PlanDay, PlanDaySide
from services.recipe_visibility import visible_recipes_query
from services.seasons import recipe_available_now
from services.ingredient_aliases import normalize_ingredient_name
from services.settings import get_display_units
from services.units import convert_for_display

# The household's week runs Friday-Thursday, not ISO Monday-Sunday.
# lazy_gettext because this is evaluated at import time, outside a request.
DAY_NAMES = [_l('Friday'), _l('Saturday'), _l('Sunday'), _l('Monday'), _l('Tuesday'), _l('Wednesday'), _l('Thursday')]

# Favorites are this many times as likely to be drawn (a weighting, not a filter).
FAVORITE_WEIGHT = 3

REPETITION_LOOKBACK_WEEKS = 8


def recent_usage_counts(recipe_ids, reference_date, is_side_dish, plan_id):
    """{recipe_id: uses} within REPETITION_LOOKBACK_WEEKS before
    reference_date, for one plan. reference_date is the day being planned,
    not today, since past/future weeks can be planned too."""
    if not recipe_ids:
        return {}
    since = reference_date - timedelta(weeks=REPETITION_LOOKBACK_WEEKS)

    if is_side_dish:
        rows = (
            db.session.query(PlanDaySide.recipe_id)
            .join(PlanDay, PlanDaySide.plan_day_id == PlanDay.id)
            .filter(
                PlanDay.plan_id == plan_id, PlanDay.date >= since, PlanDay.date < reference_date,
                PlanDaySide.recipe_id.in_(recipe_ids)
            )
            .all()
        )
        return Counter(rid for (rid,) in rows)

    rows = PlanDay.query.filter(
        PlanDay.plan_id == plan_id, PlanDay.date >= since, PlanDay.date < reference_date,
        PlanDay.main_recipe_id.in_(recipe_ids)
    ).all()
    return Counter(pd.main_recipe_id for pd in rows)


def weighted_recipe_choice(recipes, usage_counts=None):
    """random.choice() weighted by favorite status and a soft repetition
    penalty of 1/(recent uses + 1) - frequently used recipes get rarer but
    never impossible."""
    usage_counts = usage_counts or {}
    weights = [
        (FAVORITE_WEIGHT if r.is_favorite else 1) / (usage_counts.get(r.id, 0) + 1)
        for r in recipes
    ]
    return random.choices(recipes, weights=weights, k=1)[0]


def friday_of(d):
    """The Friday starting the Friday-Thursday week that d falls in."""
    return d - timedelta(days=(d.weekday() - 4) % 7)


def week_dates_for(start):
    return [start + timedelta(days=i) for i in range(7)]


def parse_iso_date(value):
    """date from "YYYY-MM-DD", or None for invalid input (callers answer 404/400)."""
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def week_neighbor_exclude_ids(day_date, plan_id):
    """Main-dish recipe IDs of the OTHER days in day_date's week. The day
    itself is excluded; callers re-add its current recipe when rerolling."""
    start = friday_of(day_date)
    dates = week_dates_for(start)
    rows = PlanDay.query.filter(PlanDay.plan_id == plan_id, PlanDay.date.in_(dates)).all()
    ids = set()
    for pd in rows:
        if pd.date == day_date:
            continue
        if pd.main_recipe_id:
            ids.add(pd.main_recipe_id)
    return ids


def week_side_recipe_ids(day_date, plan_id):
    """All side-dish recipe IDs in day_date's week, including that day's own
    (a day can have several sides, and a reroll must not return a duplicate)."""
    start = friday_of(day_date)
    dates = week_dates_for(start)
    rows = (
        db.session.query(PlanDaySide.recipe_id)
        .join(PlanDay, PlanDaySide.plan_day_id == PlanDay.id)
        .filter(PlanDay.plan_id == plan_id, PlanDay.date.in_(dates))
        .all()
    )
    return {rid for (rid,) in rows}


def assign_balanced_categories(all_categories, days_to_fill, final_plan, preexisting_counts=None):
    """{day_index: category_id} for each day to fill. Avoids the category of
    a directly neighboring day where possible, then balances counts across
    the week; the neighbor rule is relaxed rather than leaving a day empty."""
    cat_ids = [c.id for c in all_categories]
    if not cat_ids:
        return {}

    counts = Counter(preexisting_counts or {})
    for cid in cat_ids:
        counts.setdefault(cid, 0)

    known_category_by_day = {
        i: final_plan[i].category_id for i in range(7) if final_plan[i] is not None
    }

    assigned = {}
    for day_index in days_to_fill:
        neighbor_cats = {
            known_category_by_day[n] for n in (day_index - 1, day_index + 1)
            if 0 <= n <= 6 and n in known_category_by_day
        }

        # False < True: non-neighbor categories first, then least used.
        def sort_key(cid):
            return (cid in neighbor_cats, counts[cid])

        best_key = min(sort_key(cid) for cid in cat_ids)
        candidates = [cid for cid in cat_ids if sort_key(cid) == best_key]
        choice = random.choice(candidates)

        assigned[day_index] = choice
        counts[choice] += 1
        known_category_by_day[day_index] = choice

    return assigned


def choose_recipe(is_side_dish, exclude_ids, plan_id, category_id=None, prefer_season=True, reference_date=None):
    """Picks one recipe visible to plan_id, or None if nothing is left.

    exclude_ids is the only hard filter. Currently seasonal recipes are
    preferred but never required (falls back to all candidates), and the
    draw is weighted by favorites and recent use before reference_date.
    """
    base_query = visible_recipes_query(plan_id).filter(
        Recipe.is_side_dish.is_(is_side_dish),
        ~Recipe.id.in_(exclude_ids)
    )
    if category_id is not None:
        base_query = base_query.filter(Recipe.category_id == category_id)

    candidates = base_query.all()
    if not candidates:
        return None

    usage_counts = {}
    if reference_date is not None:
        usage_counts = recent_usage_counts([r.id for r in candidates], reference_date, is_side_dish, plan_id)

    if prefer_season:
        seasonal_candidates = [r for r in candidates if recipe_available_now(r)]
        if seasonal_candidates:
            return weighted_recipe_choice(seasonal_candidates, usage_counts)

    return weighted_recipe_choice(candidates, usage_counts)


def jsonify_recipe(recipe, plan_id):
    """Recipe as a JSON-ready dict for the plan page.

    Ingredient names go through plan_id's alias mapping and amounts are
    converted to plan_id's display units - always plan_id's (the viewing
    plan), not the owner's, and always one unit per family, because the
    client-side shopping list merges items by name+unit.
    """
    display_units = get_display_units(plan_id)
    return {
        "id": recipe.id,
        "name": recipe.name,
        "category_name": recipe.category.name,
        "category_id": recipe.category_id,
        "servings": recipe.servings,
        "calories": recipe.calories,
        "protein": recipe.protein,
        "carbs": recipe.carbs,
        "fat": recipe.fat,
        "is_favorite": recipe.is_favorite,
        "source_url": recipe.source_url,
        "instructions": recipe.instructions,
        "ingredients": [
            {
                "name": normalize_ingredient_name(plan_id, ing.name),
                **dict(zip(("amount", "unit"), convert_for_display(ing.amount, ing.unit, display_units))),
                "category": ing.category,
                "is_pantry": ing.is_pantry,
            }
            for ing in recipe.ingredients
        ]
    }


def jsonify_side(plan_day_side, plan_id):
    """jsonify_recipe() plus the PlanDaySide's own id (the slot the frontend
    rerolls/moves/removes) and its cooked flag."""
    data = jsonify_recipe(plan_day_side.recipe, plan_id)
    data['side_id'] = plan_day_side.id
    data['cooked'] = plan_day_side.cooked
    return data
