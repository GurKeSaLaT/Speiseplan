"""One-time demo-data seeding for a brand new, empty database - loads
fixtures/demo_data.json (recipes/categories/ingredient aliases etc. for
two example accounts) via SQLAlchemy Core bulk inserts, in the same
order the tables' foreign keys depend on each other.

Deliberately NOT automatic just because the database happens to be
empty: a completely empty database is also the exact state of a brand
new PRODUCTION deployment before its first real Authelia login (see
services/auth.py module docstring) - auto-seeding on that condition
alone would wrongly inject demo content into every fresh real
deployment. Seeding therefore additionally requires the
SEED_DEMO_DATA=1 environment variable to be set explicitly (see
README.md: "Local development without Authelia").

This sample data used to be shipped as a committed binary SQLite file
(instance/speiseplan.db) - every edit to it showed up as an opaque,
undiffable binary change in git history. fixtures/demo_data.json is the
same content as plain, diffable, human-readable text instead; loading it
via SQLAlchemy Core's Table.insert() (rather than hand-written SQL
text) means a row that predates a later-added column (e.g. an ingredient
row from before Ingredient.is_pantry existed) still gets that column's
normal Python-side default applied automatically, exactly like the ORM
would for a freshly created row - no separate handling needed here for
"the fixture is one column behind the current schema".
"""

import json
import os
from datetime import datetime

from sqlalchemy import Date, DateTime

from models import (
    db, User, Plan, PlanMembership, PendingPlanInvite, Category, Recipe,
    Ingredient, RecipeSeason, RecipePlanLink, IngredientAlias,
    IngredientNutrition, AppSettings, PlanDay, PlanDaySide, ExtraShoppingItem,
)

FIXTURE_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'fixtures', 'demo_data.json')

# Parents before children, matching the foreign keys between these
# tables (see models/*.py) - e.g. Recipe references Category and Plan,
# so both must already exist before any Recipe row is inserted.
_MODELS_IN_DEPENDENCY_ORDER = [
    User, Plan, PlanMembership, PendingPlanInvite, Category, Recipe,
    Ingredient, RecipeSeason, RecipePlanLink, IngredientAlias,
    IngredientNutrition, AppSettings, PlanDay, PlanDaySide, ExtraShoppingItem,
]


def _coerce_temporal_columns(model, rows):
    """JSON has no native date/datetime type - the fixture stores them as
    plain "YYYY-MM-DD[ HH:MM:SS]" text (exactly how SQLite itself
    displays them). A raw INSERT of that text works fine against SQLite
    directly, but going through SQLAlchemy Core's Table.insert() (see
    module docstring for why that's worth it) means the DateTime/Date
    column types' bind processors run first and reject a plain string -
    they need an actual datetime.datetime/datetime.date object. Converts
    every column of either type on rows IN PLACE (mutating the dicts
    already loaded from the fixture, no need to copy)."""
    datetime_columns = [c.name for c in model.__table__.columns if isinstance(c.type, DateTime)]
    date_columns = [c.name for c in model.__table__.columns if isinstance(c.type, Date)]
    for row in rows:
        for col in datetime_columns:
            if isinstance(row.get(col), str):
                # db.func.now() (see models/user.py, models/plan.py:
                # created_at) sometimes includes microseconds, sometimes
                # doesn't (SQLite's CURRENT_TIMESTAMP vs. a Python-side
                # now() rounds differently depending on how the row was
                # originally created) - fromisoformat() handles both in
                # one call, unlike a single fixed strptime() format.
                row[col] = datetime.fromisoformat(row[col])
        for col in date_columns:
            if isinstance(row.get(col), str):
                row[col] = datetime.fromisoformat(row[col]).date()


def seed_demo_data_if_requested():
    """Called once at startup, right after migrations (see app.py) -
    no-ops unless explicitly requested AND the database doesn't already
    have at least one user (never overwrites/duplicates into a database
    that's already in real use, including one that was seeded before)."""
    if os.environ.get('SEED_DEMO_DATA') != '1':
        return
    if User.query.first() is not None:
        return
    if not os.path.exists(FIXTURE_PATH):
        return

    with open(FIXTURE_PATH, 'r', encoding='utf-8') as f:
        data = json.load(f)

    for model in _MODELS_IN_DEPENDENCY_ORDER:
        rows = data.get(model.__tablename__)
        if rows:
            _coerce_temporal_columns(model, rows)
            db.session.execute(model.__table__.insert(), rows)
    db.session.commit()
