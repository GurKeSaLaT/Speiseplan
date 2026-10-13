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
- B places its own follow-up C in turn (Folgekette), also while B is
  pending, so A is bought for the whole chain right away. Creating B's
  week takes the chain over: kept dishes stay coupled and place nothing
  new, the rest of the pending chain is dropped.
- A is a main dish or a side: a side placed by hand, by reroll or pinned
  in the create form places its follow-up just like a main dish.
- Replacing or removing A frees B's day (a new B may take it, otherwise it
  is rolled normally) or removes B if it is a side, and so on down the
  chain; replacing or removing B drops its coupling, so A is no longer
  bought for B's servings, and releases B's own follow-ups.
- Couplings follow the dishes on swaps and when a side is moved, as long
  as the follow-up stays in its source's window after it; otherwise the
  coupling is released and searched anew (recouple_moved).
- Nachträgliche Kopplung: a follow-up recipe that lands on a day without a
  coupling (picked by hand, set as a side, pinned in the create form,
  moved by a swap or a side move)
  couples to the latest dish of its source recipe in the link's window
  that isn't cooked and isn't before today, even if that dish has
  follow-ups already (couple_retroactively). No such dish -> it stays a
  normal dish and all its ingredients are bought.

A coupling (Kopplung) is stored on the follow-up dish and references its
source dish (models.calendar.CoupledDish), not a day: the main dish of a
PlanDay, a PlanDaySide or a PendingFollowUp.
"""

from collections import defaultdict, namedtuple
from datetime import date, timedelta

from flask_babel import gettext as _

from sqlalchemy import ColumnElement

from models import db, PendingFollowUp, PlanDay, PlanDaySide, Recipe, RecipeFollowUp
from models.calendar import CoupledDish
from services.planning import (  # noqa: F401 - follow_up_target_ids re-exported
    follow_up_target_ids, friday_of, recent_usage_counts, reroll_choice, weighted_recipe_choice, week_dates_for,
)
from services.recipe_trees import complete_tree
from services.recipe_visibility import visible_recipes_query

MAX_WINDOW_DAYS = 14


def today() -> date:
    """The current date, for "not before today" (tests replace it)."""
    return date.today()


def _window(link: RecipeFollowUp) -> tuple[int, int]:
    """(first, last) day offset of link's window, clamped to 1..MAX_WINDOW_DAYS."""
    low = max(1, link.min_days)
    return low, min(MAX_WINDOW_DAYS, max(low, link.max_days))


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
        low, high = _window(link)
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


# A dish that can be a source dish: a PlanDay's main dish, a side, or - in a
# chain reaching into a week not created yet - a pending follow-up.
Dish = PlanDay | PlanDaySide | PendingFollowUp


def source_dish(dish: CoupledDish) -> Dish | None:
    """The dish (a PlanDay for its main dish, a PlanDaySide or a
    PendingFollowUp) that dish is coupled to, or None."""
    if dish.source_pending_id is not None:
        return db.session.get(PendingFollowUp, dish.source_pending_id)
    if dish.source_side_id is not None:
        return db.session.get(PlanDaySide, dish.source_side_id)
    if dish.source_day_id is not None:
        return db.session.get(PlanDay, dish.source_day_id)
    return None


def couple(dish: CoupledDish, source: Dish | None) -> bool:
    """Couples dish to source (a PlanDay for its main dish, a PlanDaySide, a
    PendingFollowUp, or None to uncouple). Returns True if dish was coupled
    before."""
    was_coupled = dish.is_coupled
    dish.source_day_id = source.id if isinstance(source, PlanDay) else None
    dish.source_side_id = source.id if isinstance(source, PlanDaySide) else None
    dish.source_pending_id = source.id if isinstance(source, PendingFollowUp) else None
    return was_coupled


def _dish_date(dish: Dish) -> date:
    return dish.day.date if isinstance(dish, PlanDaySide) else dish.date


def _dish_recipe(dish: Dish) -> Recipe | None:
    return dish.main_recipe if isinstance(dish, PlanDay) else dish.recipe


def _dish_name(dish):
    recipe = _dish_recipe(dish)
    return recipe.name if recipe else ''


