"""SQLAlchemy data models for the Speiseplan app, split by domain into
this package's modules:

    models/user.py     - User
    models/plan.py      - Plan, PlanMembership, PendingPlanInvite
    models/recipe.py    - Category, Recipe, RecipePlanLink, RecipeSeason, Ingredient
    models/calendar.py  - PlanDay, PlanDaySide, ExtraShoppingItem
    models/settings.py  - AppSettings, IngredientAlias, IngredientNutrition

db = SQLAlchemy() is created HERE, first, and every submodule does
`from models import db` to reuse this one shared instance/registry -
db.relationship('SomeClassName', ...) resolves the target class by name
against that shared registry at mapper-configuration time (not at import
time), so which file a class is defined in doesn't matter for
relationships to work, as long as every class ends up imported (as they
all are, below) before the app runs its first query. Every existing
`from models import X, Y` call site across the rest of the codebase keeps
working unchanged, since this file re-exports every model.

Table relationships, for reference (unchanged from before the split):

    Category 1---n Recipe 1---n Ingredient
                      |  1
                      |  n
                RecipeSeason

    Recipe 1---n PlanDay (as main_recipe)
    Recipe 1---n PlanDaySide n---1 PlanDay

    ExtraShoppingItem (standalone, only loosely tied to a calendar week via
                        week_start - no foreign key)
"""

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

from models.user import User
from models.plan import Plan, PlanMembership, PendingPlanInvite
from models.recipe import Category, Recipe, RecipePlanLink, RecipeSeason, Ingredient
from models.calendar import PlanDay, PlanDaySide, ExtraShoppingItem
from models.settings import AppSettings, IngredientAlias, IngredientNutrition

__all__ = [
    'db',
    'User',
    'Plan', 'PlanMembership', 'PendingPlanInvite',
    'Category', 'Recipe', 'RecipePlanLink', 'RecipeSeason', 'Ingredient',
    'PlanDay', 'PlanDaySide', 'ExtraShoppingItem',
    'AppSettings', 'IngredientAlias', 'IngredientNutrition',
]
