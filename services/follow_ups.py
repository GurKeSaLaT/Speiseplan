"""Linked recipes: a dish (A) is cooked for more people and a few days later
a follow-up dish (B) is made from what's left (RecipeFollowUp).

Rules (decided with the household):
- Only A is ever drawn at random; recipes that are some recipe's follow-up
  are left out of every random pool (follow_up_target_ids).
- When A is planned, B goes on the earliest free day in A's window
  (min_days..max_days later), preferred over normal filling. No free day
  -> A without B. B is a main dish or a side as its recipe says: a main
  dish needs a day without one, a side is added as an extra side on any
  day that isn't excluded (no check whether it fits that day's main dish).
  Several follow-ups -> one of those with a free day is
  drawn (favorites/recent use weighted like choose_recipe).
- A day in a week that doesn't exist yet is free unless something is
  already pending there; B then waits as a PendingFollowUp and is offered
  as a fixed dish when that week is created.
- A is a main dish or a side: a side placed by hand, by reroll or pinned
  in the create form places its follow-up just like a main dish.
- Replacing or removing A frees B's day (a new B may take it, otherwise it
  is rolled normally) or removes B if it is a side; replacing or removing
  B only drops the coupling, so A is no longer bought for B's servings.
- Couplings follow the dishes on swaps and when a side is moved.

A coupling (Kopplung) is stored on the follow-up dish and references its
source dish (models.calendar.CoupledDish), not a day: the main dish of a
PlanDay or a PlanDaySide.
"""

from collections import defaultdict, namedtuple
from datetime import date, timedelta

from flask_babel import gettext as _

from models import db, PendingFollowUp, PlanDay, PlanDaySide, Recipe
from services.planning import (  # noqa: F401 - follow_up_target_ids re-exported
    follow_up_target_ids, friday_of, recent_usage_counts, reroll_choice, weighted_recipe_choice, week_dates_for,
)
from services.recipe_trees import complete_tree
from services.recipe_visibility import visible_recipes_query

MAX_WINDOW_DAYS = 14


def follow_up_options(recipe, plan_id, exclude_ids=()):
    """recipe's follow-up links whose follow-up dish plan_id can see."""
    if recipe is None or not recipe.follow_ups:
        return []
    visible = {
        r.id for r in visible_recipes_query(plan_id).filter(
            Recipe.id.in_([link.follow_up_recipe_id for link in recipe.follow_ups])
        )
    }
    return [
        link for link in recipe.follow_ups
        if link.follow_up_recipe_id in visible and link.follow_up_recipe_id not in exclude_ids
        and link.follow_up_recipe_id != recipe.id
    ]


def pick_follow_up(recipe, plan_id, source_date, is_free, exclude_ids=()):
    """(follow-up Recipe, date) for recipe planned on source_date, or None.
    is_free(date, is_side) says whether a day can take a main dish (is_side
    False) or a side; each option uses the earliest free day of its window."""
    candidates = {}
    for link in follow_up_options(recipe, plan_id, exclude_ids):
        low = max(1, link.min_days)
        high = min(MAX_WINDOW_DAYS, max(low, link.max_days))
        for offset in range(low, high + 1):
            day = source_date + timedelta(days=offset)
            if is_free(day, link.follow_up_recipe.is_side_dish):
                candidates[link.follow_up_recipe] = day
                break
    if not candidates:
        return None
    recipes = list(candidates)
    usage = recent_usage_counts([r.id for r in recipes], source_date, False, plan_id)
    chosen = weighted_recipe_choice(recipes, usage)
    return chosen, candidates[chosen]


def source_dish(dish):
    """The dish (a PlanDay for its main dish, or a PlanDaySide) that dish -
    a PlanDay's main dish, PlanDaySide or PendingFollowUp - is coupled to,
    or None."""
    if dish.source_side_id is not None:
        return db.session.get(PlanDaySide, dish.source_side_id)
    if dish.source_day_id is not None:
        return db.session.get(PlanDay, dish.source_day_id)
    return None


