"""Tests für routes/plan/shopping.py: manuell zur Einkaufsliste einer
Woche hinzugefügte Posten (ExtraShoppingItem), unabhängig von Rezepten."""
from datetime import date


def test_add_shopping_item_invalid_date_returns_400(client):
    resp = client.post("/plan/garbage/shopping-item/add", json={"name": "Klopapier"})
    assert resp.status_code == 400


def test_add_shopping_item_requires_name(client):
    resp = client.post("/plan/2026-06-15/shopping-item/add", json={"name": "  "})
    assert resp.status_code == 400
    assert "error" in resp.get_json()


def test_add_shopping_item_success_normalizes_week_start(client, app):
    from models import ExtraShoppingItem

    # 2026-06-17 ist ein Mittwoch - der Posten muss trotzdem dem Montag
    # derselben Woche zugeordnet werden.
    resp = client.post("/plan/2026-06-17/shopping-item/add", json={
        "name": "Klopapier", "amount": 2, "unit": "Pack", "category": "Hygieneartikel",
    })
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["name"] == "Klopapier"
    assert data["amount"] == 2

    with app.app_context():
        item = ExtraShoppingItem.query.first()
        assert item.week_start == date(2026, 6, 15)


def test_add_shopping_item_normalizes_convertible_unit(client, app):
    from models import ExtraShoppingItem

    resp = client.post("/plan/2026-06-15/shopping-item/add", json={
        "name": "Milch", "amount": 1, "unit": "Liter",
    })
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["amount"] == 1000
    assert data["unit"] == "ml"

    with app.app_context():
        item = ExtraShoppingItem.query.first()
        assert item.amount == 1000
        assert item.unit == "ml"


def test_add_shopping_item_response_uses_display_unit(client, app):
    from services.settings import update_display_units

    with app.app_context():
        update_display_units("kg", "ml")

    resp = client.post("/plan/2026-06-15/shopping-item/add", json={
        "name": "Zucker", "amount": 2000, "unit": "g",
    })
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["amount"] == 2
    assert data["unit"] == "kg"


def test_add_shopping_item_amount_and_unit_optional(client, app):
    from models import ExtraShoppingItem

    resp = client.post("/plan/2026-06-15/shopping-item/add", json={"name": "Servietten"})
    assert resp.status_code == 200
    with app.app_context():
        item = ExtraShoppingItem.query.first()
        assert item.amount is None
        assert item.unit is None
        assert item.category is None


def test_delete_shopping_item_removes_it(client, app):
    from models import ExtraShoppingItem, db

    with app.app_context():
        item = ExtraShoppingItem(week_start=date(2026, 6, 15), name="Zu löschen")
        db.session.add(item)
        db.session.commit()
        item_id = item.id

    resp = client.post(f"/shopping-item/{item_id}/delete")
    assert resp.status_code == 200
    assert resp.get_json() == {"ok": True}
    with app.app_context():
        assert ExtraShoppingItem.query.count() == 0


def test_delete_shopping_item_unknown_id_returns_404(client):
    resp = client.post("/shopping-item/999999/delete")
    assert resp.status_code == 404