def _coupled_to(model: type, source: Dish) -> ColumnElement[bool]:
    """Filter for the rows of model (PlanDay, PlanDaySide or
    PendingFollowUp) coupled to source."""
    if isinstance(source, PlanDay):
        return model.source_day_id == source.id
    if isinstance(source, PlanDaySide):
        return model.source_side_id == source.id
    return model.source_pending_id == source.id


def _followers(source: Dish) -> list[CoupledDish]:
    """All main dishes, sides and pending follow-ups coupled to source."""
    return [dish for model in (PlanDay, PlanDaySide, PendingFollowUp)
            for dish in model.query.filter(_coupled_to(model, source)).all()]


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
    """Puts the follow-up on day, coupled to source (the dish it is made
    from): as the main dish, or for a side recipe as an extra side, if that
    week exists, else as pending. Returns the new dish (PlanDay,
    PlanDaySide or PendingFollowUp), for continue_chain. No commit."""
    is_side = follow_up_recipe.is_side_dish
    plan_day = PlanDay.query.filter_by(plan_id=plan_id, date=day).first()
    if plan_day is None:
        pending = PendingFollowUp(plan_id=plan_id, date=day, recipe_id=follow_up_recipe.id, is_side=is_side)
        couple(pending, source)
        db.session.add(pending)
        return pending
    if is_side:
        return add_side(plan_day, follow_up_recipe.id, source)
    plan_day.main_recipe_id = follow_up_recipe.id
    plan_day.cooked = False
    couple(plan_day, source)
    return plan_day


def add_side(plan_day, recipe_id, source=None):
    """Adds a side to plan_day, coupled to source if given. No commit."""
    side = PlanDaySide(plan_day_id=plan_day.id, recipe_id=recipe_id)
    couple(side, source)
    db.session.add(side)
    return side


def place_follow_up(plan_id: int, source: Dish) -> date | None:
    """Plans a follow-up for source (a PlanDay's main dish, a PlanDaySide or
    a PendingFollowUp) if one fits, never one already in source's week, and
    lets it place its own follow-up in turn (Folgekette, also into weeks not
    created yet, so the whole chain is bought for). Returns the first
    follow-up's date or None. No commit."""
    db.session.flush()
    picked = pick_follow_up(
        _dish_recipe(source), plan_id, _dish_date(source),
        lambda day, is_side: live_slot_free(plan_id, day, is_side), _week_recipe_ids(plan_id, _dish_date(source)),
    )
    if picked is None:
        return None
    recipe, day = picked
    continue_chain(plan_id, assign_follow_up(plan_id, recipe, day, source))
    return day


def continue_chain(plan_id: int, dish: Dish) -> date | None:
    """Lets a just stored dish place its follow-up (place_follow_up) once
    its changes are flushed. Returns the follow-up's date or None. No
    commit."""
    db.session.flush()
    db.session.refresh(dish)
    return place_follow_up(plan_id, dish)


def couple_retroactively(plan_id: int, dish: PlanDay | PlanDaySide) -> bool:
    """Nachträgliche Kopplung: dish (a PlanDay's main dish or a side) landed
    without a coupling - picked by hand, set as a side, pinned in the
    create form, or moved by a swap or side move (recouple_moved). If its
    recipe is a follow-up recipe, dish is coupled to the latest dish (main
    dish before side on the same day) of its source recipe in the link's
    window before it that isn't cooked and isn't before today, even if that
    source has follow-ups already. A dish already cooked (carried along by
    a swap) stays uncoupled: its source isn't bought for more any more.
    Returns True if dish was coupled. No commit."""
    db.session.flush()
    db.session.refresh(dish)  # its recipe may just have been set by id
    recipe = _dish_recipe(dish)
    if recipe is None or dish.is_coupled or dish.cooked:
        return False
    day = _dish_date(dish)
    candidates = []
    for link in RecipeFollowUp.query.filter_by(follow_up_recipe_id=recipe.id):
        low, high = _window(link)
        in_window = (PlanDay.plan_id == plan_id, PlanDay.date >= max(today(), day - timedelta(days=high)),
                     PlanDay.date <= day - timedelta(days=low))
        candidates += PlanDay.query.filter(
            *in_window, PlanDay.main_recipe_id == link.recipe_id, PlanDay.cooked.is_(False)).all()
        candidates += PlanDaySide.query.join(PlanDay, PlanDaySide.plan_day_id == PlanDay.id).filter(
            *in_window, PlanDaySide.recipe_id == link.recipe_id, PlanDaySide.cooked.is_(False)).all()
    if not candidates:
        return False
    couple(dish, max(candidates, key=lambda source: (_dish_date(source), isinstance(source, PlanDay))))
    return True


