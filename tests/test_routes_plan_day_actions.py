"""Tests for routes/plan/day_actions.py: AJAX endpoints for individual
calendar days (reroll, manual selection, side dishes, servings, swap)."""
from datetime import date


def _plan_day(app, plan_id, day_date, **kwargs):
    from models import PlanDay, db

    with app.app_context():
        pd = PlanDay(plan_id=plan_id, date=day_date, servings=kwargs.pop("servings", 2), **kwargs)
        db.session.add(pd)
        db.session.commit()
        return pd.id


# --- reroll-main ---

def test_reroll_day_invalid_date_returns_400(client):
    resp = client.post("/day/garbage/reroll-main")
    assert resp.status_code == 400


def test_reroll_day_without_plan_returns_400(client, make_recipe):
    make_recipe("Irgendwas")
    resp = client.post("/day/2026-06-15/reroll-main")
    assert resp.status_code == 400


def test_reroll_day_excluded_day_returns_400(client, app, make_recipe):
    make_recipe("Irgendwas")
    _plan_day(app, client.plan_id, date(2026, 6, 15), excluded=True)
    resp = client.post("/day/2026-06-15/reroll-main")
    assert resp.status_code == 400


def test_reroll_day_replaces_with_different_recipe(client, app, make_recipe):
    from models import PlanDay, db

    old_id = make_recipe("Alt")
    new_id = make_recipe("Neu")
    _plan_day(app, client.plan_id, date(2026, 6, 15), main_recipe_id=old_id)

    resp = client.post("/day/2026-06-15/reroll-main")
    assert resp.status_code == 200
    assert resp.get_json()["id"] == new_id

    with app.app_context():
        row = PlanDay.query.filter_by(date=date(2026, 6, 15)).first()
        assert row.main_recipe_id == new_id


def test_reroll_day_no_candidates_returns_400(client, app, make_recipe):
    only_id = make_recipe("Einziges")
    _plan_day(app, client.plan_id, date(2026, 6, 15), main_recipe_id=only_id)

    resp = client.post("/day/2026-06-15/reroll-main")
    assert resp.status_code == 400
    assert "error" in resp.get_json()


def test_reroll_day_resets_cooked(client, app, make_recipe):
    from models import PlanDay

    old_id = make_recipe("Alt")
    make_recipe("Neu")
    _plan_day(app, client.plan_id, date(2026, 6, 15), main_recipe_id=old_id, cooked=True)

    resp = client.post("/day/2026-06-15/reroll-main")
    assert resp.status_code == 200

    with app.app_context():
        row = PlanDay.query.filter_by(date=date(2026, 6, 15)).first()
        assert row.cooked is False


# --- set-main ---

def test_set_main_day_invalid_date_returns_400(client):
    resp = client.post("/day/garbage/set-main", json={"recipe_id": 1})
    assert resp.status_code == 400


def test_set_main_day_invalid_recipe_id_returns_400(client):
    resp = client.post("/day/2026-06-15/set-main", json={"recipe_id": "not-a-number"})
    assert resp.status_code == 400


def test_set_main_day_side_dish_rejected(client, make_recipe):
    side_id = make_recipe("Beilage", is_side_dish=True)
    resp = client.post("/day/2026-06-15/set-main", json={"recipe_id": side_id})
    assert resp.status_code == 400


def test_set_main_day_creates_plan_day_and_clears_excluded(client, app, make_recipe):
    from models import PlanDay, db

    recipe_id = make_recipe("Manuell gewählt")
    _plan_day(app, client.plan_id, date(2026, 6, 15), excluded=True)

    resp = client.post("/day/2026-06-15/set-main", json={"recipe_id": recipe_id})
    assert resp.status_code == 200
    assert resp.get_json()["id"] == recipe_id

    with app.app_context():
        row = PlanDay.query.filter_by(date=date(2026, 6, 15)).first()
        assert row.excluded is False
        assert row.main_recipe_id == recipe_id


