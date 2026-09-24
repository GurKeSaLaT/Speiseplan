"""Tests for services/demo_seed.py: loading fixtures/demo_data.json into
an otherwise empty database - see the module docstring there for why
this is opt-in (SEED_DEMO_DATA=1) rather than automatic."""


def test_seed_demo_data_noops_without_env_var(app, monkeypatch):
    from models import User
    from services.demo_seed import seed_demo_data_if_requested

    monkeypatch.delenv("SEED_DEMO_DATA", raising=False)
    with app.app_context():
        seed_demo_data_if_requested()
        assert User.query.count() == 0


def test_seed_demo_data_loads_fixture_when_requested(app, monkeypatch):
    from models import Category, Ingredient, Plan, PlanDay, Recipe, User, db
    from services.demo_seed import seed_demo_data_if_requested

    monkeypatch.setenv("SEED_DEMO_DATA", "1")
    with app.app_context():
        seed_demo_data_if_requested()

        assert User.query.count() > 0
        assert Plan.query.count() > 0
        assert Category.query.count() > 0
        assert Recipe.query.count() > 0
        assert Ingredient.query.count() > 0
        assert PlanDay.query.count() > 0

        # Foreign keys survived the bulk insert (recipes actually belong
        # to a plan that exists, ingredients to a recipe that exists).
        recipe = Recipe.query.first()
        assert db.session.get(Plan, recipe.owner_plan_id) is not None
        ingredient = Ingredient.query.first()
        assert db.session.get(Recipe, ingredient.recipe_id) is not None

        # A column that postdates the fixture (or simply wasn't set on a
        # given row) still gets its normal model default, exactly like a
        # freshly created row would (see services/demo_seed.py:
        # _coerce_temporal_columns docstring for the general point this
        # makes about Table.insert() vs. hand-written SQL).
        assert ingredient.is_pantry in (True, False)


def test_seed_demo_data_is_idempotent(app, monkeypatch):
    from models import User
    from services.demo_seed import seed_demo_data_if_requested

    monkeypatch.setenv("SEED_DEMO_DATA", "1")
    with app.app_context():
        seed_demo_data_if_requested()
        count_after_first = User.query.count()
        assert count_after_first > 0

        seed_demo_data_if_requested()
        assert User.query.count() == count_after_first
