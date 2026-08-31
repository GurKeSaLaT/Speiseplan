"""AJAX endpoints called by the client-side static/plan-sides.js that
return JSON - for the SIDE DISHES of individual calendar days
(/day/<day_date>/side/...). Split out from routes/plan/day_actions.py
(which covers the main-dish/whole-day actions) because these are
additionally ITEM-specific (a day can have several side dishes, see
models/calendar.py: PlanDaySide) - all but "add" therefore address one
specific PlanDaySide row via <int:side_id>.
"""

from flask import request
from flask_babel import gettext as _

from models import db, PlanDay, PlanDaySide
from services.auth import current_plan
from services.planning import parse_iso_date, week_side_recipe_ids, choose_recipe, jsonify_side
from services.recipe_visibility import visible_recipes_query
from routes.plan import plan_bp


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
    see models/calendar.py: PlanDaySide).

    Expects a JSON body {"recipe_id": <id> or null}:
    - If recipe_id is set (the picker button in
      static/plan-sides.js: openSideManualSelect), EXACTLY this
      user-chosen recipe is used - without any randomness/exclusion
      logic, analogous to routes/plan/day_actions.py: set_main_day().
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
    # See routes/plan/day_actions.py: reroll_day() - a freshly rolled
    # side dish is not yet cooked.
    plan_day_side.cooked = False
    db.session.commit()
    return jsonify_side(plan_day_side, plan.id)


@plan_bp.route('/day/<day_date>/side/<int:side_id>/set', methods=['POST'])
def set_one_side(day_date, side_id):
    """AJAX endpoint behind the pencil button of ONE specific side dish:
    replaces exactly this slot with a recipe explicitly chosen by the
    user (the manual counterpart to reroll_one_side above - without
    randomness/exclusion logic, analogous to
    routes/plan/day_actions.py: set_main_day)."""
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
    # See routes/plan/day_actions.py: reroll_day() - a manually chosen
    # side dish is not yet cooked.
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
    a full day swap (routes/plan/day_actions.py: swap_days, triggered by
    dragging the whole day card including the main dish), everything else
    on the source AND target day remains completely untouched.

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


@plan_bp.route('/day/<day_date>/side/<int:side_id>/cooked', methods=['POST'])
def set_side_cooked(day_date, side_id):
    """Like routes/plan/day_actions.py: set_day_cooked() above, but for
    ONE specific side dish (a side dish's detail window opens with the
    same checkbox, see static/plan-sides.js: renderSidesSection).

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
