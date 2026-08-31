"""AJAX endpoints called by the client-side static/plan.js (and the
plan-*.js companion files) that return JSON - for individual calendar
days (day_date), not whole weeks. They work directly with the concrete
calendar day, not with week-start+index - that makes them independent of
which week view the user is currently triggering them from, and even
lets the neighborhood category rule on reroll work across week
boundaries (see reroll_day).

The side-dish actions (/day/<day_date>/side/...) are additionally
ITEM-specific (a day can have several side dishes, see models.py:
PlanDaySide) - all but "add" therefore address one specific PlanDaySide
row via <int:side_id>.
"""

from datetime import timedelta

from flask import request
from flask_babel import gettext as _

from models import db, Category, Recipe, PlanDay, PlanDaySide
from services.auth import current_plan
from services.planning import (
    parse_iso_date, week_neighbor_exclude_ids, week_side_recipe_ids,
    choose_recipe, jsonify_recipe, jsonify_side
)
from services.recipe_visibility import visible_recipes_query
from routes.plan import plan_bp


@plan_bp.route('/day/<day_date>/reroll-main', methods=['POST'])
def reroll_day(day_date):
    """AJAX endpoint behind the dice button of a main dish on the
    finished plan page: rolls a new, different main dish for EXACTLY THIS
    calendar day and persists it immediately.

    A reroll is only possible for days that are already part of a
    created plan AND have not been marked as "excluded" (an excluded day
    deliberately has no main dish - there's nothing to reroll there).

    The selection logic is essentially the same as in week_generate()
    (steps 4+5 there), but for a single day instead of a whole week at
    once:

    - exclude_ids starts with the main dishes of all OTHER days of the
      same week (week_neighbor_exclude_ids) and is extended by the
      CURRENT recipe of this day - so a reroll can never return the same
      recipe that's already there, nor a recipe already used elsewhere
      this week.

    - The category count (other_cat_counts) is derived from exactly these
      excluded recipes, to preserve the same notion of balance as when
      creating the plan.

    - The direct neighboring days (previous/next day, determined via
      real timedelta(days=1) arithmetic) are given lower priority in the
      category sorting, so a reroll doesn't put two consecutive days in
      the same category. Because this works with real calendar dates
      instead of a week-internal index, this even works across week
      boundaries (e.g. when rerolling a Sunday, the Monday of the
      FOLLOWING, already existing week is also considered a neighbor).

    First tries to hit one of the categories (sorted by
    neighborhood/balance); if that fails completely, a category-
    independent attempt is made as a last fallback. If in the end none
    of them yields a result (e.g. because literally no main dish is left),
    an error is returned instead of silently leaving the day empty.

    reference_date=target_date is passed through to choose_recipe() and
    activates the soft repetition weighting there (see
    services/planning.py: recent_usage_counts/weighted_recipe_choice) -
    among the candidates remaining after the logic above, recipes used
    recently/often are rolled less often (but never made impossible).
    """
    target_date = parse_iso_date(day_date)
    if target_date is None:
        return {"error": _("Invalid date")}, 400
    plan = current_plan()

    plan_day = PlanDay.query.filter_by(plan_id=plan.id, date=target_date).first()
    if not plan_day or plan_day.excluded:
        return {"error": _("This day is not part of a plan or is excluded from main dish planning.")}, 400

    exclude_ids = week_neighbor_exclude_ids(target_date, plan.id)
    if plan_day.main_recipe_id:
        exclude_ids.add(plan_day.main_recipe_id)

    all_categories = Category.query.filter_by(plan_id=plan.id).all()
    all_cat_ids = [c.id for c in all_categories]

    other_recipes = visible_recipes_query(plan.id).filter(Recipe.id.in_(exclude_ids)).all()
    other_cat_counts = {cid: 0 for cid in all_cat_ids}
    for r in other_recipes:
        other_cat_counts[r.category_id] = other_cat_counts.get(r.category_id, 0) + 1

    neighbor_ids = []
    for neighbor_date in (target_date - timedelta(days=1), target_date + timedelta(days=1)):
        neighbor_day = PlanDay.query.filter_by(plan_id=plan.id, date=neighbor_date).first()
        if neighbor_day and neighbor_day.main_recipe_id:
            neighbor_ids.append(neighbor_day.main_recipe_id)
    neighbor_categories = {r.category_id for r in visible_recipes_query(plan.id).filter(Recipe.id.in_(neighbor_ids)).all()}

    # Sort key just like in assign_balanced_categories(): first
    # non-neighbor categories (False < True), then the rarest one so far.
    sorted_target_categories = sorted(
        all_cat_ids, key=lambda cid: (cid in neighbor_categories, other_cat_counts[cid])
    )

    chosen = None
    for best_cat_id in sorted_target_categories:
        chosen = choose_recipe(
            is_side_dish=False, exclude_ids=exclude_ids, plan_id=plan.id, category_id=best_cat_id,
            reference_date=target_date
        )
        if chosen:
            break
    if not chosen:
        chosen = choose_recipe(is_side_dish=False, exclude_ids=exclude_ids, plan_id=plan.id, reference_date=target_date)

    if not chosen:
        return {"error": _("No more recipes available in the database!")}, 400

    plan_day.main_recipe_id = chosen.id
    # Freshly rolled dish hasn't been cooked yet (see models.py:
    # PlanDay.cooked) - regardless of whether the previous state here was
    # already marked as cooked.
    plan_day.cooked = False
    db.session.commit()
    return jsonify_recipe(chosen, plan.id)


