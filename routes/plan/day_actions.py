"""JSON endpoints for one calendar day's main dish plus whole-day actions
(exclude, servings, swap, cooked). Days are addressed by date rather than
week index, so e.g. the neighbor rule on reroll works across week
boundaries. Side-dish endpoints live in day_actions_sides.py."""

from flask import request
from flask_babel import gettext as _

from models import db, PlanDay, PlanDaySide
from services.auth import current_plan
from services.follow_ups import move_links_on_swap, replace_main_dish
from services.planning import parse_iso_date, jsonify_recipe, reroll_choice
from services.recipe_visibility import visible_recipes_query
from routes.plan import plan_bp


def _refill(plan_day):
    """Rolls a normal dish for a day whose follow-up dish was released."""
    chosen = reroll_choice(plan_day.plan_id, plan_day.date)
    plan_day.main_recipe_id = chosen.id if chosen else None
    plan_day.cooked = False


@plan_bp.route('/day/<day_date>/reroll-main', methods=['POST'])
def reroll_day(day_date):
    """Rolls a different main dish for one planned, non-excluded day
    (services/planning.py: reroll_choice). Linked dishes: rerolling a source
    dish re-plans its follow-up too, rerolling a follow-up only drops the
    link (services/follow_ups.py); links_changed tells the page to reload.
    """
    target_date = parse_iso_date(day_date)
    if target_date is None:
        return {"error": _("Invalid date")}, 400
    plan = current_plan()

    plan_day = PlanDay.query.filter_by(plan_id=plan.id, date=target_date).first()
    if not plan_day or plan_day.excluded:
        return {"error": _("This day is not part of a plan or is excluded from main dish planning.")}, 400

    chosen = reroll_choice(plan.id, target_date, plan_day.main_recipe_id)
    if not chosen:
        return {"error": _("No more recipes available in the database!")}, 400

    links_changed = replace_main_dish(plan.id, plan_day, chosen, _refill)
    db.session.commit()
    return {**jsonify_recipe(chosen, plan.id), "links_changed": links_changed}


@plan_bp.route('/day/<day_date>/set-main', methods=['POST'])
def set_main_day(day_date):
    """Sets a manually chosen main dish - none of the automatic rules apply
    (a follow-up dish picked by hand is just a normal dish). Also
    un-excludes the day; links are kept right like on reroll."""
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
    links_changed = replace_main_dish(plan.id, plan_day, recipe, _refill)
    db.session.commit()
    return {**jsonify_recipe(recipe, plan.id), "links_changed": links_changed}


@plan_bp.route('/day/<day_date>/toggle-exclude', methods=['POST'])
def toggle_day_exclusion(day_date):
    """Excluding clears the main dish (releasing its follow-up, or dropping
    its own link); side dishes are unaffected ("excluded" only concerns
    the main dish)."""
    target_date = parse_iso_date(day_date)
    if target_date is None:
        return {"error": _("Invalid date")}, 400
    plan = current_plan()

    plan_day = PlanDay.query.filter_by(plan_id=plan.id, date=target_date).first()
    if not plan_day:
        plan_day = PlanDay(plan_id=plan.id, date=target_date, servings=2)
        db.session.add(plan_day)

    plan_day.excluded = not plan_day.excluded
    links_changed = False
    if plan_day.excluded:
        db.session.flush()
        links_changed = replace_main_dish(plan.id, plan_day, None, _refill)
    db.session.commit()
    return {"excluded": plan_day.excluded, "links_changed": links_changed}


@plan_bp.route('/day/<day_date>/servings', methods=['POST'])
def set_day_servings(day_date):
    """Body: {"servings": int}; invalid -> 2, minimum 1 (the shopping list
    divides by it)."""
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
    """Swaps main dish, all side dishes, excluded and cooked between two
    days. Servings stay: they belong to the weekday, not the dish. Follow-up
    links travel with the dishes."""
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
    plan_day_a.cooked, plan_day_b.cooked = plan_day_b.cooked, plan_day_a.cooked
    links_changed = move_links_on_swap(plan.id, plan_day_a, plan_day_b)

    sides_a = PlanDaySide.query.filter_by(plan_day_id=plan_day_a.id).all()
    sides_b = PlanDaySide.query.filter_by(plan_day_id=plan_day_b.id).all()
    for side in sides_a:
        side.plan_day_id = plan_day_b.id
    for side in sides_b:
        side.plan_day_id = plan_day_a.id

    db.session.commit()
    return {"ok": True, "links_changed": links_changed}


@plan_bp.route('/day/<day_date>/cooked', methods=['POST'])
def set_day_cooked(day_date):
    """Body: {"cooked": bool}. Only for a day that has a main dish."""
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