def couple(dish, source):
    """Couples dish to source (a PlanDay for its main dish, a PlanDaySide, or
    None to uncouple). Returns True if dish was coupled before."""
    was_coupled = dish.is_coupled
    dish.source_day_id = source.id if isinstance(source, PlanDay) else None
    dish.source_side_id = source.id if isinstance(source, PlanDaySide) else None
    return was_coupled


def _dish_date(dish):
    return dish.date if isinstance(dish, PlanDay) else dish.day.date


def _dish_recipe(dish: PlanDay | PlanDaySide) -> Recipe | None:
    return dish.main_recipe if isinstance(dish, PlanDay) else dish.recipe


def _dish_name(dish):
    recipe = _dish_recipe(dish)
    return recipe.name if recipe else ''


def _coupled_to(model: type, source: PlanDay | PlanDaySide):
    """Filter for the rows of model (PlanDay, PlanDaySide or
    PendingFollowUp) coupled to source."""
    if isinstance(source, PlanDay):
        return model.source_day_id == source.id
    return model.source_side_id == source.id


def has_follow_ups(source: PlanDay | PlanDaySide) -> bool:
    """Whether any dish or pending follow-up is coupled to source."""
    return any(
        model.query.filter(_coupled_to(model, source)).first() is not None
        for model in (PlanDay, PlanDaySide, PendingFollowUp)
    )


def week_exists(plan_id, day):
    start = friday_of(day)
    return PlanDay.query.filter(
        PlanDay.plan_id == plan_id, PlanDay.date >= start, PlanDay.date < start + timedelta(days=7)
    ).first() is not None


def live_slot_free(plan_id, day, is_side=False):
    """Free for a follow-up in the stored plan: an existing day that isn't
    excluded and, for a main dish, has none yet; or a day of a
    not-yet-created week with no main dish pending (any number of sides
    may wait there)."""
    plan_day = PlanDay.query.filter_by(plan_id=plan_id, date=day).first()
    if plan_day is not None:
        return not plan_day.excluded and (is_side or plan_day.main_recipe_id is None)
    if week_exists(plan_id, day):
        return False
    return is_side or PendingFollowUp.query.filter_by(plan_id=plan_id, date=day, is_side=False).first() is None


def assign_follow_up(plan_id, follow_up_recipe, day, source):
    """Puts the follow-up on day, coupled to source (the PlanDay whose main
    dish it is made from, or a PlanDaySide): as the main dish, or for a side
    recipe as an extra side, if that week exists, else as pending. No commit."""
    is_side = follow_up_recipe.is_side_dish
    plan_day = PlanDay.query.filter_by(plan_id=plan_id, date=day).first()
    if plan_day is None:
        dish = PendingFollowUp(plan_id=plan_id, date=day, recipe_id=follow_up_recipe.id, is_side=is_side)
        db.session.add(dish)
    elif is_side:
        add_side(plan_day, follow_up_recipe.id, source)
        return
    else:
        dish = plan_day
        plan_day.main_recipe_id = follow_up_recipe.id
        plan_day.cooked = False
    couple(dish, source)


def add_side(plan_day, recipe_id, source=None):
    """Adds a side to plan_day, coupled to source if given. No commit."""
    side = PlanDaySide(plan_day_id=plan_day.id, recipe_id=recipe_id)
    couple(side, source)
    db.session.add(side)
    return side


def place_follow_up(plan_id: int, source: PlanDay | PlanDaySide) -> date | None:
    """Plans a follow-up for source (a PlanDay's main dish or a
    PlanDaySide) if one fits, never one already in source's week; returns
    its date or None. No commit."""
    db.session.flush()
    picked = pick_follow_up(
        _dish_recipe(source), plan_id, _dish_date(source),
        lambda day, is_side: live_slot_free(plan_id, day, is_side), _week_recipe_ids(plan_id, _dish_date(source)),
    )
    if picked is None:
        return None
    recipe, day = picked
    assign_follow_up(plan_id, recipe, day, source)
    return day