# freed_days: PlanDays whose follow-up main dish was cleared, for re-planning;
# released: whether anything at all was released.
Release = namedtuple('Release', 'freed_days released')


def release_follow_ups(source: Dish) -> Release:
    """source (a PlanDay's main dish, a PlanDaySide or a PendingFollowUp)
    goes away: the days of its follow-up main dishes lose their dish
    (returned, for re-planning), its follow-up sides and pending follow-ups
    are dropped, and so on down the chain (Kopplung lösen). No commit."""
    freed = []
    for plan_day in PlanDay.query.filter(_coupled_to(PlanDay, source)).all():
        freed += [plan_day, *release_follow_ups(plan_day).freed_days]
        couple(plan_day, None)
        plan_day.main_recipe_id = None
        plan_day.cooked = False
    sides = PlanDaySide.query.filter(_coupled_to(PlanDaySide, source)).all()
    for side in sides:
        freed += release_follow_ups(side).freed_days
        db.session.delete(side)
    pending = PendingFollowUp.query.filter(_coupled_to(PendingFollowUp, source)).all()
    for row in pending:
        freed += release_follow_ups(row).freed_days
        db.session.delete(row)
    return Release(freed, bool(freed or sides or pending))


def replace_main_dish(plan_id: int, plan_day: PlanDay, new_recipe: Recipe | None) -> bool:
    """Sets plan_day's main dish (None clears it) and keeps links right:
    plan_day stops being a follow-up; if it was a source, its follow-ups
    are released; a new follow-up recipe couples to an earlier source dish
    (couple_retroactively); a new source gets a follow-up (possibly on a
    released day); released days still empty are rolled anew
    (refill_released). Returns True if any coupling changed (the client
    then reloads)."""
    changed = couple(plan_day, None)
    db.session.flush()  # a new plan_day gets its id
    freed, released = release_follow_ups(plan_day)
    changed = changed or released

    plan_day.main_recipe_id = new_recipe.id if new_recipe else None
    plan_day.cooked = False
    if couple_retroactively(plan_id, plan_day):
        changed = True
    if new_recipe is not None and continue_chain(plan_id, plan_day) is not None:
        changed = True
    refill_released(plan_id, freed)
    return changed


def replace_side_dish(plan_id: int, side: PlanDaySide, new_recipe: Recipe) -> bool:
    """The side counterpart of replace_main_dish: side stops being a
    follow-up, its own follow-ups are released, a follow-up recipe couples
    to an earlier source dish, the new recipe places a follow-up if it has
    one, released days are rolled anew. Returns True if any coupling
    changed. No commit."""
    changed = couple(side, None)
    freed, released = release_follow_ups(side)
    side.recipe_id = new_recipe.id
    side.cooked = False
    if couple_retroactively(plan_id, side):
        changed = True
    if continue_chain(plan_id, side) is not None:
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


def _refill_day(plan_day: PlanDay) -> None:
    """Rolls a normal dish for a day whose follow-up dish was released
    (services/planning.py: reroll_choice). No commit."""
    chosen = reroll_choice(plan_day.plan_id, plan_day.date)
    plan_day.main_recipe_id = chosen.id if chosen else None
    plan_day.cooked = False


def release_week(plan_id: int, dates: list[date]) -> list[PlanDay]:
    """The week `dates` is recreated: all its main dishes and sides release
    their follow-ups. Returns the freed days outside the week, for
    refill_released once the new week is saved. No commit."""
    freed = []
    for plan_day in week_days(plan_id, dates):
        for source in [plan_day, *plan_day.sides]:
            freed += [pd for pd in release_follow_ups(source).freed_days if pd.date not in dates]
    return freed


