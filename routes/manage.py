"""Management home page: a dashboard overview with key figures and a
sidebar navigation to the recipe/category/unit/ingredient/nutrition
management pages (which each live in their own blueprints -
routes/recipes.py, routes/categories.py, routes/settings.py).
Deliberately kept as its own, minimal blueprint instead of being packed
into one of the other files, since it doesn't clearly belong to any one
of the responsibilities."""

from datetime import datetime, timezone

from flask import Blueprint, render_template
from flask_babel import gettext as _

from models import Category, IngredientNutrition, Recipe
from services.auth import current_plan
from services.nutrition import list_alias_canonical_names
from services.recipe_visibility import visible_recipes_query

manage_bp = Blueprint('manage', __name__)

# How many recently edited recipes the "recently edited" list shows
# (see manage() below) - not a configuration value, since it only
# affects this one spot.
RECENT_RECIPES_LIMIT = 6


def _format_relative_day(dt):
    """Formats a point in time as a rough day distance from TODAY
    ("Today"/"Yesterday"/"N days ago") for the "recently edited" list -
    deliberately coarse (no time-of-day/hour granularity), since this
    list is only meant to give a quick overview, not an exact history."""
    days = (datetime.now(timezone.utc).replace(tzinfo=None).date() - dt.date()).days
    if days <= 0:
        return _("Today")
    if days == 1:
        return _("Yesterday")
    return _("%(days)s days ago", days=days)


@manage_bp.route('/manage')
def manage():
    """Shows the management overview page (see templates/manage.html): a
    fixed sidebar with grouped navigation (recipes/data) plus a display
    toggle, and in the main area a small row of key figures as well as the
    recently edited recipes (Recipe.updated_at, see models.py - updated on
    every save in routes/recipes.py: edit_recipe()).

    "Ingredients merged" counts the actual alias TARGET names
    (list_alias_canonical_names(), e.g. "pasta") - not the number of
    individual spellings combined into them. "Nutrition entries maintained"
    counts the number of existing IngredientNutrition reference entries.
    Everything here refers to the currently ACTIVE plan (current_plan()) -
    recipes to the ones visible to it (owner + linked, see
    services/recipe_visibility.py), categories/aliases/nutrition to the
    ones this plan itself maintains.
    """
    plan = current_plan()
    recent_recipes = (
        visible_recipes_query(plan.id).filter(Recipe.updated_at.isnot(None))
        .order_by(Recipe.updated_at.desc())
        .limit(RECENT_RECIPES_LIMIT)
        .all()
    )
    stats = {
        "recipe_count": visible_recipes_query(plan.id).count(),
        "category_count": Category.query.filter_by(plan_id=plan.id).count(),
        "aliased_ingredient_count": len(list_alias_canonical_names(plan.id)),
        "nutrition_entry_count": IngredientNutrition.query.filter_by(plan_id=plan.id).count(),
    }
    recent = [
        {"recipe": r, "when": _format_relative_day(r.updated_at)}
        for r in recent_recipes
    ]
    return render_template('manage.html', stats=stats, recent=recent)
