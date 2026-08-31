"""Shared pytest fixtures for the whole suite.

app.py already connects to the database on plain module import
(no app factory pattern, see app.py: `with app.app_context(): init_db()`
runs at module level) - the DATABASE_URL environment variable therefore
has to be set BEFORE the very first `import app`, otherwise even a
single test run would touch the real instance/speiseplan.db. The
app_module fixture is therefore session-scoped: the first test that
requests it (directly or via app/client) triggers the import exactly
once against its own temporary SQLite file; all further tests keep
using that same already-connected app.

So that every test still starts with an empty database regardless of
execution order, the autouse fixture _clean_tables wipes all tables
after EVERY test (not via rollback, since the routes themselves
commit) - tests that need specific starting data create it themselves
via the make_category/make_recipe factory fixtures below.
"""
import os

import pytest


@pytest.fixture(scope="session")
def app_module(tmp_path_factory):
    db_path = tmp_path_factory.mktemp("db") / "test.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"
    os.environ["SECRET_KEY"] = "test-secret-key"

    import app as _app_module  # noqa: PLC0415 - intentionally late, see docstring above

    _app_module.app.config["TESTING"] = True
    _app_module.app.config["WTF_CSRF_ENABLED"] = False
    return _app_module


@pytest.fixture()
def app(app_module):
    return app_module.app


@pytest.fixture()
def make_user(app):
    """Creates a user with its own starred plan (analogous to
    make_category/make_recipe below) and returns (user_id, plan_id).

    An _make() call WITHOUT an explicit username gets an automatically
    numbered name ("Testnutzer2", "Testnutzer3", ...) instead of always
    the same "Testnutzer" - otherwise a second bare make_user() call in
    the same test (or one that also uses the client fixture, which
    already creates "Testnutzer" internally, see default_plan) would
    collide with a UNIQUE constraint violation on User.username. With
    an EXPLICITLY passed name, the behavior stays unchanged."""
    from models import Plan, PlanMembership, User, db
    from services.auth import hash_password

    counter = {"n": 1}

    def _make(username=None, password="test"):
        if username is None:
            counter["n"] += 1
            username = f"Testnutzer{counter['n']}"
        with app.app_context():
            user = User(name=username, email=f"{username.lower()}@test.local", password_hash=hash_password(password))
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
    """ONE user+plan pair, cached by pytest lazily/once per test
    (standard fixture semantics: all fixtures that request default_plan
    in the SAME test get the same result) - shared basis for
    client/make_category/make_recipe below, so that a recipe/category
    created without an explicit plan_id automatically ends up in the
    same plan the test client is logged into (which is exactly what
    most tests that use client AND make_recipe/make_category together
    expect)."""
    user_id, plan_id = make_user("Testnutzer")
    return {"user_id": user_id, "plan_id": plan_id}


@pytest.fixture()
def test_plan_id(default_plan):
    """Shorthand for tests that only need the plan_id (e.g. direct unit
    tests of services/*.py functions that now require a plan_id
    argument) - the same cached result as default_plan, just without
    the dict wrapped around it."""
    return default_plan['plan_id']


@pytest.fixture()
def client(app, default_plan):
    """An already logged-in test client: ever since user management was
    added, app.py: require_login() requires an active session for
    practically every route, completely independent of what the
    respective test actually wants to check - login is thus simply
    another invisible precondition, just like _clean_tables below.
    client.user_id/client.plan_id (see attributes below) make the
    associated test user/plan accessible for tests that e.g. need to
    create a PlanDay directly via the ORM (PlanDay.plan_id is NOT
    NULL). Tests that explicitly want to check the NOT-logged-in
    behavior (redirect to /login) instead build their own, deliberately
    anonymous client directly via app.test_client() (see
    tests/test_auth.py)."""
    test_client = app.test_client()
    with test_client.session_transaction() as sess:
        sess['user_id'] = default_plan['user_id']
        sess['active_plan_id'] = default_plan['plan_id']
    test_client.user_id = default_plan['user_id']
    test_client.plan_id = default_plan['plan_id']
    return test_client


@pytest.fixture(autouse=True)
def _clean_tables(app_module):
    """Wipes all tables BEFORE every test (on the very first app import,
    init_db() seeds default categories into the otherwise empty test
    database - without this step, of all tests it would be the first
    one in the session that collides with "Fleisch"/"Fisch"/... as
    already-existing categories) AND afterwards (safety net in case a
    test aborts mid-assertion before it can clean up itself)."""
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
    """Creates a Category and returns its id (not an ORM object - that
    would count as "detached" after the end of the with block, as soon
    as Flask-SQLAlchemy removes the session when the app context
    closes). Ends up in the same plan as the client fixture without an
    explicit plan_id (see default_plan) - a test that deliberately wants
    to assign a category to a DIFFERENT plan (e.g. for isolation tests)
    passes plan_id explicitly."""
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
    """Like make_category above: without an explicit plan_id the recipe
    ends up (as owner, Recipe.owner_plan_id) in the same plan as the
    client fixture."""
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
