"""AJAX-Endpunkte für manuell zur Einkaufsliste hinzugefügte Posten
(ExtraShoppingItem), die zu keinem Rezept gehören - z.B. Hygieneartikel
oder Getränke. Anlegen ist wochenbezogen (start_date), Löschen dagegen
postenbezogen (die id reicht, ohne Wochenbezug).
"""

from flask import request

from models import db, ExtraShoppingItem
from services.planning import monday_of, parse_iso_date
from routes.plan import plan_bp


@plan_bp.route('/plan/<start_date>/shopping-item/add', methods=['POST'])
def add_shopping_item(start_date):
    """AJAX-Endpunkt hinter dem "Artikel hinzufügen"-Mini-Formular auf der
    Plan-Seite (siehe static/plan-shopping.js: addExtraShoppingItem): legt
    einen manuellen Einkaufslisten-Posten an, der zu keinem Rezept gehört
    (z.B. Hygieneartikel). start_date wird wie überall sonst auf den
    Wochenmontag normalisiert, damit ein Artikel unabhängig davon, über
    welches Datum innerhalb der Woche die Seite gerade aufgerufen wurde,
    konsistent DER EINEN Woche zugeordnet wird.

    Erwartet einen JSON-Body {"name": str, "amount": Zahl oder null,
    "unit": str, "category": str}. name ist die einzige Pflichtangabe -
    ohne ihn ergibt der Eintrag keinen Sinn; amount/unit/category dürfen
    leer bleiben (z.B. "Klopapier" ganz ohne Mengenangabe).
    """
    start = parse_iso_date(start_date)
    if start is None:
        return {"error": "Ungültiges Datum"}, 400
    start = monday_of(start)

    data = request.get_json() or {}
    name = (data.get('name') or '').strip()
    if not name:
        return {"error": "Name darf nicht leer sein."}, 400

    try:
        raw_amount = data.get('amount')
        amount = float(raw_amount) if raw_amount not in (None, '') else None
    except (TypeError, ValueError):
        amount = None

    unit = (data.get('unit') or '').strip() or None
    category = (data.get('category') or '').strip() or None

    item = ExtraShoppingItem(week_start=start, name=name, amount=amount, unit=unit, category=category)
    db.session.add(item)
    db.session.commit()
    return {"id": item.id, "name": item.name, "amount": item.amount, "unit": item.unit, "category": item.category}


@plan_bp.route('/shopping-item/<int:item_id>/delete', methods=['POST'])
def delete_shopping_item(item_id):
    """AJAX-Endpunkt hinter dem ❌-Button eines manuell hinzugefügten
    Einkaufslisten-Postens: löscht ihn endgültig (im Gegensatz zur
    Ankreuzen-Funktion der übrigen Einkaufsliste, die rein clientseitig und
    nicht dauerhaft ist)."""
    item = ExtraShoppingItem.query.get_or_404(item_id)
    db.session.delete(item)
    db.session.commit()
    return {"ok": True}