def refill_released(plan_id: int, freed_days: list[PlanDay]) -> None:
    """Rolls a dish for released follow-up days that are still empty
    (_refill_day); a refilled dish with follow-ups gets one placed like
    any planned dish. No commit."""
    for freed_day in freed_days:
        if freed_day.main_recipe_id is None and not freed_day.excluded:
            _refill_day(freed_day)
            if freed_day.main_recipe_id is not None:
                continue_chain(plan_id, freed_day)


def _week_recipe_ids(plan_id, day):
    """Main dishes, sides and pending follow-ups of the week containing day."""
    dates = week_dates_for(friday_of(day))
    rows = week_days(plan_id, dates)
    pending = PendingFollowUp.query.filter(PendingFollowUp.plan_id == plan_id, PendingFollowUp.date.in_(dates))
    return ({pd.main_recipe_id for pd in rows if pd.main_recipe_id}
            | {side.recipe_id for pd in rows for side in pd.sides} | {row.recipe_id for row in pending})


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


def _fits_window(follow_up: Dish, source: Dish) -> bool:
    """Whether follow_up lies in the window of source's link to it (at
    least a day after source if the link is gone)."""
    gap = (_dish_date(follow_up) - _dish_date(source)).days
    source_recipe, recipe = _dish_recipe(source), _dish_recipe(follow_up)
    link = None if source_recipe is None or recipe is None else RecipeFollowUp.query.filter_by(
        recipe_id=source_recipe.id, follow_up_recipe_id=recipe.id).first()
    low, high = _window(link) if link else (1, MAX_WINDOW_DAYS)
    return low <= gap <= high


def recouple_moved(plan_id: int, moved: list[PlanDay | PlanDaySide]) -> bool:
    """After a swap or a side move (couplings already carried along): a
    moved dish that left its source's window or now lies before it loses
    its coupling, and so does a follow-up of a moved dish that its source
    left behind; both then look for a source anew (couple_retroactively),
    like a follow-up recipe that moved onto a day without a coupling. A
    pending follow-up that falls out is dropped with its chain (released
    days rolled anew). Returns True if any coupling changed. No commit."""
    db.session.flush()
    for dish in moved:
        db.session.refresh(dish)  # a moved side's day relationship is stale
    changed = False
    needs_source = list(moved)
    freed_days = []
    for dish in moved:
        source = source_dish(dish)
        if source is not None and not _fits_window(dish, source):
            couple(dish, None)
            changed = True
        for follower in _followers(dish):
            if _fits_window(follower, dish):
                continue
            changed = True
            if isinstance(follower, PendingFollowUp):
                freed_days += release_follow_ups(follower).freed_days
                db.session.delete(follower)
            else:
                couple(follower, None)
                needs_source.append(follower)
    for dish in needs_source:
        if couple_retroactively(plan_id, dish):
            changed = True
    refill_released(plan_id, freed_days)
    return changed


def _day_label(day):
    from services.planning import DAY_NAMES
    return f"{DAY_NAMES[(day.weekday() - 4) % 7]}, {day.strftime('%d.%m.')}"


# dish: the pending follow-up or stored dish itself; source: its source dish.
IncomingFollowUp = namedtuple('IncomingFollowUp', 'day_index recipe is_side source source_name dish')


def incoming_follow_ups(plan_id, dates):
    """[IncomingFollowUp] for the week `dates`, ordered by day: pending
    follow-ups plus stored main dishes and sides coupled to a dish from
    before this week, and the pending follow-ups further down their chains
    within the week. The create form offers them as fixed dishes (a main
    dish per day at most, any number of sides)."""
    def coupled(model):
        return model.source_day_id.isnot(None) | model.source_side_id.isnot(None) | model.source_pending_id.isnot(None)

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
        if source is not None and (_dish_date(source) < dates[0] or isinstance(source, PendingFollowUp)):
            result.append(IncomingFollowUp(dates.index(day), recipe, is_side, source, _dish_name(source), dish))
    return sorted(result, key=lambda entry: (entry.day_index, entry.is_side))