# freed_days: PlanDays whose follow-up main dish was cleared, for re-planning;
# released: whether anything at all was released.
Release = namedtuple('Release', 'freed_days released')


def release_follow_ups(source: PlanDay | PlanDaySide) -> Release:
    """source (a PlanDay's main dish or a PlanDaySide) goes away: the days
    of its follow-up main dishes lose their dish (returned, for
    re-planning), its follow-up sides and pending follow-ups are dropped.
    No commit."""
    freed = PlanDay.query.filter(_coupled_to(PlanDay, source)).all()
    for plan_day in freed:
        couple(plan_day, None)
        plan_day.main_recipe_id = None
        plan_day.cooked = False
    dropped = PlanDaySide.query.filter(_coupled_to(PlanDaySide, source)).delete()
    dropped += PendingFollowUp.query.filter(_coupled_to(PendingFollowUp, source)).delete()
    return Release(freed, bool(freed) or dropped > 0)


def replace_main_dish(plan_id: int, plan_day: PlanDay, new_recipe: Recipe | None) -> bool:
    """Sets plan_day's main dish (None clears it) and keeps links right:
    plan_day stops being a follow-up; if it was a source, its follow-ups
    are released; a new source gets a follow-up (possibly on a released
    day); released days still empty are rolled anew (refill_released).
    Returns True if any coupling changed (the client then reloads)."""
    changed = couple(plan_day, None)
    db.session.flush()  # a new plan_day gets its id
    freed, released = release_follow_ups(plan_day)
    changed = changed or released

    plan_day.main_recipe_id = new_recipe.id if new_recipe else None
    plan_day.cooked = False
    db.session.flush()
    if new_recipe is not None:
        db.session.refresh(plan_day)
        if place_follow_up(plan_id, plan_day) is not None:
            changed = True
    refill_released(plan_id, freed)
    return changed


def replace_side_dish(plan_id: int, side: PlanDaySide, new_recipe: Recipe) -> bool:
    """The side counterpart of replace_main_dish: side stops being a
    follow-up, its own follow-ups are released, the new recipe places a
    follow-up if it has one, released days are rolled anew. Returns True if
    any coupling changed. No commit."""
    changed = couple(side, None)
    freed, released = release_follow_ups(side)
    side.recipe_id = new_recipe.id
    side.cooked = False
    db.session.flush()
    db.session.refresh(side)
    if place_follow_up(plan_id, side) is not None:
        changed = True
    refill_released(plan_id, freed)
    return changed or released


def remove_side_dish(plan_id: int, side: PlanDaySide) -> bool:
    """Deletes side; its follow-ups are released (released days rolled
    anew). Returns True if any coupling changed. No commit."""
    changed = side.is_coupled
    freed, released = release_follow_ups(side)
    db.session.delete(side)
    db.session.flush()
    refill_released(plan_id, freed)
    return changed or released


def reroll_refill(plan_day: PlanDay) -> None:
    """Rolls a normal dish for a day whose follow-up dish was released
    (services/planning.py: reroll_choice). No commit."""
    chosen = reroll_choice(plan_day.plan_id, plan_day.date)
    plan_day.main_recipe_id = chosen.id if chosen else None
    plan_day.cooked = False


def refill_released(plan_id: int, freed_days: list[PlanDay]) -> None:
    """Rolls a dish for released follow-up days that are still empty
    (reroll_refill); a refilled dish with follow-ups gets one placed like
    any planned dish. No commit."""
    for freed_day in freed_days:
        if freed_day.main_recipe_id is None and not freed_day.excluded:
            reroll_refill(freed_day)
            db.session.flush()
            if freed_day.main_recipe_id is not None:
                db.session.refresh(freed_day)
                place_follow_up(plan_id, freed_day)


