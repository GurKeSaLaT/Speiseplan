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
"""

from datetime import timedelta

from models import db, PendingFollowUp, PlanDay, Recipe
from services.planning import (  # noqa: F401 - follow_up_target_ids re-exported
    follow_up_target_ids, friday_of, recent_usage_counts, weighted_recipe_choice,
)
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


def assign_follow_up(plan_id, follow_up_recipe, day, source_date):
    """Puts the follow-up on day: onto its PlanDay if that week exists,
    else as pending. No commit."""
    plan_day = PlanDay.query.filter_by(plan_id=plan_id, date=day).first()
    if plan_day is not None:
        plan_day.main_recipe_id = follow_up_recipe.id
        plan_day.cooked = False
        plan_day.follow_up_of_date = source_date
        return plan_day
    db.session.add(PendingFollowUp(
        plan_id=plan_id, date=day, recipe_id=follow_up_recipe.id, source_date=source_date
    ))
    return None


def place_follow_up(plan_id, source_day, exclude_ids=()):
    """Plans a follow-up for source_day's dish if one fits; returns its
    date or None. No commit."""
    db.session.flush()
    picked = pick_follow_up(
        source_day.main_recipe, plan_id, source_day.date,
        lambda day: live_slot_free(plan_id, day), exclude_ids,
    )
    if picked is None:
        return None
    recipe, day = picked
    assign_follow_up(plan_id, recipe, day, source_day.date)
    return day


def release_follow_ups(plan_id, source_date):
    """The source dish on source_date goes away: its follow-up days lose
    their dish (returned, for re-planning) and pending ones are dropped.
    No commit."""
    freed = PlanDay.query.filter_by(plan_id=plan_id, follow_up_of_date=source_date).all()
    for plan_day in freed:
        plan_day.follow_up_of_date = None
        plan_day.main_recipe_id = None
        plan_day.cooked = False
    PendingFollowUp.query.filter_by(plan_id=plan_id, source_date=source_date).delete()
    return freed


def replace_main_dish(plan_id, plan_day, new_recipe, refill):
    """Sets plan_day's main dish (None clears it) and keeps links right:
    plan_day stops being a follow-up; if it was a source, its follow-ups
    are released; a new source gets a follow-up (possibly on a released
    day); released days still empty are filled via refill(plan_day).
    Returns True if any link changed (the client then reloads)."""
    changed = plan_day.follow_up_of_date is not None
    plan_day.follow_up_of_date = None
    had_pending = PendingFollowUp.query.filter_by(plan_id=plan_id, source_date=plan_day.date).count() > 0
    freed = release_follow_ups(plan_id, plan_day.date)
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


def unlink_follow_up(plan_day):
    """plan_day's dish no longer counts as a follow-up. True if it was one."""
    was_linked = plan_day.follow_up_of_date is not None
    plan_day.follow_up_of_date = None
    return was_linked


def move_links_on_swap(plan_id, day_a, day_b):
    """Call after swapping the dishes of day_a and day_b: incoming links
    travel with the dishes, outgoing links point to the source's new date.
    Returns True if any link was involved."""
    date_a, date_b = day_a.date, day_b.date
    involved = day_a.follow_up_of_date is not None or day_b.follow_up_of_date is not None
    day_a.follow_up_of_date, day_b.follow_up_of_date = day_b.follow_up_of_date, day_a.follow_up_of_date

    from_a = PlanDay.query.filter_by(plan_id=plan_id, follow_up_of_date=date_a).all()
    from_b = PlanDay.query.filter_by(plan_id=plan_id, follow_up_of_date=date_b).all()
    pending_a = PendingFollowUp.query.filter_by(plan_id=plan_id, source_date=date_a).all()
    pending_b = PendingFollowUp.query.filter_by(plan_id=plan_id, source_date=date_b).all()
    # The swapped days' own fields were already exchanged above; a dish that
    # follows its own (now swapped) source is fixed up by the same mapping.
    for plan_day in from_a:
        plan_day.follow_up_of_date = date_b
    for plan_day in from_b:
        plan_day.follow_up_of_date = date_a
    for pending in pending_a:
        pending.source_date = date_b
    for pending in pending_b:
        pending.source_date = date_a
    return involved or bool(from_a or from_b or pending_a or pending_b)


def _day_label(day):
    from services.planning import DAY_NAMES
    return f"{DAY_NAMES[(day.weekday() - 4) % 7]}, {day.strftime('%d.%m.')}"


def _main_name(plan_id, day):
    plan_day = PlanDay.query.filter_by(plan_id=plan_id, date=day).first()
    return plan_day.main_recipe.name if plan_day and plan_day.main_recipe else ''


