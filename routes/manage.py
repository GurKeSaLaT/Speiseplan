"""Management dashboard (/manage): key figures and recently edited recipes
for the active plan."""

from datetime import datetime, timezone

from flask import Blueprint, render_template
from flask_babel import gettext as _

from models import Category, IngredientNutrition, Recipe
from services.auth import current_plan
from services.nutrition import list_alias_canonical_names
from services.recipe_visibility import visible_recipes_query

manage_bp = Blueprint('manage', __name__)

RECENT_RECIPES_LIMIT = 6


def _format_relative_day(dt):
    """"Today" / "Yesterday" / "N days ago"."""
    days = (datetime.now(timezone.utc).replace(tzinfo=None).date() - dt.date()).days
    if days <= 0:
        return _("Today")
    if days == 1:
        return _("Yesterday")
    return _("%(days)s days ago", days=days)


@manage_bp.route('/manage')
def manage():
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