def _week_recipe_ids(plan_id, day):
    """Main dishes and sides of the week containing day."""
    rows = week_days(plan_id, week_dates_for(friday_of(day)))
    return {pd.main_recipe_id for pd in rows if pd.main_recipe_id} | {side.recipe_id for pd in rows for side in pd.sides}


def move_couplings_on_swap(day_a, day_b):
    """Call after swapping the main dishes of day_a and day_b: their own
    couplings travel with them, and dishes coupled to one of the two main
    dishes now point at the other day. Couplings to sides need nothing,
    sides keep their id when they move. Returns True if any coupling was
    involved."""
    involved = day_a.is_coupled or day_b.is_coupled
    source_a, source_b = source_dish(day_a), source_dish(day_b)
    couple(day_a, source_b)
    couple(day_b, source_a)

    followers = {
        day.id: [
            dish for model in (PlanDay, PlanDaySide, PendingFollowUp)
            for dish in model.query.filter_by(source_day_id=day.id).all()
        ]
        for day in (day_a, day_b)
    }
    # The swapped days' own couplings were already exchanged above; a dish
    # that follows its own (now swapped) source is fixed up by the same mapping.
    for dish in followers[day_a.id]:
        dish.source_day_id = day_b.id
    for dish in followers[day_b.id]:
        dish.source_day_id = day_a.id
    return involved or bool(followers[day_a.id] or followers[day_b.id])


def _day_label(day):
    from services.planning import DAY_NAMES
    return f"{DAY_NAMES[(day.weekday() - 4) % 7]}, {day.strftime('%d.%m.')}"


IncomingFollowUp = namedtuple('IncomingFollowUp', 'day_index recipe is_side source source_name')


def incoming_follow_ups(plan_id, dates):
    """[IncomingFollowUp] for the week `dates`, ordered by day: pending
    follow-ups plus stored main dishes and sides coupled to a dish from
    before this week. The create form offers them as fixed dishes (a main
    dish per day at most, any number of sides)."""
    def coupled(model):
        return model.source_day_id.isnot(None) | model.source_side_id.isnot(None)

    found = [
        (row.date, row.recipe, row.is_side, row)
        for row in PendingFollowUp.query.filter(PendingFollowUp.plan_id == plan_id, PendingFollowUp.date.in_(dates))
    ]
    found += [
        (plan_day.date, plan_day.main_recipe, False, plan_day)
        for plan_day in PlanDay.query.filter(
            PlanDay.plan_id == plan_id, PlanDay.date.in_(dates), PlanDay.main_recipe_id.isnot(None), coupled(PlanDay))
    ]
    found += [
        (side.day.date, side.recipe, True, side)
        for side in PlanDaySide.query.join(PlanDay, PlanDaySide.plan_day_id == PlanDay.id).filter(
            PlanDay.plan_id == plan_id, PlanDay.date.in_(dates), coupled(PlanDaySide))
    ]
    result = []
    for day, recipe, is_side, dish in found:
        source = source_dish(dish)
        if source is not None and _dish_date(source) < dates[0]:
            result.append(IncomingFollowUp(dates.index(day), recipe, is_side, source, _dish_name(source)))
    return sorted(result, key=lambda entry: (entry.day_index, entry.is_side))


def week_days(plan_id, dates):
    return PlanDay.query.filter(PlanDay.plan_id == plan_id, PlanDay.date.in_(dates)).all()


# A dish or pending follow-up coupled to a source dish, for notes and amounts.
FollowUpDish = namedtuple('FollowUpDish', 'date name servings pending')


