"""JSON endpoints for side dishes (/day/<date>/side/...). A day can have any
number of sides, so most endpoints address one PlanDaySide by id.

A follow-up side (coupled to its source dish, services/follow_ups.py) loses
its coupling when it is rerolled, replaced or removed, and keeps it when it
is moved within its window (services/follow_ups.py: recouple_moved). A side
whose recipe has follow-up links is a source dish: adding it (or
rerolling/replacing a side into it) places a follow-up, rerolling, replacing
or removing it releases its follow-ups, moving it keeps them coupled while
they stay in its window. links_changed tells the page to reload then."""

from datetime import date

from flask import request
from flask.typing import ResponseReturnValue
from flask_babel import gettext as _

from models import db, Plan, PlanDay, PlanDaySide, Recipe
from services.auth import current_plan
from services.follow_ups import (
    add_side as add_side_to_day, couple_retroactively, has_follow_ups, place_follow_up, recouple_moved,
    remove_side_dish, replace_side_dish, week_shopping_servings,
)
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
def add_side(day_date: str) -> ResponseReturnValue:
    """Adds a side: the given recipe_id as-is (manual pick), or without one
    a random side not yet used in the week. Either way a side with
    follow-up links places one of its follow-ups, and a follow-up recipe
    picked by hand couples to an earlier source dish
    (services/follow_ups.py: couple_retroactively)."""
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

    plan_day_side = add_side_to_day(plan_day, chosen.id)
    coupled = couple_retroactively(plan.id, plan_day_side)
    links_changed = place_follow_up(plan.id, plan_day_side) is not None or coupled
    db.session.commit()
    return {
        **jsonify_side(plan_day_side, plan.id), "links_changed": links_changed,
        "shopping_servings": week_shopping_servings(plan.id, target_date),
    }


@plan_bp.route('/day/<day_date>/side/<int:side_id>/reroll', methods=['POST'])
def reroll_one_side(day_date: str, side_id: int) -> ResponseReturnValue:
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

    return _replace_side(plan, plan_day_side, chosen, target_date)


@plan_bp.route('/day/<day_date>/side/<int:side_id>/set', methods=['POST'])
def set_one_side(day_date: str, side_id: int) -> ResponseReturnValue:
    """Manual pick: drops the side's own coupling and handles its
    follow-ups like a reroll (services/follow_ups.py: replace_side_dish)."""
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

    return _replace_side(plan, plan_day_side, recipe, target_date)


def _replace_side(plan: Plan, plan_day_side: PlanDaySide, recipe: Recipe, target_date: date) -> dict:
    links_changed = replace_side_dish(plan.id, plan_day_side, recipe)
    db.session.commit()
    return {
        **jsonify_side(plan_day_side, plan.id), "links_changed": links_changed,
        "shopping_servings": week_shopping_servings(plan.id, target_date),
    }


@plan_bp.route('/day/<day_date>/side/<int:side_id>/remove', methods=['POST'])
def remove_one_side(day_date: str, side_id: int) -> ResponseReturnValue:
    """Idempotent: an already missing side also returns ok. Removing a
    source side releases its follow-ups."""
    target_date = parse_iso_date(day_date)
    if target_date is None:
        return {"error": _("Invalid date")}, 400
    plan = current_plan()

    plan_day_side = PlanDaySide.query.join(PlanDay).filter(
        PlanDaySide.id == side_id, PlanDay.plan_id == plan.id, PlanDay.date == target_date
    ).first()
    links_changed = False
    if plan_day_side:
        links_changed = remove_side_dish(plan.id, plan_day_side)
        db.session.commit()
    return {"ok": True, "links_changed": links_changed}


@plan_bp.route('/day/<day_date>/side/<int:side_id>/move/<target_date_str>', methods=['POST'])
def move_one_side(day_date: str, side_id: int, target_date_str: str) -> ResponseReturnValue:
    """Moves one side to another day (one-way, nothing else changes). Its
    coupling and those of its follow-ups stay while they fit their window;
    otherwise they are released and searched anew, as is a follow-up
    recipe moved onto a day without a coupling (services/follow_ups.py:
    recouple_moved)."""
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
    involved = plan_day_side.is_coupled or has_follow_ups(plan_day_side)
    plan_day_side.plan_day_id = target_plan_day.id
    links_changed = recouple_moved(plan.id, [plan_day_side]) or involved
    db.session.commit()
    return {
        **jsonify_side(plan_day_side, plan.id),
        "links_changed": links_changed,
        "shopping_servings": week_shopping_servings(plan.id, source_date),
    }


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