def test_set_main_day_without_existing_plan_day_creates_one(client, app, make_recipe):
    from models import PlanDay

    recipe_id = make_recipe("Neuer Tag")
    resp = client.post("/day/2026-06-20/set-main", json={"recipe_id": recipe_id})
    assert resp.status_code == 200

    with app.app_context():
        row = PlanDay.query.filter_by(date=date(2026, 6, 20)).first()
        assert row is not None
        assert row.main_recipe_id == recipe_id


def test_set_main_day_resets_cooked(client, app, make_recipe):
    from models import PlanDay

    recipe_id = make_recipe("Manuell gewählt")
    _plan_day(app, client.plan_id, date(2026, 6, 15), cooked=True)

    resp = client.post("/day/2026-06-15/set-main", json={"recipe_id": recipe_id})
    assert resp.status_code == 200

    with app.app_context():
        row = PlanDay.query.filter_by(date=date(2026, 6, 15)).first()
        assert row.cooked is False


# --- side/add ---

def test_add_side_invalid_date_returns_400(client):
    resp = client.post("/day/garbage/side/add", json={})
    assert resp.status_code == 400


def test_add_side_with_explicit_recipe_id(client, app, make_recipe):
    from models import PlanDaySide

    side_id = make_recipe("Salat", is_side_dish=True)
    resp = client.post("/day/2026-06-15/side/add", json={"recipe_id": side_id})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["id"] == side_id
    assert "side_id" in data

    with app.app_context():
        assert PlanDaySide.query.count() == 1


def test_add_side_rejects_main_dish_id(client, make_recipe):
    main_id = make_recipe("Hauptgericht", is_side_dish=False)
    resp = client.post("/day/2026-06-15/side/add", json={"recipe_id": main_id})
    assert resp.status_code == 400


def test_add_side_random_pick_without_recipe_id(client, make_recipe):
    side_id = make_recipe("Einzige Beilage", is_side_dish=True)
    resp = client.post("/day/2026-06-15/side/add", json={})
    assert resp.status_code == 200
    assert resp.get_json()["id"] == side_id


def test_add_side_no_candidates_available_returns_400(client):
    resp = client.post("/day/2026-06-15/side/add", json={})
    assert resp.status_code == 400


# --- side/<id>/reroll ---

def test_reroll_one_side_wrong_day_returns_404(client, app, make_recipe):
    from models import PlanDay, PlanDaySide, db

    side_recipe_id = make_recipe("Beilage", is_side_dish=True)
    with app.app_context():
        pd = PlanDay(plan_id=client.plan_id, date=date(2026, 6, 15), servings=2)
        db.session.add(pd)
        db.session.flush()
        side = PlanDaySide(plan_day_id=pd.id, recipe_id=side_recipe_id)
        db.session.add(side)
        db.session.commit()
        side_id = side.id

    resp = client.post(f"/day/2026-06-16/side/{side_id}/reroll")
    assert resp.status_code == 404


def test_reroll_one_side_replaces_recipe_keeps_id(client, app, make_recipe):
    from models import PlanDay, PlanDaySide, db

    old_side = make_recipe("Alte Beilage", is_side_dish=True)
    new_side = make_recipe("Neue Beilage", is_side_dish=True)
    with app.app_context():
        pd = PlanDay(plan_id=client.plan_id, date=date(2026, 6, 15), servings=2)
        db.session.add(pd)
        db.session.flush()
        side = PlanDaySide(plan_day_id=pd.id, recipe_id=old_side)
        db.session.add(side)
        db.session.commit()
        side_id = side.id

    resp = client.post(f"/day/2026-06-15/side/{side_id}/reroll")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["id"] == new_side
    assert data["side_id"] == side_id


def test_reroll_one_side_resets_cooked(client, app, make_recipe):
    from models import PlanDay, PlanDaySide, db

    old_side = make_recipe("Alte Beilage", is_side_dish=True)
    make_recipe("Neue Beilage", is_side_dish=True)
    with app.app_context():
        pd = PlanDay(plan_id=client.plan_id, date=date(2026, 6, 15), servings=2)
        db.session.add(pd)
        db.session.flush()
        side = PlanDaySide(plan_day_id=pd.id, recipe_id=old_side, cooked=True)
        db.session.add(side)
        db.session.commit()
        side_id = side.id

    resp = client.post(f"/day/2026-06-15/side/{side_id}/reroll")
    assert resp.status_code == 200
    assert resp.get_json()["cooked"] is False