def _follow_ups_by_source(days: list[PlanDay]) -> dict:
    """The follow-ups of the main dishes and sides of days, in any week or
    still pending: {PlanDay or PlanDaySide: [FollowUpDish]}, by date."""
    sources = {('day', pd.id): pd for pd in days} | {('side', side.id): side for pd in days for side in pd.sides}

    def coupled(model):
        return (model.source_day_id.in_([i for kind, i in sources if kind == 'day'])
                | model.source_side_id.in_([i for kind, i in sources if kind == 'side']))

    def source_of(dish):
        return sources[('side', dish.source_side_id) if dish.source_side_id is not None else ('day', dish.source_day_id)]

    result = defaultdict(list)
    for plan_day in PlanDay.query.filter(coupled(PlanDay), PlanDay.main_recipe_id.isnot(None)):
        result[source_of(plan_day)].append(
            FollowUpDish(plan_day.date, plan_day.main_recipe.name, plan_day.servings, False))
    for side in PlanDaySide.query.filter(coupled(PlanDaySide)):
        result[source_of(side)].append(FollowUpDish(side.day.date, side.recipe.name, side.day.servings, False))
    for row in PendingFollowUp.query.filter(coupled(PendingFollowUp)):
        result[source_of(row)].append(FollowUpDish(row.date, row.recipe.name, row.servings, True))
    for dishes in result.values():
        dishes.sort(key=lambda dish: dish.date)
    return result


def week_follow_up_data(plan_id, dates, ordered_days, day_labels):
    """plan_data entries for the follow-up notes on the week page (plan.js):
    followUpOf[i]: the source dish (main dish or side) of day i's follow-up
    main dish, or null; followUpsOut[i]: day i's main dish's follow-ups
    (main dishes and sides), in this week (index set) or elsewhere;
    sideFollowUpsOut: the same per source side, by side id. Amounts come
    from week_shopping_servings."""
    def place(day):
        in_week = day in dates
        return {
            "date": day.isoformat(),
            "index": dates.index(day) if in_week else None,
            "label": day_labels[dates.index(day)] if in_week else _day_label(day),
        }

    def notes(dishes):
        return [
            {**place(dish.date), **({"index": None} if dish.pending else {}), "name": dish.name, "pending": dish.pending}
            for dish in dishes
        ]

    follow_up_of = []
    for plan_day in ordered_days:
        source = source_dish(plan_day) if plan_day and plan_day.main_recipe_id else None
        follow_up_of.append(None if source is None else {**place(_dish_date(source)), "name": _dish_name(source)})

    days = [pd for pd in ordered_days if pd is not None]
    follow_ups = _follow_ups_by_source(days)
    return {
        "followUpOf": follow_up_of,
        "followUpsOut": [notes(follow_ups.get(pd, [])) if pd else [] for pd in ordered_days],
        "sideFollowUpsOut": {
            str(side.id): notes(follow_ups[side]) for pd in days for side in pd.sides if side in follow_ups
        },
    }


def week_shopping_servings(plan_id, day):
    """Per day of the week containing day: {"main": ..., "sides": {side id:
    ...}} with the servings each dish is bought for (plan.js:
    shoppingServings; the client only multiplies). A source dish (main
    dish or side) is bought for its own servings plus those of its
    follow-up dishes, in any week or still pending (followUpServings); a
    coupled follow-up dish skips its pre-cooked ingredients. main is None
    on a day without a main dish.

    Also sent with every day action that places a dish or changes servings
    (plan.js: applyShoppingServings); removing a dish needs none, since a
    coupling change makes the page reload."""
    dates = week_dates_for(friday_of(day))
    days = {pd.date: pd for pd in week_days(plan_id, dates)}
    follow_ups = _follow_ups_by_source(list(days.values()))

    def entry(own_servings, source, skip_precooked):
        follow_up_servings = sum(dish.servings for dish in follow_ups.get(source, ()))
        return {
            "servings": own_servings + follow_up_servings,
            "followUpServings": follow_up_servings, "skipPrecooked": skip_precooked,
        }

    result = []
    for day in dates:
        plan_day = days.get(day)
        if plan_day is None:
            result.append({"main": None, "sides": {}})
            continue
        main = None
        if plan_day.main_recipe_id is not None:
            main = entry(plan_day.servings, plan_day, source_dish(plan_day) is not None)
        result.append({"main": main, "sides": {
            str(side.id): entry(plan_day.servings, side, side.is_coupled) for side in plan_day.sides
        }})
    return result


