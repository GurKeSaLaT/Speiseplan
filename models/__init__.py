"""SQLAlchemy models, re-exported so callers can `from models import X`.

db is created before the submodules are imported because they all do
`from models import db`.
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
