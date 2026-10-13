"""Linked recipes: a dish (A) is cooked for more people and a few days later
a follow-up dish (B) is made from what's left (RecipeFollowUp).

Rules (decided with the household):
- Only A is ever drawn at random; recipes that are some recipe's follow-up
  are left out of every random pool (follow_up_target_ids).
- When A is planned, B goes on the earliest free day in A's window
  (min_days..max_days later), preferred over normal filling. No free day
  -> A without B. Several follow-ups -> one of those with a free day is
  drawn (favorites/recent use weighted like choose_recipe).
- A day in a week that doesn't exist yet is free unless something is
  already pending there; B then waits as a PendingFollowUp and is offered
  as a fixed dish when that week is created.
- Replacing or removing A frees B's day (a new B may take it, otherwise it
  is rolled normally); replacing B only drops the link, so A is no longer
  bought for B's servings.
- Links follow the dishes on swaps.

A coupling (Kopplung) is stored on the follow-up dish and references its
source dish (models.calendar.CoupledDish), not a day: the main dish of a
PlanDay or a PlanDaySide. So far only main dishes are coupled.
"""

from datetime import timedelta

from flask_babel import gettext as _

from models import db, PendingFollowUp, PlanDay, PlanDaySide, Recipe
from services.planning import (  # noqa: F401 - follow_up_target_ids re-exported
    follow_up_target_ids, friday_of, recent_usage_counts, weighted_recipe_choice, week_dates_for,
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
            Recipe.id.in_([link.follow_up_recipe_id for link in recipe.follow_ups]),
            Recipe.is_side_dish.is_(False),
        )
    }
    return [
        link for link in recipe.follow_ups
        if link.follow_up_recipe_id in visible and link.follow_up_recipe_id not in exclude_ids
        and link.follow_up_recipe_id != recipe.id
    ]


def pick_follow_up(recipe, plan_id, source_date, is_free, exclude_ids=()):
    """(follow-up Recipe, date) for recipe planned on source_date, or None.
    is_free(date) says whether a day can take it; each option uses the
    earliest free day of its window."""
    candidates = {}
    for link in follow_up_options(recipe, plan_id, exclude_ids):
        low = max(1, link.min_days)
        high = min(MAX_WINDOW_DAYS, max(low, link.max_days))
        for offset in range(low, high + 1):
            day = source_date + timedelta(days=offset)
            if is_free(day):
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
    was_coupled = dish.source_day_id is not None or dish.source_side_id is not None
    dish.source_day_id = source.id if isinstance(source, PlanDay) else None
    dish.source_side_id = source.id if isinstance(source, PlanDaySide) else None
    return was_coupled


def _dish_date(dish):
    return dish.date if isinstance(dish, PlanDay) else dish.day.date


def _dish_name(dish):
    recipe = dish.main_recipe if isinstance(dish, PlanDay) else dish.recipe
    return recipe.name if recipe else ''


def week_exists(plan_id, day):
    start = friday_of(day)
    return PlanDay.query.filter(
        PlanDay.plan_id == plan_id, PlanDay.date >= start, PlanDay.date < start + timedelta(days=7)
    ).first() is not None


def live_slot_free(plan_id, day, taken=()):
    """Free for a follow-up in the stored plan: an existing day without a
    main dish that isn't excluded, or a day of a not-yet-created week with
    nothing pending."""
    if day in taken:
        return False
    plan_day = PlanDay.query.filter_by(plan_id=plan_id, date=day).first()
    if plan_day is not None:
        return not plan_day.excluded and plan_day.main_recipe_id is None
    if week_exists(plan_id, day):
        return False
    return PendingFollowUp.query.filter_by(plan_id=plan_id, date=day).first() is None


def assign_follow_up(plan_id, follow_up_recipe, day, source):
    """Puts the follow-up on day as main dish, coupled to source (the
    PlanDay whose main dish it is made from): onto its PlanDay if that week
    exists, else as pending. No commit."""
    plan_day = PlanDay.query.filter_by(plan_id=plan_id, date=day).first()
    if plan_day is not None:
        plan_day.main_recipe_id = follow_up_recipe.id
        plan_day.cooked = False
        couple(plan_day, source)
        return plan_day
    pending = PendingFollowUp(plan_id=plan_id, date=day, recipe_id=follow_up_recipe.id, is_side=False)
    couple(pending, source)
    db.session.add(pending)
    return None