class FollowUpRuleError(ValueError):
    """A follow-up link that breaks the recipe tree rules (ADR 0001); the
    message names the recipes involved and is shown in the recipe form."""


def _sources_by_follow_up():
    """follow-up recipe id -> its source recipe ids, over all links in the
    database (not only those visible to one plan). More than one source
    only in data from before the tree rules."""
    from models import RecipeFollowUp

    sources = {}
    for source_id, follow_up_id in db.session.query(RecipeFollowUp.recipe_id, RecipeFollowUp.follow_up_recipe_id):
        sources.setdefault(follow_up_id, []).append(source_id)
    return sources


def _ancestor_paths(recipe_id, sources):
    """ancestor id -> the recipe ids from that ancestor down to recipe_id."""
    paths = {recipe_id: [recipe_id]}
    queue = [recipe_id]
    while queue:
        current = queue.pop(0)
        for source_id in sources.get(current, ()):
            if source_id not in paths:
                paths[source_id] = [source_id] + paths[current]
                queue.append(source_id)
    del paths[recipe_id]
    return paths


def unavailable_follow_up_ids(recipe_id):
    """Recipes that recipe_id (None = a new recipe) may not newly take as
    follow-up: itself, its ancestors (cycle) and recipes that already have
    another source recipe."""
    sources = _sources_by_follow_up()
    taken = {follow_up_id for follow_up_id, source_ids in sources.items() if set(source_ids) - {recipe_id}}
    if recipe_id is None:
        return taken
    return taken | {recipe_id} | set(_ancestor_paths(recipe_id, sources))


def _check_tree_rules(recipe, new_ids, plan_id):
    """Raises FollowUpRuleError for the first of new_ids (follow-ups recipe
    doesn't have yet) that would close a cycle or give a follow-up recipe a
    second source. Links recipe already has are left alone - rule breaks
    from before the rules are the migration's business. Recipes plan_id
    can't see aren't named."""
    sources = _sources_by_follow_up()
    ancestors = _ancestor_paths(recipe.id, sources) if recipe.id is not None else {}
    names = {recipe.id: recipe.name}

    def name(recipe_id):
        if recipe_id not in names:
            visible = visible_recipes_query(plan_id).filter(Recipe.id == recipe_id).first()
            names[recipe_id] = visible.name if visible else _("a recipe in another plan")
        return names[recipe_id]

    for follow_up_id in new_ids:
        if follow_up_id == recipe.id or follow_up_id in ancestors:
            cycle = [recipe.id] + ancestors.get(follow_up_id, [recipe.id])
            raise FollowUpRuleError(_("This follow-up link would close a cycle: %(cycle)s.",
                                      cycle=" → ".join(name(i) for i in cycle)))
        other_sources = [i for i in sources.get(follow_up_id, ()) if i != recipe.id]
        if other_sources:
            raise FollowUpRuleError(_(
                "%(follow_up)s is already the follow-up dish of %(source)s, "
                "and a follow-up recipe can only have one source recipe.",
                follow_up=name(follow_up_id), source=name(other_sources[0])))