@plan_bp.route('/day/<day_date>/set-main', methods=['POST'])
def set_main_day(day_date):
    """AJAX endpoint behind the pencil button of a main dish: sets an
    explicitly user-selected main dish (instead of a randomly rolled one,
    see reroll_day above) for EXACTLY THIS calendar day.

    Deliberately WITHOUT any of the automatic rules described in
    reroll_day() (category balance, neighborhood, repetition weighting,
    weekly duplicate exclusion) - a manual selection is an explicit user
    wish and should never be blocked by an automatic rule, just like the
    manual assignment on the create page (week_generate) is also not
    subject to any of these rules.

    Also sets excluded to False: a day that is currently having a main
    dish explicitly assigned to it can, by definition, no longer be
    "excluded from main dish planning" (see models.py: PlanDay) - this
    way an excluded day can be brought back into the plan via the pencil
    button too, without a detour through the create page.
    """
    target_date = parse_iso_date(day_date)
    if target_date is None:
        return {"error": _("Invalid date")}, 400
    plan = current_plan()

    data = request.get_json() or {}
    try:
        recipe_id = int(data.get('recipe_id'))
    except (TypeError, ValueError):
        return {"error": _("Invalid recipe")}, 400

    recipe = visible_recipes_query(plan.id).filter_by(id=recipe_id, is_side_dish=False).first()
    if not recipe:
        return {"error": _("Recipe not found.")}, 400

    plan_day = PlanDay.query.filter_by(plan_id=plan.id, date=target_date).first()
    if not plan_day:
        plan_day = PlanDay(plan_id=plan.id, date=target_date, servings=2)
        db.session.add(plan_day)

    plan_day.excluded = False
    plan_day.main_recipe_id = recipe.id
    # See reroll_day() above - a manually assigned dish is by definition
    # not yet cooked.
    plan_day.cooked = False
    db.session.commit()
    return jsonify_recipe(recipe, plan.id)


def _get_or_create_plan_day(target_date, plan_id):
    """Get-or-create helper needed identically in several of the
    side-dish endpoints below (add_side/reroll_one_side/set_one_side/
    move_one_side all create a new, empty PlanDay row if needed, in case
    no row exists yet for target_date - e.g. when a side dish is moved to
    a day that wasn't previously part of the week at all).
    db.session.flush() ensures that a newly created row immediately has a
    real id before the caller points a PlanDaySide at it."""
    plan_day = PlanDay.query.filter_by(plan_id=plan_id, date=target_date).first()
    if not plan_day:
        plan_day = PlanDay(plan_id=plan_id, date=target_date, servings=2)
        db.session.add(plan_day)
        db.session.flush()
    return plan_day


