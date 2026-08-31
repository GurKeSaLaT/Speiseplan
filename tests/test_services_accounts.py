"""Tests for services/accounts.py: change profile, change password,
delete account."""


def test_update_profile_success(app, client):
    from models import User
    from services.accounts import update_profile

    with app.app_context():
        ok, error = update_profile(User.query.get(client.user_id), "Neuer Name", "neu@test.local", "en")
        assert ok is True
        assert error is None
        user = User.query.get(client.user_id)
        assert user.name == "Neuer Name"
        assert user.email == "neu@test.local"


def test_update_profile_normalizes_email_lowercase(app, client):
    from models import User
    from services.accounts import update_profile

    with app.app_context():
        update_profile(User.query.get(client.user_id), "X", "GROSS@Test.Local", "en")
        assert User.query.get(client.user_id).email == "gross@test.local"


def test_update_profile_rejects_duplicate_email(app, client, make_user):
    from models import User
    from services.accounts import update_profile

    other_id, _ = make_user("Andere")
    with app.app_context():
        other_email = User.query.get(other_id).email
        ok, error = update_profile(User.query.get(client.user_id), "X", other_email, "en")
        assert ok is False
        assert "already exists" in error


def test_update_profile_rejects_malformed_email(app, client):
    from models import User
    from services.accounts import update_profile

    with app.app_context():
        ok, error = update_profile(User.query.get(client.user_id), "X", "keine-email", "en")
        assert ok is False
        assert "valid email address" in error


def test_update_profile_rejects_empty_fields(app, client):
    from models import User
    from services.accounts import update_profile

    with app.app_context():
        ok, error = update_profile(User.query.get(client.user_id), "", "", "en")
        assert ok is False


def test_update_profile_changes_language(app, client):
    from models import User
    from services.accounts import update_profile

    with app.app_context():
        ok, error = update_profile(User.query.get(client.user_id), "X", "x@test.local", "de")
        assert ok is True
        assert User.query.get(client.user_id).language == "de"


def test_update_profile_rejects_unsupported_language(app, client):
    from models import User
    from services.accounts import update_profile

    with app.app_context():
        ok, error = update_profile(User.query.get(client.user_id), "X", "x2@test.local", "fr")
        assert ok is False
        assert error is not None


def test_update_password_requires_correct_current_password(app, client):
    from models import User
    from services.accounts import update_password

    with app.app_context():
        ok, error = update_password(User.query.get(client.user_id), "falsch", "neuespw")
        assert ok is False
        assert "incorrect" in error


def test_update_password_success(app, client):
    from models import User
    from services.accounts import update_password
    from services.auth import verify_password

    with app.app_context():
        ok, error = update_password(User.query.get(client.user_id), "test", "neuespw123")
        assert ok is True
        assert verify_password(User.query.get(client.user_id), "neuespw123")


def test_update_password_rejects_empty_new_password(app, client):
    from models import User
    from services.accounts import update_password

    with app.app_context():
        ok, error = update_password(User.query.get(client.user_id), "test", "")
        assert ok is False


def test_delete_account_removes_solo_plan_entirely(app, client, make_recipe):
    from models import Plan, Recipe, User
    from services.accounts import delete_account

    recipe_id = make_recipe("Nur hier")
    with app.app_context():
        delete_account(User.query.get(client.user_id))
        assert User.query.get(client.user_id) is None
        assert Plan.query.get(client.plan_id) is None
        assert Recipe.query.get(recipe_id) is None


def test_delete_account_keeps_shared_plan_and_transfers_ownership(app, client, make_user):
    from models import Plan, PlanMembership, User, db
    from services.accounts import delete_account

    other_id, _ = make_user("Mitbewohner")
    with app.app_context():
        db.session.add(PlanMembership(plan_id=client.plan_id, user_id=other_id, is_starred=False))
        db.session.commit()

        delete_account(User.query.get(client.user_id))

        assert User.query.get(client.user_id) is None
        plan = Plan.query.get(client.plan_id)
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

        delete_account(User.query.get(client.user_id))

        plan = Plan.query.get(other_plan_id)
        assert plan is not None
        assert plan.owner_user_id == other_id
        assert PlanMembership.query.filter_by(plan_id=other_plan_id, user_id=other_id).first() is not None
