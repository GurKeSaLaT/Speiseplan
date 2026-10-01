"""JSON endpoints for manually added shopping-list items and for ticking
off shopping-list lines."""

from flask import abort, request
from flask_babel import gettext as _

from models import db, ExtraShoppingItem, ShoppingListCheck
from services.auth import current_plan
from services.planning import friday_of, parse_iso_date
from services.settings import get_display_units
from services.units import convert_for_display, normalize_amount_unit
from routes.plan import plan_bp


@plan_bp.route('/plan/<start_date>/shopping-item/add', methods=['POST'])
def add_shopping_item(start_date):
    """Body: {"name", "amount"?, "unit"?, "category"?}; only name is
    required. start_date is normalized to the week's Friday."""
    start = parse_iso_date(start_date)
    if start is None:
        return {"error": _("Invalid date")}, 400
    start = friday_of(start)

    data = request.get_json() or {}
    name = (data.get('name') or '').strip()
    if not name:
        return {"error": _("Name must not be empty.")}, 400

    try:
        raw_amount = data.get('amount')
        amount = float(raw_amount) if raw_amount not in (None, '') else None
    except (TypeError, ValueError):
        amount = None

    unit = (data.get('unit') or '').strip() or None
    category = (data.get('category') or '').strip() or None

    if amount is not None and unit is not None:
        amount, unit = normalize_amount_unit(amount, unit)

    plan = current_plan()
    item = ExtraShoppingItem(
        plan_id=plan.id, week_start=start, name=name, amount=amount, unit=unit, category=category
    )
    db.session.add(item)
    db.session.commit()

    display_amount, display_unit = (
        convert_for_display(amount, unit, get_display_units(plan.id)) if amount is not None else (None, unit)
    )
    return {"id": item.id, "name": item.name, "amount": display_amount, "unit": display_unit, "category": item.category}


@plan_bp.route('/shopping-item/<int:item_id>/delete', methods=['POST'])
def delete_shopping_item(item_id):
    item = ExtraShoppingItem.query.get_or_404(item_id)
    if item.plan_id != current_plan().id:
        abort(404)
    ShoppingListCheck.query.filter_by(
        plan_id=item.plan_id, week_start=item.week_start, item_key=f"extra:{item.id}"
    ).delete()
    db.session.delete(item)
    db.session.commit()
    return {"ok": True}


@plan_bp.route('/plan/<start_date>/shopping-check', methods=['POST'])
def set_shopping_check(start_date):
    """Body: {"key", "checked"}. Ticks a shopping-list line off (or back on)
    for the week containing start_date; idempotent either way."""
    start = parse_iso_date(start_date)
    if start is None:
        return {"error": _("Invalid date")}, 400
    start = friday_of(start)

    data = request.get_json() or {}
    key = data.get('key')
    if not isinstance(key, str) or not key.strip() or len(key) > 255:
        return {"error": _("Invalid item")}, 400

    plan = current_plan()
    existing = ShoppingListCheck.query.filter_by(plan_id=plan.id, week_start=start, item_key=key).first()
    if data.get('checked'):
        if existing is None:
            db.session.add(ShoppingListCheck(plan_id=plan.id, week_start=start, item_key=key))
    elif existing is not None:
        db.session.delete(existing)
    db.session.commit()
    return {"ok": True}
