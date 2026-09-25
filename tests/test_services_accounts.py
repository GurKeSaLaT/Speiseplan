"""Tests for services/accounts.py: change UI language, delete account."""


def test_update_language_success(app, client):
    from models import User, db
    from services.accounts import update_language

    with app.app_context():
        ok, error = update_language(db.session.get(User, client.user_id), "de")
        assert ok is True
        assert error is None
        assert db.session.get(User, client.user_id).language == "de"


def test_update_language_rejects_unsupported_language(app, client):
    from models import User, db
    from services.accounts import update_language

    with app.app_context():
        ok, error = update_language(db.session.get(User, client.user_id), "fr")
        assert ok is False
        assert error is not None
        assert db.session.get(User, client.user_id).language == "en"


def test_delete_account_removes_solo_plan_entirely(app, client, make_recipe):
    from models import Plan, Recipe, User, db
    from services.accounts import delete_account

    recipe_id = make_recipe("Nur hier")
    with app.app_context():
        delete_account(db.session.get(User, client.user_id))
        assert db.session.get(User, client.user_id) is None
        assert db.session.get(Plan, client.plan_id) is None
        assert db.session.get(Recipe, recipe_id) is None


def test_delete_account_keeps_shared_plan_and_transfers_ownership(app, client, make_user):
    from models import Plan, PlanMembership, User, db
    from services.accounts import delete_account

    other_id, _ = make_user("Mitbewohner")
    with app.app_context():
        db.session.add(PlanMembership(plan_id=client.plan_id, user_id=other_id, is_starred=False))
        db.session.commit()

        delete_account(db.session.get(User, client.user_id))

        assert db.session.get(User, client.user_id) is None
        plan = db.session.get(Plan, client.plan_id)
        assert plan is not None
        assert plan.owner_user_id == other_id
        assert PlanMembership.query.filter_by(plan_id=client.plan_id, user_id=client.user_id).first() is None
        assert PlanMembership.query.filter_by(plan_id=client.plan_id, user_id=other_id).first() is not None


def test_delete_account_does_not_touch_plans_where_user_is_not_owner(app, client, make_user):
    from models import Plan, PlanMembership, User, db
    from services.accounts import delete_account

    other_id, other_plan_id = make_user("Andere")
    with app.app_context():
        db.session.add(PlanMembership(plan_id=other_plan_id, user_id=client.user_id, is_starred=False))
        db.session.commit()

        delete_account(db.session.get(User, client.user_id))

        plan = db.session.get(Plan, other_plan_id)
        assert plan is not None
        assert plan.owner_user_id == other_id
        assert PlanMembership.query.filter_by(plan_id=other_plan_id, user_id=other_id).first() is not None