@plan_bp.route('/day/<day_date>/side/add', methods=['POST'])
def add_side(day_date):
    """AJAX endpoint behind the side-dish "add" buttons at the end of a
    day card's side-dish list: creates a NEW side dish for this day, in
    addition to any already present (a day can have any number of them,
    see models.py: PlanDaySide).

    Expects a JSON body {"recipe_id": <id> or null}:
    - If recipe_id is set (the picker button in
      static/plan-sides.js: openSideManualSelect), EXACTLY this
      user-chosen recipe is used - without any randomness/exclusion
      logic, analogous to set_main_day() above.
    - If recipe_id is empty/null (the dice button), a random one is
      rolled instead: choose_recipe() with week_side_recipe_ids() as the
      exclusion set (prevents duplicates both with other days and with
      side dishes already present on THIS day) and the soft repetition
      weighting (reference_date).
    """
    target_date = parse_iso_date(day_date)
    if target_date is None:
        return {"error": _("Invalid date")}, 400
    plan = current_plan()

    data = request.get_json() or {}
    raw_recipe_id = data.get('recipe_id')

    plan_day = _get_or_create_plan_day(target_date, plan.id)

    if raw_recipe_id:
        try:
            recipe_id = int(raw_recipe_id)
        except (TypeError, ValueError):
            return {"error": _("Invalid recipe")}, 400
        chosen = visible_recipes_query(plan.id).filter_by(id=recipe_id, is_side_dish=True).first()
        if not chosen:
            return {"error": _("Recipe not found.")}, 400
    else:
        exclude_ids = week_side_recipe_ids(target_date, plan.id)
        chosen = choose_recipe(is_side_dish=True, exclude_ids=exclude_ids, plan_id=plan.id, reference_date=target_date)
        if not chosen:
            return {"error": _("No more side dishes available in the database!")}, 400

    plan_day_side = PlanDaySide(plan_day_id=plan_day.id, recipe_id=chosen.id)
    db.session.add(plan_day_side)
    db.session.commit()
    return jsonify_side(plan_day_side, plan.id)


@plan_bp.route('/day/<day_date>/side/<int:side_id>/reroll', methods=['POST'])
def reroll_one_side(day_date, side_id):
    """AJAX endpoint behind the dice button of ONE specific side dish:
    replaces exactly this side-dish slot with a newly rolled, different
    recipe (as opposed to add_side above, which creates an ADDITIONAL
    slot).

    The PlanDaySide row is not deleted and recreated here, but its
    recipe_id is overwritten directly - so its id (and thus e.g. a
    currently open reference in the frontend) stays stable across the
    reroll.
    """
    target_date = parse_iso_date(day_date)
    if target_date is None:
        return {"error": _("Invalid date")}, 400
    plan = current_plan()

    plan_day_side = PlanDaySide.query.join(PlanDay).filter(
        PlanDaySide.id == side_id, PlanDay.plan_id == plan.id, PlanDay.date == target_date
    ).first()
    if not plan_day_side:
        return {"error": _("This side dish does not belong to this day.")}, 404

    exclude_ids = week_side_recipe_ids(target_date, plan.id)
    chosen = choose_recipe(is_side_dish=True, exclude_ids=exclude_ids, plan_id=plan.id, reference_date=target_date)
    if not chosen:
        return {"error": _("No more side dishes available in the database!")}, 400

    plan_day_side.recipe_id = chosen.id
    # See reroll_day() above - a freshly rolled side dish is not yet cooked.
    plan_day_side.cooked = False
    db.session.commit()
    return jsonify_side(plan_day_side, plan.id)


@plan_bp.route('/day/<day_date>/side/<int:side_id>/set', methods=['POST'])
def set_one_side(day_date, side_id):
    """AJAX endpoint behind the pencil button of ONE specific side dish:
    replaces exactly this slot with a recipe explicitly chosen by the
    user (the manual counterpart to reroll_one_side above - without
    randomness/exclusion logic, analogous to set_main_day)."""
    target_date = parse_iso_date(day_date)
    if target_date is None:
        return {"error": _("Invalid date")}, 400
    plan = current_plan()

    plan_day_side = PlanDaySide.query.join(PlanDay).filter(
        PlanDaySide.id == side_id, PlanDay.plan_id == plan.id, PlanDay.date == target_date
    ).first()
    if not plan_day_side:
        return {"error": _("This side dish does not belong to this day.")}, 404

    data = request.get_json() or {}
    try:
        recipe_id = int(data.get('recipe_id'))
    except (TypeError, ValueError):
        return {"error": _("Invalid recipe")}, 400

    recipe = visible_recipes_query(plan.id).filter_by(id=recipe_id, is_side_dish=True).first()
    if not recipe:
        return {"error": _("Recipe not found.")}, 400

    plan_day_side.recipe_id = recipe.id
    # See reroll_day() above - a manually chosen side dish is not yet cooked.
    plan_day_side.cooked = False
    db.session.commit()
    return jsonify_side(plan_day_side, plan.id)