# --- side/<id>/set ---

def test_set_one_side_not_found_returns_404(client):
    resp = client.post("/day/2026-06-15/side/999999/set", json={"recipe_id": 1})
    assert resp.status_code == 404


def test_set_one_side_invalid_recipe_returns_400(client, app, make_recipe):
    from models import PlanDay, PlanDaySide, db

    side_recipe_id = make_recipe("Beilage", is_side_dish=True)
    with app.app_context():
        pd = PlanDay(plan_id=client.plan_id, date=date(2026, 6, 15), servings=2)
        db.session.add(pd)
        db.session.flush()
        side = PlanDaySide(plan_day_id=pd.id, recipe_id=side_recipe_id)
        db.session.add(side)
        db.session.commit()
        side_id = side.id

    resp = client.post(f"/day/2026-06-15/side/{side_id}/set", json={"recipe_id": 999999})
    assert resp.status_code == 400


def test_set_one_side_success(client, app, make_recipe):
    from models import PlanDay, PlanDaySide, db

    old_side = make_recipe("Alte Beilage", is_side_dish=True)
    new_side = make_recipe("Neue, manuell gewählt", is_side_dish=True)
    with app.app_context():
        pd = PlanDay(plan_id=client.plan_id, date=date(2026, 6, 15), servings=2)
        db.session.add(pd)
        db.session.flush()
        side = PlanDaySide(plan_day_id=pd.id, recipe_id=old_side)
        db.session.add(side)
        db.session.commit()
        side_id = side.id

    resp = client.post(f"/day/2026-06-15/side/{side_id}/set", json={"recipe_id": new_side})
    assert resp.status_code == 200
    assert resp.get_json()["id"] == new_side


def test_set_one_side_resets_cooked(client, app, make_recipe):
    from models import PlanDay, PlanDaySide, db

    old_side = make_recipe("Alte Beilage", is_side_dish=True)
    new_side = make_recipe("Neue, manuell gewählt", is_side_dish=True)
    with app.app_context():
        pd = PlanDay(plan_id=client.plan_id, date=date(2026, 6, 15), servings=2)
        db.session.add(pd)
        db.session.flush()
        side = PlanDaySide(plan_day_id=pd.id, recipe_id=old_side, cooked=True)
        db.session.add(side)
        db.session.commit()
        side_id = side.id

    resp = client.post(f"/day/2026-06-15/side/{side_id}/set", json={"recipe_id": new_side})
    assert resp.status_code == 200
    assert resp.get_json()["cooked"] is False


# --- side/<id>/remove ---

def test_remove_one_side_deletes_existing(client, app, make_recipe):
    from models import PlanDay, PlanDaySide, db

    side_recipe_id = make_recipe("Beilage", is_side_dish=True)
    with app.app_context():
        pd = PlanDay(plan_id=client.plan_id, date=date(2026, 6, 15), servings=2)
        db.session.add(pd)
        db.session.flush()
        side = PlanDaySide(plan_day_id=pd.id, recipe_id=side_recipe_id)
        db.session.add(side)
        db.session.commit()
        side_id = side.id

    resp = client.post(f"/day/2026-06-15/side/{side_id}/remove")
    assert resp.status_code == 200
    assert resp.get_json() == {"ok": True}
    with app.app_context():
        assert PlanDaySide.query.count() == 0


def test_remove_one_side_missing_id_still_returns_ok(client):
    resp = client.post("/day/2026-06-15/side/999999/remove")
    assert resp.status_code == 200
    assert resp.get_json() == {"ok": True}


# --- side/<id>/move/<target_date> ---

def test_move_one_side_wrong_source_returns_404(client):
    resp = client.post("/day/2026-06-15/side/999999/move/2026-06-16")
    assert resp.status_code == 404