def place_follow_up(plan_id, source_day, exclude_ids=()):
    """Plans a follow-up for source_day's main dish if one fits; returns its
    date or None. No commit."""
    db.session.flush()
    picked = pick_follow_up(
        source_day.main_recipe, plan_id, source_day.date,
        lambda day: live_slot_free(plan_id, day), exclude_ids,
    )
    if picked is None:
        return None
    recipe, day = picked
    assign_follow_up(plan_id, recipe, day, source_day)
    return day


def release_follow_ups(source_day):
    """source_day's main dish goes away: the days of its follow-up dishes
    lose their dish (returned, for re-planning) and pending ones are
    dropped. No commit."""
    freed = PlanDay.query.filter_by(source_day_id=source_day.id).all()
    for plan_day in freed:
        couple(plan_day, None)
        plan_day.main_recipe_id = None
        plan_day.cooked = False
    PendingFollowUp.query.filter_by(source_day_id=source_day.id).delete()
    return freed


def replace_main_dish(plan_id, plan_day, new_recipe, refill):
    """Sets plan_day's main dish (None clears it) and keeps links right:
    plan_day stops being a follow-up; if it was a source, its follow-ups
    are released; a new source gets a follow-up (possibly on a released
    day); released days still empty are filled via refill(plan_day).
    Returns True if any link changed (the client then reloads)."""
    changed = couple(plan_day, None)
    db.session.flush()  # a new plan_day gets its id
    had_pending = PendingFollowUp.query.filter_by(source_day_id=plan_day.id).count() > 0
    freed = release_follow_ups(plan_day)
    changed = changed or had_pending or bool(freed)

    plan_day.main_recipe_id = new_recipe.id if new_recipe else None
    plan_day.cooked = False
    db.session.flush()
    if new_recipe is not None:
        db.session.refresh(plan_day)
        week_ids = _week_main_ids(plan_id, plan_day.date)
        if place_follow_up(plan_id, plan_day, exclude_ids=week_ids) is not None:
            changed = True
    refill_released(plan_id, freed, refill)
    return changed


def refill_released(plan_id, freed_days, refill):
    """Fills released follow-up days that are still empty via
    refill(plan_day); a refilled dish with follow-ups gets one placed like
    any planned dish. No commit."""
    for freed_day in freed_days:
        if freed_day.main_recipe_id is None and not freed_day.excluded:
            refill(freed_day)
            db.session.flush()
            if freed_day.main_recipe_id is not None:
                db.session.refresh(freed_day)
                place_follow_up(plan_id, freed_day, exclude_ids=_week_main_ids(plan_id, freed_day.date))


def _week_main_ids(plan_id, day):
    start = friday_of(day)
    rows = PlanDay.query.filter(
        PlanDay.plan_id == plan_id, PlanDay.date >= start, PlanDay.date < start + timedelta(days=7)
    ).all()
    return {pd.main_recipe_id for pd in rows if pd.main_recipe_id}


def move_links_on_swap(day_a, day_b):
    """Call after swapping the main dishes of day_a and day_b: their own
    couplings travel with them, and dishes coupled to one of the two main
    dishes now point at the other day. Couplings to sides need nothing,
    sides keep their id when they move. Returns True if any coupling was
    involved."""
    coupling_a = (day_a.source_day_id, day_a.source_side_id)
    coupling_b = (day_b.source_day_id, day_b.source_side_id)
    involved = coupling_a != (None, None) or coupling_b != (None, None)
    (day_a.source_day_id, day_a.source_side_id), (day_b.source_day_id, day_b.source_side_id) = coupling_b, coupling_a

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


def incoming_follow_ups(plan_id, dates):
    """{day index: (follow-up Recipe, source dish, source dish name)} for the
    week `dates`: pending follow-ups plus stored days whose main dish is
    coupled to a dish from before this week. The create form offers them
    as fixed dishes."""
    result = {}
    pending = PendingFollowUp.query.filter(
        PendingFollowUp.plan_id == plan_id, PendingFollowUp.date.in_(dates), PendingFollowUp.is_side.is_(False)
    ).all()
    for row in pending:
        source = source_dish(row)
        if source is not None:
            result[dates.index(row.date)] = (row.recipe, source, _dish_name(source))
    coupled_days = PlanDay.query.filter(
        PlanDay.plan_id == plan_id, PlanDay.date.in_(dates), PlanDay.main_recipe_id.isnot(None),
        PlanDay.source_day_id.isnot(None) | PlanDay.source_side_id.isnot(None),
    ).all()
    for plan_day in coupled_days:
        source = source_dish(plan_day)
        if source is not None and _dish_date(source) < dates[0]:
            result[dates.index(plan_day.date)] = (plan_day.main_recipe, source, _dish_name(source))
    return result


