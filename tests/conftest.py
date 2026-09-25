"""Shared fixtures.

app.py binds the database at import time, so DATABASE_URL must be set
before the first `import app` (app_module, session-scoped) or tests would
hit the real instance/speiseplan.db. Tables are wiped around every test
because routes commit, which rules out rollback-based isolation.
"""
import os

import pytest


@pytest.fixture(scope="session")
def app_module(tmp_path_factory):
    db_path = tmp_path_factory.mktemp("db") / "test.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"
    os.environ["SECRET_KEY"] = "test-secret-key"

    import app as _app_module  # noqa: PLC0415 - must come after DATABASE_URL

    _app_module.app.config["TESTING"] = True
    _app_module.app.config["WTF_CSRF_ENABLED"] = False
    return _app_module


@pytest.fixture()
def app(app_module):
    return app_module.app


@pytest.fixture()
def make_user(app):
    """Creates a user with a starred plan; returns (user_id, plan_id).
    Unnamed calls get numbered names to avoid duplicate emails."""
    from models import Plan, PlanMembership, User, db

    counter = {"n": 1}

    def _make(username=None):
        if username is None:
            counter["n"] += 1
            username = f"Testnutzer{counter['n']}"
        # Spaces would make the email fail EMAIL_PATTERN on every request.
        email_local_part = username.lower().replace(' ', '.')
        with app.app_context():
            user = User(name=username, email=f"{email_local_part}@test.local")
            db.session.add(user)
            db.session.flush()
            plan = Plan(name=f"{username}s Plan", owner_user_id=user.id)
            db.session.add(plan)
            db.session.flush()
            db.session.add(PlanMembership(plan_id=plan.id, user_id=user.id, is_starred=True))
            db.session.commit()
            return user.id, plan.id

    return _make


@pytest.fixture()
def default_plan(make_user):
    """The user/plan that client, make_category and make_recipe share."""
    user_id, plan_id = make_user("Testnutzer")
    return {"user_id": user_id, "plan_id": plan_id}


@pytest.fixture()
def test_plan_id(default_plan):
    return default_plan['plan_id']


@pytest.fixture()
def login_as(app):
    """Returns a factory for a test client authenticated as user_id via the
    Authelia email header (sent with every request)."""
    def _login_as(user_id):
        from models import User, db

        with app.app_context():
            email = db.session.get(User, user_id).email
        test_client = app.test_client()
        test_client.environ_base['HTTP_REMOTE_EMAIL'] = email
        test_client.user_id = user_id
        return test_client

    return _login_as


@pytest.fixture()
def client(login_as, default_plan):
    """Authenticated client with .user_id and .plan_id. For anonymous
    requests use app.test_client() directly."""
    test_client = login_as(default_plan['user_id'])
    test_client.plan_id = default_plan['plan_id']
    return test_client


@pytest.fixture(autouse=True)
def _clean_tables(app_module):
    """Wipes all tables before (init_db seeds default categories on the
    first import) and after every test."""
    from models import db

    def _wipe():
        with app_module.app.app_context():
            for table in reversed(db.metadata.sorted_tables):
                db.session.execute(table.delete())
            db.session.commit()

    _wipe()
    yield
    _wipe()


@pytest.fixture()
def make_category(app, default_plan):
    """Returns the id (an ORM object would be detached after the context
    closes). Defaults to the client's plan."""
    from models import Category, db

    def _make(name="Testkategorie", plan_id=None):
        with app.app_context():
            cat = Category(plan_id=plan_id or default_plan['plan_id'], name=name)
            db.session.add(cat)
            db.session.commit()
            return cat.id

    return _make


@pytest.fixture()
def make_recipe(app, default_plan, make_category):
    """Returns the id; owned by the client's plan unless plan_id is given."""
    def _make(name="Testgericht", category_id=None, is_side_dish=False, ingredients=None, plan_id=None, **kwargs):
        from models import Ingredient, Recipe, db

        owner_plan_id = plan_id or default_plan['plan_id']
        if category_id is None:
            category_id = make_category(f"Kategorie für {name}", plan_id=owner_plan_id)

        with app.app_context():
            recipe = Recipe(
                name=name, owner_plan_id=owner_plan_id, category_id=category_id,
                is_side_dish=is_side_dish, **kwargs
            )
            db.session.add(recipe)
            db.session.flush()
            for ing in ingredients or []:
                db.session.add(Ingredient(recipe_id=recipe.id, **ing))
            db.session.commit()
            return recipe.id

    return _make