def incoming_follow_ups(plan_id, dates):
    """{day index: (follow-up Recipe, source date, source dish name)} for the
    week `dates`: pending follow-ups plus stored days that follow a dish
    from before this week. The create form offers them as fixed dishes."""
    result = {}
    pending = PendingFollowUp.query.filter(
        PendingFollowUp.plan_id == plan_id, PendingFollowUp.date.in_(dates)
    ).all()
    for row in pending:
        result[dates.index(row.date)] = (row.recipe, row.source_date, _main_name(plan_id, row.source_date))
    linked_days = PlanDay.query.filter(
        PlanDay.plan_id == plan_id, PlanDay.date.in_(dates),
        PlanDay.follow_up_of_date.isnot(None), PlanDay.follow_up_of_date < dates[0],
    ).all()
    for plan_day in linked_days:
        if plan_day.main_recipe is not None:
            result[dates.index(plan_day.date)] = (
                plan_day.main_recipe, plan_day.follow_up_of_date, _main_name(plan_id, plan_day.follow_up_of_date)
            )
    return result


def week_follow_up_data(plan_id, dates, ordered_days, day_labels):
    """plan_data entries for the week page (plan.js / plan-shopping.js):
    followUpOf[i]: the source dish of day i's follow-up dish, or null;
    followUpsOut[i]: day i's dish's follow-ups - in this week (index set,
    servings read live from the page) or elsewhere (servings fixed here)."""
    follow_up_of = []
    for i, plan_day in enumerate(ordered_days):
        source = plan_day.follow_up_of_date if plan_day and plan_day.main_recipe_id else None
        if source is None:
            follow_up_of.append(None)
            continue
        follow_up_of.append({
            "date": source.isoformat(),
            "index": dates.index(source) if source in dates else None,
            "name": _main_name(plan_id, source),
            "label": day_labels[dates.index(source)] if source in dates else _day_label(source),
        })

    follow_ups_out = [[] for _ in dates]
    linked_days = PlanDay.query.filter(
        PlanDay.plan_id == plan_id, PlanDay.follow_up_of_date.in_(dates), PlanDay.main_recipe_id.isnot(None)
    ).all()
    for plan_day in linked_days:
        in_week = plan_day.date in dates
        follow_ups_out[dates.index(plan_day.follow_up_of_date)].append({
            "date": plan_day.date.isoformat(),
            "index": dates.index(plan_day.date) if in_week else None,
            "name": plan_day.main_recipe.name,
            "label": day_labels[dates.index(plan_day.date)] if in_week else _day_label(plan_day.date),
            "servings": plan_day.servings,
            "pending": False,
        })
    pending = PendingFollowUp.query.filter(
        PendingFollowUp.plan_id == plan_id, PendingFollowUp.source_date.in_(dates)
    ).all()
    for row in pending:
        follow_ups_out[dates.index(row.source_date)].append({
            "date": row.date.isoformat(), "index": None, "name": row.recipe.name,
            "label": _day_label(row.date), "servings": row.servings, "pending": True,
        })
    for entries in follow_ups_out:
        entries.sort(key=lambda e: e["date"])
    return {"followUpOf": follow_up_of, "followUpsOut": follow_ups_out}


def save_follow_up_links(recipe, form, plan_id):
    """Replaces recipe's follow-ups from the recipe form's parallel
    fu_recipe[] / fu_min[] / fu_max[] lists. Unknown, side-dish, duplicate
    or self references are skipped; days are clamped to 1..MAX_WINDOW_DAYS
    with max >= min. No commit."""
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
        if follow_up_id is None or follow_up_id == recipe.id or follow_up_id in wanted:
            continue
        low = min(MAX_WINDOW_DAYS, max(1, as_int(mins[i] if i < len(mins) else None, 2)))
        high = min(MAX_WINDOW_DAYS, max(low, as_int(maxs[i] if i < len(maxs) else None, 3)))
        wanted[follow_up_id] = (low, high)
    valid = {
        r.id for r in visible_recipes_query(plan_id).filter(
            Recipe.id.in_(list(wanted)), Recipe.is_side_dish.is_(False)
        )
    } if wanted else set()

    recipe.follow_ups = [
        RecipeFollowUp(follow_up_recipe_id=follow_up_id, min_days=low, max_days=high)
        for follow_up_id, (low, high) in wanted.items() if follow_up_id in valid
    ]


def forget_recipe(recipe_id):
    """Before deleting a recipe: drop links that would dangle - follow-up
    definitions pointing at it, follow-up days of days where it is the
    dish, its own follow-up status and pending entries. No commit."""
    from models import RecipeFollowUp

    RecipeFollowUp.query.filter_by(follow_up_recipe_id=recipe_id).delete()
    for plan_day in PlanDay.query.filter_by(main_recipe_id=recipe_id).all():
        PlanDay.query.filter_by(plan_id=plan_day.plan_id, follow_up_of_date=plan_day.date).update(
            {"follow_up_of_date": None})
        PendingFollowUp.query.filter_by(plan_id=plan_day.plan_id, source_date=plan_day.date).delete()
        plan_day.follow_up_of_date = None
    PendingFollowUp.query.filter_by(recipe_id=recipe_id).delete()