def _week_days(plan_id, dates):
    return PlanDay.query.filter(PlanDay.plan_id == plan_id, PlanDay.date.in_(dates)).all()


def week_follow_up_data(plan_id, dates, ordered_days, day_labels):
    """plan_data entries for the follow-up notes on the week page (plan.js):
    followUpOf[i]: the source dish of day i's follow-up dish, or null;
    followUpsOut[i]: day i's dish's follow-ups, in this week (index set) or
    elsewhere. Amounts come from week_shopping_servings."""
    def place(day):
        in_week = day in dates
        return {
            "date": day.isoformat(),
            "index": dates.index(day) if in_week else None,
            "label": day_labels[dates.index(day)] if in_week else _day_label(day),
        }

    follow_up_of = []
    for plan_day in ordered_days:
        source = source_dish(plan_day) if plan_day and plan_day.main_recipe_id else None
        follow_up_of.append(None if source is None else {**place(_dish_date(source)), "name": _dish_name(source)})

    index_of_day = {pd.id: dates.index(pd.date) for pd in _week_days(plan_id, dates)}
    follow_ups_out = [[] for _ in dates]
    coupled_days = PlanDay.query.filter(
        PlanDay.source_day_id.in_(index_of_day), PlanDay.main_recipe_id.isnot(None)
    ).all()
    for plan_day in coupled_days:
        follow_ups_out[index_of_day[plan_day.source_day_id]].append(
            {**place(plan_day.date), "name": plan_day.main_recipe.name, "pending": False})
    for row in PendingFollowUp.query.filter(PendingFollowUp.source_day_id.in_(index_of_day)).all():
        follow_ups_out[index_of_day[row.source_day_id]].append(
            {**place(row.date), "index": None, "name": row.recipe.name, "pending": True})
    for entries in follow_ups_out:
        entries.sort(key=lambda e: e["date"])
    return {"followUpOf": follow_up_of, "followUpsOut": follow_ups_out}


def week_shopping_servings(plan_id, day):
    """Per day of the week containing day: {"main": ..., "sides": {side id:
    ...}} with the servings each dish is bought for (plan.js:
    shoppingServings; the client only multiplies). A source dish is bought
    for its own servings plus those of its follow-up dishes, in any week or
    still pending (followUpServings); a coupled follow-up dish skips its
    pre-cooked ingredients. main is None on a day without a main dish.

    Also sent with every day action that places a dish or changes servings
    (plan.js: applyShoppingServings); removing a dish needs none, since a
    coupling change makes the page reload."""
    dates = week_dates_for(friday_of(day))
    days = {pd.date: pd for pd in _week_days(plan_id, dates)}
    day_ids = [pd.id for pd in days.values()]

    servings_of_follow_ups = dict.fromkeys(day_ids, 0)
    for plan_day in PlanDay.query.filter(PlanDay.source_day_id.in_(day_ids), PlanDay.main_recipe_id.isnot(None)):
        servings_of_follow_ups[plan_day.source_day_id] += plan_day.servings
    for row in PendingFollowUp.query.filter(PendingFollowUp.source_day_id.in_(day_ids)):
        servings_of_follow_ups[row.source_day_id] += row.servings

    def entry(own_servings, follow_up_servings=0, skip_precooked=False):
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
            main = entry(plan_day.servings, servings_of_follow_ups[plan_day.id], source_dish(plan_day) is not None)
        result.append({"main": main, "sides": {str(side.id): entry(plan_day.servings) for side in plan_day.sides}})
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
    fu_recipe[] / fu_min[] / fu_max[] lists. Unknown, side-dish or duplicate
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
        r.id for r in visible_recipes_query(plan_id).filter(
            Recipe.id.in_(list(wanted)), Recipe.is_side_dish.is_(False)
        )
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
    definitions pointing at it, couplings to main dishes where it is the
    dish, its own couplings and pending entries. No commit."""
    from models import RecipeFollowUp

    RecipeFollowUp.query.filter_by(follow_up_recipe_id=recipe_id).delete()
    for plan_day in PlanDay.query.filter_by(main_recipe_id=recipe_id).all():
        PlanDay.query.filter_by(source_day_id=plan_day.id).update({"source_day_id": None})
        PendingFollowUp.query.filter_by(source_day_id=plan_day.id).delete()
        couple(plan_day, None)
    PendingFollowUp.query.filter_by(recipe_id=recipe_id).delete()
