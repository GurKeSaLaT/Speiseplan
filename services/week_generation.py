"""Selection logic for generating a whole week (form parsing and saving
live in routes/plan/pages.py: week_generate())."""

from collections import Counter, namedtuple
from collections.abc import Collection
from datetime import date

from models import Category, Plan, Recipe
from services.follow_ups import live_slot_free, pick_follow_up
from services.leftovers import ingredient_names_by_recipe
from services.planning import (
    assign_balanced_categories, choose_recipe, follow_up_target_ids, recent_usage_counts,
    weighted_recipe_choice,
)
from services.recipe_visibility import visible_recipes_query
from services.seasons import recipe_available_now

class DishRef(namedtuple('DishRef', 'day side', defaults=(None,))):
    """A source dish in the generated week: the main dish of day `day`
    (side None) or pinned side number `side` of that day."""

    def resolve(self, mains: list, sides: list[list]):
        """The entry this refers to in per-day mains / per-day side lists
        (recipes while generating, stored dishes when saving)."""
        return mains[self.day] if self.side is None else sides[self.day][self.side]


# final_plan / final_side_plan: indexed 0=Friday..6=Thursday; final_side_plan
#   holds the pinned sides only.
# follow_up_couplings: {day index of a follow-up main dish: DishRef of its source dish}.
# side_follow_ups: [(day index, follow-up side Recipe, source DishRef)], extra sides.
# outside_follow_ups: [(date, follow-up Recipe, source DishRef)] beyond this week.
GeneratedWeek = namedtuple(
    'GeneratedWeek', 'final_plan final_side_plan follow_up_couplings side_follow_ups outside_follow_ups')


def generate_week(
    plan: Plan, dates: list[date], excluded_days: set[int], day_recipe_ids: dict[int, str],
    day_side_recipe_ids: dict[int, list[str]], leftover_names: set[str] | None = None,
    incoming_days: Collection[int] = (), incoming_sides: Collection[tuple[int, int]] = (),
) -> GeneratedWeek:
    """Returns a GeneratedWeek.

    Pinned main dishes and sides are kept; incoming_days (day indexes) and
    incoming_sides ((day index, recipe id)) mark pinned dishes that are
    follow-ups of an earlier week's dish, so they place no follow-up of
    their own. Follow-ups of planned dishes take precedence over normal
    filling (services/follow_ups.py): pinned main dishes, then pinned sides
    place theirs first,
    then leftovers are used up on the earliest free days (see
    fill_leftover_days), then every other non-excluded day gets a balanced
    category (counting the days already set) and a recipe from it - or
    from any category if that one has nothing left - placing its follow-up
    as it goes. Sides are never generated, except follow-up sides placed
    on top of a day's sides. Recipe ids arrive as strings from the form.
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
                    used_recipe_ids.add(recipe.id)  # no follow-up side twice in a week

    couplings = {}
    side_follow_ups = []
    outside = []
    outside_taken = set()

    def is_free(day, is_side):
        if dates[0] <= day <= dates[6]:
            i = (day - dates[0]).days
            return i not in excluded_days and (is_side or final_plan[i] is None)
        if day < dates[0] or (day in outside_taken and not is_side):
            return False
        return live_slot_free(plan.id, day, is_side)

    def place_follow_up(source: DishRef) -> None:
        recipe = source.resolve(final_plan, final_side_plan)
        picked = pick_follow_up(recipe, plan.id, dates[source.day], is_free, exclude_ids=used_recipe_ids)
        if picked is None:
            return
        recipe, day = picked
        if not dates[0] <= day <= dates[6]:
            outside.append((day, recipe, source))
            if not recipe.is_side_dish:
                outside_taken.add(day)
            return
        j = (day - dates[0]).days
        if recipe.is_side_dish:
            side_follow_ups.append((j, recipe, source))
        else:
            final_plan[j] = recipe
            couplings[j] = source
        used_recipe_ids.add(recipe.id)

    for i in sorted(day_recipe_ids):
        if final_plan[i] is not None and i not in couplings and i not in incoming_days:
            place_follow_up(DishRef(i))
    for i, sides in enumerate(final_side_plan):
        for k, recipe in enumerate(sides):
            if (i, recipe.id) not in incoming_sides:
                place_follow_up(DishRef(i, k))

    days_to_fill = [i for i in range(7) if i not in excluded_days and final_plan[i] is None]

    if leftover_names:
        fill_leftover_days(
            plan.id, dates, days_to_fill, final_plan, final_side_plan, used_recipe_ids, leftover_names,
            on_pick=lambda day_index: place_follow_up(DishRef(day_index)),
        )
        days_to_fill = [i for i in days_to_fill if final_plan[i] is None]

    preexisting_counts = Counter(
        recipe.category_id for i, recipe in enumerate(final_plan)
        if recipe is not None and i not in excluded_days
    )
    category_by_day = assign_balanced_categories(
        all_categories, days_to_fill, final_plan, preexisting_counts=preexisting_counts
    )

    for day_index in sorted(category_by_day):
        if final_plan[day_index] is not None:  # taken by a follow-up meanwhile
            continue
        needed_cat_id = category_by_day[day_index]
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
            place_follow_up(DishRef(day_index))

    return GeneratedWeek(final_plan, final_side_plan, couplings, side_follow_ups, outside)


def fill_leftover_days(plan_id, dates, days_to_fill, final_plan, final_side_plan, used_recipe_ids, leftover_names,
                       on_pick=None):
    """Puts recipes that use up leftovers on the earliest free days
    (leftovers don't keep). Greedy: each day gets a recipe covering the most
    still-unused leftovers, ties drawn like choose_recipe() (seasonal
    first, weighted by favorites and recent use). Stops when every leftover
    is used or no recipe uses any of the rest. Leftovers already in a
    pinned main or side dish count as used; follow-up dishes are never
    drawn. on_pick(day_index) runs right after each pick (generate_week
    places the follow-up there, before the next leftover day is chosen).
    Mutates final_plan and used_recipe_ids; returns the set of leftovers
    nothing uses."""
    pinned = [r for r in final_plan if r is not None] + [r for sides in final_side_plan for r in sides]
    pinned_names = ingredient_names_by_recipe(plan_id, {r.id for r in pinned})
    remaining = set(leftover_names)
    for names in pinned_names.values():
        remaining -= names
    if not remaining or not days_to_fill:
        return remaining

    candidates = visible_recipes_query(plan_id).filter(
        Recipe.is_side_dish.is_(False), ~Recipe.id.in_(used_recipe_ids | follow_up_target_ids(plan_id))
    ).all()
    names_by_recipe = ingredient_names_by_recipe(plan_id, {r.id for r in candidates})

    for day_index in sorted(days_to_fill):
        if not remaining:
            break
        if final_plan[day_index] is not None:
            continue
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
        if on_pick is not None:
            on_pick(day_index)
    return remaining