def keeping_follow_ups(kept: list[IncomingFollowUp], dates: list[date]) -> list[IncomingFollowUp]:
    """Of the incoming dishes kept when the week `dates` is created, the
    pending ones whose chain goes on: a follow-up of theirs is kept too or
    waits beyond the week. They place no new follow-up."""
    kept_dishes = [entry.dish for entry in kept]
    return [
        entry for entry in kept if isinstance(entry.dish, PendingFollowUp) and any(
            follower in kept_dishes or _dish_date(follower) not in dates for follower in _followers(entry.dish))
    ]


def take_over_incoming(plan_id: int, dates: list[date], stored: list[tuple[IncomingFollowUp, Dish]]) -> list[PlanDay]:
    """After the week `dates` is saved: each kept incoming dish (stored:
    (entry, its dish in the saved week)) is coupled to its source dish - to
    the saved dish if the source was pending in this week too, uncoupled if
    that wasn't kept. Follow-ups beyond the week of a kept pending dish now
    follow its saved dish. All other pending follow-ups of the week are
    dropped with their chains (release_follow_ups). Returns the freed days,
    for refill_released. No commit."""
    saved = {id(entry.dish): dish for entry, dish in stored}

    def resolve(source: Dish) -> Dish | None:
        if isinstance(source, PendingFollowUp) and source.date in dates:
            return saved.get(id(source))
        return source

    for entry, dish in stored:
        couple(dish, resolve(entry.source))
    pending = PendingFollowUp.query.filter(PendingFollowUp.plan_id == plan_id, PendingFollowUp.date.in_(dates)).all()
    for row in pending:
        if id(row) in saved:
            for follower in _followers(row):
                if _dish_date(follower) not in dates:
                    couple(follower, saved[id(row)])
    freed = []
    for row in pending:
        if id(row) not in saved:
            freed += release_follow_ups(row).freed_days
    db.session.flush()
    PendingFollowUp.query.filter(PendingFollowUp.plan_id == plan_id, PendingFollowUp.date.in_(dates)).delete(
        synchronize_session=False)
    return freed


def week_days(plan_id, dates):
    return PlanDay.query.filter(PlanDay.plan_id == plan_id, PlanDay.date.in_(dates)).all()


# A dish or pending follow-up coupled to a source dish, for notes and amounts.
# dish: the PlanDay, PlanDaySide or PendingFollowUp; servings: what it is
# bought for (_follow_ups_by_source).
FollowUpDish = namedtuple('FollowUpDish', 'dish date name servings pending')


def _follow_ups_by_source(days: list[PlanDay]) -> dict[Dish, list[FollowUpDish]]:
    """The follow-ups of the main dishes and sides of days, in any week or
    still pending, and down the chain the follow-ups of those (pending
    ones too): {source dish: [FollowUpDish]}, by date. A follow-up's
    servings are its own plus those of all follow-ups below it, so a
    source dish is bought for the whole chain (Lasagne 2, Ragout 2+2=4,
    Braten 2+4=6)."""
    children = defaultdict(list)  # source -> [FollowUpDish with its own servings]

    def dish_key(dish: Dish) -> tuple[type, int]:
        return type(dish), dish.id

    # Breadth-first down the chains; a follow-up that is in days already was
    # asked for its follow-ups as one of them (seen).
    seen = set()
    frontier = list(days) + [side for pd in days for side in pd.sides]
    while frontier:
        sources = {dish_key(d): d for d in frontier if dish_key(d) not in seen}
        seen |= set(sources)
        if not sources:
            break

        def coupled(model: type) -> ColumnElement[bool]:
            return (model.source_day_id.in_([i for kind, i in sources if kind is PlanDay])
                    | model.source_side_id.in_([i for kind, i in sources if kind is PlanDaySide])
                    | model.source_pending_id.in_([i for kind, i in sources if kind is PendingFollowUp]))

        def source_of(dish: CoupledDish) -> Dish:
            return sources[dish_key(source_dish(dish))]

        frontier = []
        for plan_day in PlanDay.query.filter(coupled(PlanDay), PlanDay.main_recipe_id.isnot(None)):
            children[source_of(plan_day)].append(
                FollowUpDish(plan_day, plan_day.date, plan_day.main_recipe.name, plan_day.servings, False))
            frontier.append(plan_day)
        for side in PlanDaySide.query.filter(coupled(PlanDaySide)):
            children[source_of(side)].append(
                FollowUpDish(side, side.day.date, side.recipe.name, side.day.servings, False))
            frontier.append(side)
        for row in PendingFollowUp.query.filter(coupled(PendingFollowUp)):
            children[source_of(row)].append(FollowUpDish(row, row.date, row.recipe.name, row.servings, True))
            frontier.append(row)

    def purchase_servings(follow_up: FollowUpDish) -> int:
        return follow_up.servings + sum(purchase_servings(child) for child in children.get(follow_up.dish, ()))

    return {
        source: sorted(
            (follow_up._replace(servings=purchase_servings(follow_up)) for follow_up in follow_ups),
            key=lambda follow_up: follow_up.date,
        )
        for source, follow_ups in children.items()
    }