@plan_bp.route('/day/<day_date>/side/<int:side_id>/remove', methods=['POST'])
def remove_one_side(day_date, side_id):
    """AJAX endpoint behind the X button of ONE specific side dish:
    removes exactly this slot, without touching the rest of the day
    (main dish, other side dishes, exclusion status, number of
    servings). If side_id no longer belongs to this day, that's silently
    acknowledged with {"ok": True} instead of an error - the end result
    ("this side dish is no longer present on this day") is identical
    either way."""
    target_date = parse_iso_date(day_date)
    if target_date is None:
        return {"error": _("Invalid date")}, 400
    plan = current_plan()

    plan_day_side = PlanDaySide.query.join(PlanDay).filter(
        PlanDaySide.id == side_id, PlanDay.plan_id == plan.id, PlanDay.date == target_date
    ).first()
    if plan_day_side:
        db.session.delete(plan_day_side)
        db.session.commit()
    return {"ok": True}


@plan_bp.route('/day/<day_date>/side/<int:side_id>/move/<target_date_str>', methods=['POST'])
def move_one_side(day_date, side_id, target_date_str):
    """AJAX endpoint behind drag-and-drop moving of ONE individual side
    dish onto another day card (see static/plan-sides.js:
    moveSideDish): simply reassigns the PlanDaySide row to a DIFFERENT
    PlanDay row (change plan_day_id) - a one-way move, not a swap. Unlike
    a full day swap (swap_days below, triggered by dragging the whole day
    card including the main dish), everything else on the source AND
    target day remains completely untouched.

    If no PlanDay row exists yet for the target day (e.g. because
    nothing has ever been planned there), it is created here instead of
    raising an error - analogous to add_side/reroll_one_side.
    """
    source_date = parse_iso_date(day_date)
    target_date = parse_iso_date(target_date_str)
    if source_date is None or target_date is None:
        return {"error": _("Invalid date")}, 400
    plan = current_plan()

    plan_day_side = PlanDaySide.query.join(PlanDay).filter(
        PlanDaySide.id == side_id, PlanDay.plan_id == plan.id, PlanDay.date == source_date
    ).first()
    if not plan_day_side:
        return {"error": _("This side dish does not belong to this day.")}, 404

    target_plan_day = _get_or_create_plan_day(target_date, plan.id)
    plan_day_side.plan_day_id = target_plan_day.id
    db.session.commit()
    return jsonify_side(plan_day_side, plan.id)


@plan_bp.route('/day/<day_date>/servings', methods=['POST'])
def set_day_servings(day_date):
    """AJAX endpoint for the servings input field on a day card: saves
    the desired number of servings for this calendar day permanently.

    Called "optimistically" by the frontend (the shopping list there is
    already recalculated before the server response, see static/plan.js:
    updateDayServings) - this endpoint therefore only needs to save
    reliably, it no longer needs to actively report back anything the UI
    would immediately need.

    Expects a JSON body {"servings": <number>}. Invalid or missing
    values fall back to 2 (instead of returning an error), negative or
    zero values are raised to at least 1 - a serving count of 0 or less
    would make the shopping list's quantity scaling (division by the
    target serving count) nonsensical.
    """
    target_date = parse_iso_date(day_date)
    if target_date is None:
        return {"error": _("Invalid date")}, 400
    plan = current_plan()

    data = request.get_json() or {}
    try:
        servings = max(1, int(data.get('servings', 2)))
    except (TypeError, ValueError):
        servings = 2

    plan_day = PlanDay.query.filter_by(plan_id=plan.id, date=target_date).first()
    if not plan_day:
        plan_day = PlanDay(plan_id=plan.id, date=target_date)
        db.session.add(plan_day)
    plan_day.servings = servings
    db.session.commit()
    return {"ok": True, "servings": servings}