def test_move_one_side_moves_to_target_creating_plan_day(client, app, make_recipe):
    from models import PlanDay, PlanDaySide, db

    side_recipe_id = make_recipe("Beilage", is_side_dish=True)
    with app.app_context():
        pd = PlanDay(plan_id=client.plan_id, date=date(2026, 6, 15), servings=2)
        db.session.add(pd)
        db.session.flush()
        side = PlanDaySide(plan_day_id=pd.id, recipe_id=side_recipe_id)
        db.session.add(side)
        db.session.commit()
        side_id = side.id

    resp = client.post(f"/day/2026-06-15/side/{side_id}/move/2026-06-20")
    assert resp.status_code == 200

    with app.app_context():
        target_pd = PlanDay.query.filter_by(date=date(2026, 6, 20)).first()
        assert target_pd is not None
        moved_side = db.session.get(PlanDaySide, side_id)
        assert moved_side.plan_day_id == target_pd.id


def test_move_one_side_preserves_cooked(client, app, make_recipe):
    from models import PlanDay, PlanDaySide, db

    side_recipe_id = make_recipe("Beilage", is_side_dish=True)
    with app.app_context():
        pd = PlanDay(plan_id=client.plan_id, date=date(2026, 6, 15), servings=2)
        db.session.add(pd)
        db.session.flush()
        side = PlanDaySide(plan_day_id=pd.id, recipe_id=side_recipe_id, cooked=True)
        db.session.add(side)
        db.session.commit()
        side_id = side.id

    resp = client.post(f"/day/2026-06-15/side/{side_id}/move/2026-06-20")
    assert resp.status_code == 200
    assert resp.get_json()["cooked"] is True


# --- servings ---

def test_set_day_servings_invalid_date_returns_400(client):
    resp = client.post("/day/garbage/servings", json={"servings": 3})
    assert resp.status_code == 400


def test_set_day_servings_valid_value(client, app):
    from models import PlanDay

    resp = client.post("/day/2026-06-15/servings", json={"servings": 5})
    assert resp.status_code == 200
    assert resp.get_json() == {"ok": True, "servings": 5}
    with app.app_context():
        row = PlanDay.query.filter_by(date=date(2026, 6, 15)).first()
        assert row.servings == 5


def test_set_day_servings_clamps_below_one(client):
    resp = client.post("/day/2026-06-15/servings", json={"servings": -3})
    assert resp.status_code == 200
    assert resp.get_json()["servings"] == 1


def test_set_day_servings_defaults_on_invalid_input(client):
    resp = client.post("/day/2026-06-15/servings", json={"servings": "not-a-number"})
    assert resp.status_code == 200
    assert resp.get_json()["servings"] == 2


# --- swap_days ---

def test_swap_days_invalid_date_returns_400(client):
    resp = client.post("/day/garbage/swap/2026-06-16")
    assert resp.status_code == 400


def test_swap_days_swaps_main_recipe_excluded_and_sides(client, app, make_recipe):
    from models import PlanDay, PlanDaySide, db

    recipe_a = make_recipe("Montagsgericht")
    recipe_b = make_recipe("Dienstagsgericht")
    side_a = make_recipe("Beilage Montag", is_side_dish=True)

    with app.app_context():
        pd_a = PlanDay(plan_id=client.plan_id, date=date(2026, 6, 15), main_recipe_id=recipe_a, excluded=False, servings=2, cooked=True)
        pd_b = PlanDay(plan_id=client.plan_id, date=date(2026, 6, 16), main_recipe_id=recipe_b, excluded=True, servings=3, cooked=False)
        db.session.add_all([pd_a, pd_b])
        db.session.flush()
        db.session.add(PlanDaySide(plan_day_id=pd_a.id, recipe_id=side_a))
        db.session.commit()

    resp = client.post("/day/2026-06-15/swap/2026-06-16")
    assert resp.status_code == 200
    assert resp.get_json() == {"ok": True}

    with app.app_context():
        row_a = PlanDay.query.filter_by(date=date(2026, 6, 15)).first()
        row_b = PlanDay.query.filter_by(date=date(2026, 6, 16)).first()

        assert row_a.main_recipe_id == recipe_b
        assert row_b.main_recipe_id == recipe_a
        assert row_a.excluded is True
        assert row_b.excluded is False
        # servings is deliberately NOT swapped along (see docstring of swap_days)
        assert row_a.servings == 2
        assert row_b.servings == 3
        # cooked belongs to the main dish (like main_recipe_id/excluded),
        # so it DOES swap along.
        assert row_a.cooked is False
        assert row_b.cooked is True
        # The side dish is now on day B, no longer on day A.
        assert PlanDaySide.query.filter_by(plan_day_id=row_a.id).count() == 0
        assert PlanDaySide.query.filter_by(plan_day_id=row_b.id).count() == 1