def week_follow_up_data(
    plan_id: int, dates: list[date], ordered_days: list[PlanDay | None], day_labels: list[str],
) -> dict:
    """plan_data entries for the follow-up notes on the week page (plan.js):
    followUpOf[i]: the source dish (main dish or side) of day i's follow-up
    main dish, or null; followUpsOut[i]: day i's main dish's follow-ups
    (main dishes and sides), in this week (index set) or elsewhere;
    sideFollowUpsOut: the same per source side, by side id. Amounts come
    from week_shopping_servings."""
    def place(day: date) -> dict:
        in_week = day in dates
        return {
            "date": day.isoformat(),
            "index": dates.index(day) if in_week else None,
            "label": day_labels[dates.index(day)] if in_week else _day_label(day),
        }

    def notes(dishes: list[FollowUpDish]) -> list[dict]:
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


def week_shopping_servings(plan_id: int, day: date) -> list[dict]:
    """Per day of the week containing day: {"main": ..., "sides": {side id:
    ...}} with the servings each dish is bought for (plan.js:
    shoppingServings; the client only multiplies). A source dish (main
    dish or side) is bought for its own servings plus those of its
    follow-up dishes, in any week or still pending, recursively down the
    chain (followUpServings); a coupled follow-up dish skips its
    pre-cooked ingredients. main is None on a day without a main dish.

    Also sent with every day action that places a dish or changes servings
    (plan.js: applyShoppingServings); removing a dish needs none, since a
    coupling change makes the page reload."""
    dates = week_dates_for(friday_of(day))
    days = {pd.date: pd for pd in week_days(plan_id, dates)}
    follow_ups = _follow_ups_by_source(list(days.values()))

    def entry(own_servings: int, source: PlanDay | PlanDaySide, skip_precooked: bool) -> dict:
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


def forget_recipe(recipe_id: int) -> None:
    """Before deleting a recipe: drop links that would dangle - follow-up
    definitions pointing at it, couplings to main dishes, sides and pending
    follow-ups where it is the dish (stored follow-ups stay as normal
    dishes, pending ones are dropped with their chains), its own couplings
    and pending entries. No commit."""
    RecipeFollowUp.query.filter_by(follow_up_recipe_id=recipe_id).delete()
    sources = PlanDay.query.filter_by(main_recipe_id=recipe_id).all()
    sources += PlanDaySide.query.filter_by(recipe_id=recipe_id).all()
    sources += PendingFollowUp.query.filter_by(recipe_id=recipe_id).all()
    def forget_follow_ups(source: Dish) -> None:
        for dish in _followers(source):
            if isinstance(dish, PendingFollowUp):
                forget_follow_ups(dish)
                db.session.delete(dish)
            else:
                couple(dish, None)

    for source in sources:
        forget_follow_ups(source)
        couple(source, None)
    db.session.flush()
    PendingFollowUp.query.filter_by(recipe_id=recipe_id).delete()
