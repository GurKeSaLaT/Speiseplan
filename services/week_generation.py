"""The balanced-category-assignment + recipe-selection orchestration
behind "(re-)create a whole week" (see routes/plan/pages.py:
week_generate(), which parses the submitted form, calls generate_week()
below, and persists the result - this module holds only the selection
logic itself, no form parsing/database writes).
"""

from collections import Counter

from models import Category, Recipe
from services.planning import assign_balanced_categories, choose_recipe
from services.recipe_visibility import visible_recipes_query


def generate_week(plan, dates, excluded_days, day_recipe_ids, day_side_recipe_ids):
    """Takes over the days fixed by the caller (routes/plan/pages.py:
    week_generate(), from the week_create_view() form) unchanged, rolls
    the remaining main dishes in a balanced way to fill the rest, and
    returns the result as (final_plan, final_side_plan) - two lists with
    one entry per weekday (index 0=Monday...6=Sunday), NOT yet persisted
    to PlanDay/PlanDaySide rows (that's the caller's job, see there).

    Parameters:
    - plan: the active Plan (restricts the recipe pool, see
      services/recipe_visibility.py: visible_recipes_query()).
    - dates: the 7 real calendar dates of this week (see
      services/planning.py: week_dates_for()) - only used here for
      reference_date in the soft repetition weighting (step 5 below), the
      day INDEX (0-6) is what all other parameters key by.
    - excluded_days: set of day indices marked "excluded" (no main dish).
    - day_recipe_ids: {day index -> main dish recipe ID (string)} for
      days the user fixed explicitly in the form.
    - day_side_recipe_ids: {day index -> list of side dish recipe IDs
      (strings)} - ALWAYS possibly present regardless of exclusion status
      (an excluded day, i.e. no main dish, can still have fixed side
      dishes).

    Flow in four steps (numbered in the code, continuing the numbering
    from week_generate()'s own step 1, form parsing, which happens before
    this function is called):

    2./2b. The recipe IDs referenced in the form are looked up in ONE
       database query per list (instead of one query per day) and
       entered into final_plan (a list with 7 entries, None = nothing
       assigned yet) or final_side_plan (a list of 7 LISTS of recipes).
       used_recipe_ids collects all already fixed MAIN DISH IDs along the
       way, so they aren't assigned twice during the automatic fill-in in
       step 5. Side dishes are deliberately NEVER rolled automatically -
       only fixed side dishes end up in the plan at creation time;
       everything else runs via the dice/pencil buttons on the finished
       plan page (see routes/plan/day_actions_sides.py: add_side/
       reroll_one_side/set_one_side).

    3. days_to_fill: the day indices that are neither excluded nor
       already fixed - exactly the ones the next two steps still need to
       fill.

    4. For each of these days, a CATEGORY (not yet a recipe) is
       determined via assign_balanced_categories() - see
       services/planning.py for the balance/neighborhood logic. Already
       fixed days are factored in as a "preload" (preexisting_counts), so
       the category distribution stays balanced across the ENTIRE week,
       not just across the newly filled days.

    5. For each day, a concrete recipe from the assigned category is
       then rolled (choose_recipe); if that category has no matching
       candidates left, a category-independent roll is made instead, so
       that SOME recipe ends up in the plan rather than none at all.
    """
    all_categories = Category.query.filter_by(plan_id=plan.id).all()

    # 2. Look up fixed main dishes by their ID
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

    # 2b. Look up fixed additional dishes (side dishes) by their IDs -
    # now a LIST of recipes per day instead of at most a single one.
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

    # 3. Which days still need to be filled automatically?
    days_to_fill = [i for i in range(7) if i not in excluded_days and final_plan[i] is None]

    # 4. Determine category per day to fill (see docstring above)
    preexisting_counts = Counter(
        final_plan[day_index].category_id
        for day_index in day_recipe_ids
        if final_plan[day_index] is not None
    )
    category_by_day = assign_balanced_categories(
        all_categories, days_to_fill, final_plan, preexisting_counts=preexisting_counts
    )

    # 5. Fill remaining days with matching, not-yet-used main dishes.
    # reference_date=dates[day_index] activates the soft repetition
    # weighting in choose_recipe() (see services/planning.py) - recipes
    # that have already been used often in the weeks BEFORE exactly this
    # calendar day are thereby rolled less often (but never made
    # impossible).
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
