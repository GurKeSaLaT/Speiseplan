"""Tests for routes/plan/shopping.py: items manually added to a week's
shopping list (ExtraShoppingItem), independent of recipes."""
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

    # 2026-06-17 is a Wednesday - the item must still be assigned to the
    # Friday that starts the same (Friday-Thursday) week.
    resp = client.post("/plan/2026-06-17/shopping-item/add", json={
        "name": "Klopapier", "amount": 2, "unit": "Pack", "category": "Hygieneartikel",
    })
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["name"] == "Klopapier"
    assert data["amount"] == 2

    with app.app_context():
        item = ExtraShoppingItem.query.first()
        assert item.week_start == date(2026, 6, 12)


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
        update_display_units(client.plan_id, "kg", "ml")

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
        item = ExtraShoppingItem(plan_id=client.plan_id, week_start=date(2026, 6, 15), name="Zu löschen")
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


def test_delete_shopping_item_from_other_plan_returns_404(client, app, make_user):
    """An item belonging to a FOREIGN plan must not be deletable via its
    mere item_id, even if the ID is guessed/known (see
    routes/plan/shopping.py: delete_shopping_item() - ownership check)."""
    from models import ExtraShoppingItem, db

    _, other_plan_id = make_user("Andere")
    with app.app_context():
        item = ExtraShoppingItem(plan_id=other_plan_id, week_start=date(2026, 6, 15), name="Fremder Posten")
        db.session.add(item)
        db.session.commit()
        item_id = item.id

    resp = client.post(f"/shopping-item/{item_id}/delete")
    assert resp.status_code == 404
    with app.app_context():
        assert ExtraShoppingItem.query.count() == 1


# --- ticking off shopping-list lines ---

def test_shopping_check_is_saved_and_shown_on_reload(client, app):
    import json
    import re

    resp = client.post("/plan/2026-06-17/shopping-check", json={"key": "item:Mehl|||g", "checked": True})
    assert resp.status_code == 200

    # Saved for the week's Friday, so the week page shows it as ticked.
    page = client.get("/plan/2026-06-12").get_data(as_text=True)
    plan_data = json.loads(re.search(r"window\.PLAN_DATA = (\{.*?\});", page, re.S).group(1))
    assert plan_data["shoppingChecks"] == [{"key": "item:Mehl|||g", "amount": None, "category": None}]


def test_shopping_check_can_be_unticked_and_is_idempotent(client, app):
    from models import ShoppingListCheck

    for checked in (True, True):
        client.post("/plan/2026-06-12/shopping-check", json={"key": "extra:1", "checked": checked})
    with app.app_context():
        assert ShoppingListCheck.query.count() == 1

    for _ in range(2):
        resp = client.post("/plan/2026-06-12/shopping-check", json={"key": "extra:1", "checked": False})
        assert resp.status_code == 200
    with app.app_context():
        assert ShoppingListCheck.query.count() == 0


def test_shopping_check_is_per_week(client, app):
    import json
    import re

    client.post("/plan/2026-06-12/shopping-check", json={"key": "item:Mehl|||g", "checked": True})
    page = client.get("/plan/2026-06-19").get_data(as_text=True)
    plan_data = json.loads(re.search(r"window\.PLAN_DATA = (\{.*?\});", page, re.S).group(1))
    assert plan_data["shoppingChecks"] == []


def test_shopping_check_rejects_invalid_input(client):
    assert client.post("/plan/garbage/shopping-check", json={"key": "x", "checked": True}).status_code == 400
    assert client.post("/plan/2026-06-12/shopping-check", json={"key": " ", "checked": True}).status_code == 400
    assert client.post("/plan/2026-06-12/shopping-check", json={"key": "x" * 256, "checked": True}).status_code == 400


def test_deleting_extra_item_removes_its_check(client, app):
    from models import ShoppingListCheck

    item_id = client.post("/plan/2026-06-12/shopping-item/add", json={"name": "Klopapier"}).get_json()["id"]
    client.post("/plan/2026-06-12/shopping-check", json={"key": f"extra:{item_id}", "checked": True})
    client.post(f"/shopping-item/{item_id}/delete")
    with app.app_context():
        assert ShoppingListCheck.query.count() == 0


def _plan_data(client, start):
    import json
    import re

    page = client.get(f"/plan/{start}").get_data(as_text=True)
    return json.loads(re.search(r"window\.PLAN_DATA = (\{.*?\});", page, re.S).group(1))


def test_shopping_check_saves_ticked_amount_and_category(client):
    resp = client.post("/plan/2026-06-12/shopping-check", json={
        "key": "item:Nudeln|||g", "checked": True, "amount": 500, "category": "Teigwaren",
    })
    assert resp.status_code == 200
    assert _plan_data(client, "2026-06-12")["shoppingChecks"] == [
        {"key": "item:Nudeln|||g", "amount": 500.0, "category": "Teigwaren"},
    ]


def test_ticking_again_updates_the_amount(client, app):
    """Ticking the open rest of a partly bought line (500 g bought, 800 g
    needed) re-ticks the same key with the full amount."""
    from models import ShoppingListCheck

    client.post("/plan/2026-06-12/shopping-check", json={"key": "item:Nudeln|||g", "checked": True, "amount": 500})
    client.post("/plan/2026-06-12/shopping-check", json={"key": "item:Nudeln|||g", "checked": True, "amount": 800})
    with app.app_context():
        checks = ShoppingListCheck.query.all()
        assert [(c.item_key, c.amount) for c in checks] == [("item:Nudeln|||g", 800.0)]


def test_shopping_check_ignores_invalid_amount_and_category(client, app):
    from models import ShoppingListCheck

    for amount in ("viel", -5, True, None):
        resp = client.post("/plan/2026-06-12/shopping-check", json={
            "key": "item:Nudeln|||g", "checked": True, "amount": amount, "category": 42,
        })
        assert resp.status_code == 200
        with app.app_context():
            check = ShoppingListCheck.query.one()
            assert (check.amount, check.category) == (None, None)


def test_shopping_check_survives_reordering_days(client, app, make_recipe):
    """Bug report: swapping days wiped all ticks. Ticks are stored per week
    and line key, independent of which day a dish is on."""
    from datetime import date
    from models import PlanDay, db

    recipe_id = make_recipe("Nudelauflauf", servings=2, ingredients=[
        {"name": "Nudeln", "amount": 500, "unit": "g", "category": "Teigwaren"},
    ])
    with app.app_context():
        db.session.add(PlanDay(plan_id=client.plan_id, date=date(2026, 6, 12), main_recipe_id=recipe_id, servings=2))
        db.session.add(PlanDay(plan_id=client.plan_id, date=date(2026, 6, 13), servings=2))
        db.session.commit()

    client.post("/plan/2026-06-12/shopping-check", json={"key": "item:Nudeln|||g", "checked": True, "amount": 500})
    assert client.post("/day/2026-06-12/swap/2026-06-13").status_code == 200
    assert _plan_data(client, "2026-06-12")["shoppingChecks"] == [
        {"key": "item:Nudeln|||g", "amount": 500.0, "category": None},
    ]
