"""JSON endpoints for side dishes (/day/<date>/side/...). A day can have any
number of sides, so most endpoints address one PlanDaySide by id."""

from flask import request
from flask_babel import gettext as _

from models import db, PlanDay, PlanDaySide
from services.auth import current_plan
from services.planning import parse_iso_date, week_side_recipe_ids, choose_recipe, jsonify_side
from services.recipe_visibility import visible_recipes_query
from routes.plan import plan_bp


def _get_or_create_plan_day(target_date, plan_id):
    """Flushes a new row so the caller can use its id right away."""
    plan_day = PlanDay.query.filter_by(plan_id=plan_id, date=target_date).first()
    if not plan_day:
        plan_day = PlanDay(plan_id=plan_id, date=target_date, servings=2)
        db.session.add(plan_day)
        db.session.flush()
    return plan_day


@plan_bp.route('/day/<day_date>/side/add', methods=['POST'])
def add_side(day_date):
    """Adds a side: the given recipe_id as-is (manual pick), or without one
    a random side not yet used in the week."""
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
    """Replaces this side's recipe in place, so its id stays stable."""
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
    plan_day_side.cooked = False
    db.session.commit()
    return jsonify_side(plan_day_side, plan.id)


@plan_bp.route('/day/<day_date>/side/<int:side_id>/set', methods=['POST'])
def set_one_side(day_date, side_id):
    """Manual pick, no automatic rules."""
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
    plan_day_side.cooked = False
    db.session.commit()
    return jsonify_side(plan_day_side, plan.id)


@plan_bp.route('/day/<day_date>/side/<int:side_id>/remove', methods=['POST'])
def remove_one_side(day_date, side_id):
    """Idempotent: an already missing side also returns ok."""
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
    """Moves one side to another day (one-way, nothing else changes)."""
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
    """Body: {"cooked": bool}."""
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
