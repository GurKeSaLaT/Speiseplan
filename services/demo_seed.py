"""Loads fixtures/demo_data.json into an empty database.

Opt-in via SEED_DEMO_DATA=1 only: an empty database is also what a fresh
production deployment looks like. Table.insert() (instead of raw SQL)
applies column defaults, so older fixture rows still fit newer columns.
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

# Parents before children.
_MODELS_IN_DEPENDENCY_ORDER = [
    User, Plan, PlanMembership, PendingPlanInvite, Category, Recipe,
    Ingredient, RecipeSeason, RecipePlanLink, IngredientAlias,
    IngredientNutrition, AppSettings, PlanDay, PlanDaySide, ExtraShoppingItem,
]


def _coerce_temporal_columns(model, rows):
    """Date/DateTime columns need Python objects, the JSON has strings.
    Converts in place; fromisoformat handles values with and without
    microseconds."""
    datetime_columns = [c.name for c in model.__table__.columns if isinstance(c.type, DateTime)]
    date_columns = [c.name for c in model.__table__.columns if isinstance(c.type, Date)]
    for row in rows:
        for col in datetime_columns:
            if isinstance(row.get(col), str):
                row[col] = datetime.fromisoformat(row[col])
        for col in date_columns:
            if isinstance(row.get(col), str):
                row[col] = datetime.fromisoformat(row[col]).date()


def seed_demo_data_if_requested():
    """No-op unless SEED_DEMO_DATA=1 and there are no users yet."""
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