def remove_tree_rule_breaks():
    """Repairs links from before the tree rules: read in id order, a link is
    removed if its follow-up recipe already has a source recipe or it would
    close a cycle, so the older link always wins. Returns the removed links
    as (link id, source id, follow-up id, reason). No commit."""
    from models import RecipeFollowUp

    source_of = {}
    removed = []
    for link in RecipeFollowUp.query.order_by(RecipeFollowUp.id).all():
        source_id, follow_up_id = link.recipe_id, link.follow_up_recipe_id
        if follow_up_id in source_of:
            reason = f"second source (keeps {source_of[follow_up_id]})"
        else:
            # Kept links give every recipe at most one source, so the
            # ancestors of source_id form a single chain.
            ancestor_id = source_id
            while ancestor_id is not None and ancestor_id != follow_up_id:
                ancestor_id = source_of.get(ancestor_id)
            if ancestor_id is None:
                source_of[follow_up_id] = source_id
                continue
            reason = "closes a cycle"
        removed.append((link.id, source_id, follow_up_id, reason))
        db.session.delete(link)
    return removed


def save_follow_up_links(recipe, form, plan_id):
    """Replaces recipe's follow-ups from the recipe form's parallel
    fu_recipe[] / fu_min[] / fu_max[] lists. Unknown or duplicate
    references are skipped; days are clamped to 1..MAX_WINDOW_DAYS with
    max >= min. A link that breaks the recipe tree rules (self-link, cycle,
    second source) raises FollowUpRuleError before anything changes. A new
    link that merges two recipe trees links the merged tree into every plan
    either was in (services/recipe_trees.py). No commit."""
    from models import RecipeFollowUp

    def as_int(raw, default):
        try:
            return int(raw)
        except (TypeError, ValueError):
            return default

    recipe_ids = form.getlist('fu_recipe[]')
    mins = form.getlist('fu_min[]')
    maxs = form.getlist('fu_max[]')
    wanted = {}
    for i, raw_id in enumerate(recipe_ids):
        follow_up_id = as_int(raw_id, None)
        if follow_up_id is None or follow_up_id in wanted:
            continue
        low = min(MAX_WINDOW_DAYS, max(1, as_int(mins[i] if i < len(mins) else None, 2)))
        high = min(MAX_WINDOW_DAYS, max(low, as_int(maxs[i] if i < len(maxs) else None, 3)))
        wanted[follow_up_id] = (low, high)
    valid = {
        r.id for r in visible_recipes_query(plan_id).filter(Recipe.id.in_(list(wanted)))
    } if wanted else set()
    if recipe.id in wanted:
        valid.add(recipe.id)  # reported as a cycle rather than skipped

    existing = {link.follow_up_recipe_id: link for link in recipe.follow_ups}
    new_ids = [i for i in wanted if i in valid and i not in existing]
    with db.session.no_autoflush:
        _check_tree_rules(recipe, new_ids, plan_id)

    links = []
    for follow_up_id, (low, high) in wanted.items():
        if follow_up_id not in valid:
            continue
        # Kept links are updated in place: a new row for the same pair
        # would be inserted before the old one is deleted (unique constraint).
        link = existing.get(follow_up_id) or RecipeFollowUp(follow_up_recipe_id=follow_up_id)
        link.min_days, link.max_days = low, high
        links.append(link)
    recipe.follow_ups = links
    if new_ids:
        complete_tree(recipe.id)


def forget_recipe(recipe_id):
    """Before deleting a recipe: drop links that would dangle - follow-up
    definitions pointing at it, couplings to main dishes and sides where it
    is the dish (those follow-ups stay as normal dishes), its own couplings
    and pending entries. No commit."""
    from models import RecipeFollowUp

    RecipeFollowUp.query.filter_by(follow_up_recipe_id=recipe_id).delete()
    sources = PlanDay.query.filter_by(main_recipe_id=recipe_id).all()
    sources += PlanDaySide.query.filter_by(recipe_id=recipe_id).all()
    for source in sources:
        for model in (PlanDay, PlanDaySide):
            for dish in model.query.filter(_coupled_to(model, source)).all():
                couple(dish, None)
        PendingFollowUp.query.filter(_coupled_to(PendingFollowUp, source)).delete()
        couple(source, None)
    PendingFollowUp.query.filter_by(recipe_id=recipe_id).delete()
