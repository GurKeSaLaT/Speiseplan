"""AJAX endpoints for items manually added to the shopping list
(ExtraShoppingItem) that don't belong to any recipe - e.g. toiletries or
drinks. Creation is week-based (start_date), while deletion is
item-based (the id is enough, no week reference needed).
"""

from flask import abort, request
from flask_babel import gettext as _

from models import db, ExtraShoppingItem
from services.auth import current_plan
from services.planning import monday_of, parse_iso_date
from services.settings import get_display_units
from services.units import convert_for_display, normalize_amount_unit
from routes.plan import plan_bp


@plan_bp.route('/plan/<start_date>/shopping-item/add', methods=['POST'])
def add_shopping_item(start_date):
    """AJAX endpoint behind the "add item" mini-form on the plan page
    (see static/plan-shopping.js: addExtraShoppingItem): creates a
    manual shopping-list item that doesn't belong to any recipe (e.g.
    toiletries). start_date is normalized to the week's Monday like
    everywhere else, so an item is consistently assigned to THE ONE week
    regardless of which date within the week the page was accessed
    through.

    Expects a JSON body {"name": str, "amount": number or null,
    "unit": str, "category": str}. name is the only required field -
    without it the entry wouldn't make sense; amount/unit/category may
    be left empty (e.g. "toilet paper" with no amount at all).
    """
    start = parse_iso_date(start_date)
    if start is None:
        return {"error": _("Invalid date")}, 400
    start = monday_of(start)

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

    # Bring into canonical form like with recipe ingredients
    # (routes/recipes/crud.py), provided an amount was given - amount may be
    # None here (unlike with Ingredient) ("toilet paper" with no amount
    # at all), normalize_amount_unit() couldn't handle None as an amount.
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
    """AJAX endpoint behind the X button of a manually added shopping-
    list item: deletes it permanently (unlike the checkbox function of
    the rest of the shopping list, which is purely client-side and not
    persistent).

    Additional ownership check (plan_id must match the active plan,
    otherwise 404 instead of silently deleting) - item_id alone would
    otherwise be guessable/usable across plan boundaries."""
    item = ExtraShoppingItem.query.get_or_404(item_id)
    if item.plan_id != current_plan().id:
        abort(404)
    db.session.delete(item)
    db.session.commit()
    return {"ok": True}