def test_swap_days_creates_missing_plan_day_rows(client, app):
    resp = client.post("/day/2026-06-15/swap/2026-06-16")
    assert resp.status_code == 200
    from models import PlanDay
    with app.app_context():
        assert PlanDay.query.filter_by(date=date(2026, 6, 15)).first() is not None
        assert PlanDay.query.filter_by(date=date(2026, 6, 16)).first() is not None


# --- cooked (main dish) ---

def test_set_day_cooked_invalid_date_returns_400(client):
    resp = client.post("/day/garbage/cooked", json={"cooked": True})
    assert resp.status_code == 400


def test_set_day_cooked_without_main_recipe_returns_400(client, app):
    _plan_day(app, client.plan_id, date(2026, 6, 15))
    resp = client.post("/day/2026-06-15/cooked", json={"cooked": True})
    assert resp.status_code == 400


def test_set_day_cooked_without_plan_day_returns_400(client):
    resp = client.post("/day/2026-06-15/cooked", json={"cooked": True})
    assert resp.status_code == 400


def test_set_day_cooked_toggles_true_and_false(client, app, make_recipe):
    from models import PlanDay

    recipe_id = make_recipe("Gericht")
    _plan_day(app, client.plan_id, date(2026, 6, 15), main_recipe_id=recipe_id)

    resp = client.post("/day/2026-06-15/cooked", json={"cooked": True})
    assert resp.status_code == 200
    assert resp.get_json() == {"ok": True, "cooked": True}
    with app.app_context():
        assert PlanDay.query.filter_by(date=date(2026, 6, 15)).first().cooked is True

    resp = client.post("/day/2026-06-15/cooked", json={"cooked": False})
    assert resp.status_code == 200
    assert resp.get_json() == {"ok": True, "cooked": False}
    with app.app_context():
        assert PlanDay.query.filter_by(date=date(2026, 6, 15)).first().cooked is False


# --- cooked (side dish) ---

def test_set_side_cooked_invalid_date_returns_400(client):
    resp = client.post("/day/garbage/side/1/cooked", json={"cooked": True})
    assert resp.status_code == 400


def test_set_side_cooked_wrong_day_returns_404(client, app, make_recipe):
    from models import PlanDay, PlanDaySide, db

    side_recipe_id = make_recipe("Beilage", is_side_dish=True)
    with app.app_context():
        pd = PlanDay(plan_id=client.plan_id, date=date(2026, 6, 15), servings=2)
        db.session.add(pd)
        db.session.flush()
        side = PlanDaySide(plan_day_id=pd.id, recipe_id=side_recipe_id)
        db.session.add(side)
        db.session.commit()
        side_id = side.id

    resp = client.post(f"/day/2026-06-16/side/{side_id}/cooked", json={"cooked": True})
    assert resp.status_code == 404


def test_set_side_cooked_toggles(client, app, make_recipe):
    from models import PlanDay, PlanDaySide, db

    side_recipe_id = make_recipe("Beilage", is_side_dish=True)
    with app.app_context():
        pd = PlanDay(plan_id=client.plan_id, date=date(2026, 6, 15), servings=2)
        db.session.add(pd)
        db.session.flush()
        side = PlanDaySide(plan_day_id=pd.id, recipe_id=side_recipe_id)
        db.session.add(side)
        db.session.commit()
        side_id = side.id

    resp = client.post(f"/day/2026-06-15/side/{side_id}/cooked", json={"cooked": True})
    assert resp.status_code == 200
    assert resp.get_json() == {"ok": True, "cooked": True}
    with app.app_context():
        assert db.session.get(PlanDaySide, side_id).cooked is True