@plan_bp.route('/day/<date_a>/swap/<date_b>', methods=['POST'])
def swap_days(date_a, date_b):
    """AJAX endpoint behind drag-and-drop swapping of two whole day cards
    on the plan page (dragging the CARD itself, not a single side dish -
    for that see move_one_side above): swaps main dish, ALL side dishes,
    exclusion status, AND cooked status of two calendar days completely
    with each other. "If the main dish moves, the side dishes come along" -
    that's why a day swap always drags along all associated PlanDaySide
    rows too, not just main_recipe_id.

    If either of the two days is still missing a PlanDay row, it is
    newly created with empty values before the swap - this way the swap
    also works when, say, a day belongs to an already created week but
    (because it's excluded and has no side dishes) has never gotten its
    own row. db.session.flush() ensures that newly created rows
    immediately have a real id before the side-dish rows below are
    reassigned to them.

    The side dishes are NOT copied individually here, but simply
    reassigned entirely to the respective other side via plan_day_id -
    more efficient than an item-by-item swap and with an identical
    result.

    The number of servings is deliberately NOT swapped: conceptually it
    belongs to the WEEKDAY itself ("on Friday there are four of us"), not
    to the dish currently placed there - a swap of the dishes should
    therefore leave this setting unchanged.
    """
    parsed_a = parse_iso_date(date_a)
    parsed_b = parse_iso_date(date_b)
    if parsed_a is None or parsed_b is None:
        return {"error": _("Invalid date")}, 400
    plan = current_plan()

    plan_day_a = PlanDay.query.filter_by(plan_id=plan.id, date=parsed_a).first()
    plan_day_b = PlanDay.query.filter_by(plan_id=plan.id, date=parsed_b).first()
    if not plan_day_a:
        plan_day_a = PlanDay(plan_id=plan.id, date=parsed_a, servings=2)
        db.session.add(plan_day_a)
    if not plan_day_b:
        plan_day_b = PlanDay(plan_id=plan.id, date=parsed_b, servings=2)
        db.session.add(plan_day_b)
    db.session.flush()

    plan_day_a.main_recipe_id, plan_day_b.main_recipe_id = plan_day_b.main_recipe_id, plan_day_a.main_recipe_id
    plan_day_a.excluded, plan_day_b.excluded = plan_day_b.excluded, plan_day_a.excluded
    # cooked belongs to the main dish, not to the weekday (unlike
    # servings, see docstring above) - so it travels WITH the swap.
    plan_day_a.cooked, plan_day_b.cooked = plan_day_b.cooked, plan_day_a.cooked

    sides_a = PlanDaySide.query.filter_by(plan_day_id=plan_day_a.id).all()
    sides_b = PlanDaySide.query.filter_by(plan_day_id=plan_day_b.id).all()
    for side in sides_a:
        side.plan_day_id = plan_day_b.id
    for side in sides_b:
        side.plan_day_id = plan_day_a.id

    db.session.commit()
    return {"ok": True}


@plan_bp.route('/day/<day_date>/cooked', methods=['POST'])
def set_day_cooked(day_date):
    """AJAX endpoint behind the "cooked" checkbox in the recipe detail
    window (see static/plan.js: openRecipeDetail/toggleCooked) for the
    MAIN DISH of a day - for a side dish see set_side_cooked below.

    Deliberately only sets this if a main dish is already assigned for
    this day (no get-or-create like e.g. in set_day_servings): a day
    without main_recipe_id also has no dish that could be marked as
    "cooked" - the detail window is only reachable via a click on an
    already-assigned dish anyway.

    Expects a JSON body {"cooked": bool}."""
    target_date = parse_iso_date(day_date)
    if target_date is None:
        return {"error": _("Invalid date")}, 400
    plan = current_plan()

    plan_day = PlanDay.query.filter_by(plan_id=plan.id, date=target_date).first()
    if not plan_day or not plan_day.main_recipe_id:
        return {"error": _("No main dish is assigned for this day.")}, 400

    data = request.get_json() or {}
    plan_day.cooked = bool(data.get('cooked'))
    db.session.commit()
    return {"ok": True, "cooked": plan_day.cooked}


@plan_bp.route('/day/<day_date>/side/<int:side_id>/cooked', methods=['POST'])
def set_side_cooked(day_date, side_id):
    """Like set_day_cooked() above, but for ONE specific side dish (a
    side dish's detail window opens with the same checkbox, see
    static/plan-sides.js: renderSidesSection).

    Expects a JSON body {"cooked": bool}."""
    target_date = parse_iso_date(day_date)
    if target_date is None:
        return {"error": _("Invalid date")}, 400
    plan = current_plan()

    plan_day_side = PlanDaySide.query.join(PlanDay).filter(
        PlanDaySide.id == side_id, PlanDay.plan_id == plan.id, PlanDay.date == target_date
    ).first()
    if not plan_day_side:
        return {"error": _("This side dish does not belong to this day.")}, 404

    data = request.get_json() or {}
    plan_day_side.cooked = bool(data.get('cooked'))
    db.session.commit()
    return {"ok": True, "cooked": plan_day_side.cooked}
