"""Which recipes are usable for a given plan (see models/recipe.py:
Recipe.owner_plan_id/RecipePlanLink) - a recipe is visible to a plan if it
either owns it OR the recipe has additionally been embedded there via
RecipePlanLink (a real link, not a copy - see the models/recipe.py docstring
there).

Deliberately its own, extra-lean module WITHOUT further dependencies (only
models): services/planning.py already imports services/ingredient_aliases.py
and services/settings.py, which in turn (since equating ingredients/
nutrition/settings are now also plan-bound) need to know which recipes
belong to a plan - if this function lived in services/planning.py itself,
a circular import would result.
"""

from models import Recipe, RecipePlanLink, db


def visible_recipe_ids_subquery(plan_id):
    """A SQLAlchemy subquery of all recipe IDs usable for plan_id - for
    filters like Ingredient.recipe_id.in_(visible_recipe_ids_subquery(plan_id))
    or Recipe.id.in_(...)."""
    owned = db.session.query(Recipe.id).filter(Recipe.owner_plan_id == plan_id)
    linked = db.session.query(RecipePlanLink.recipe_id).filter(RecipePlanLink.plan_id == plan_id)
    return owned.union(linked)


def visible_recipes_query(plan_id):
    """Recipe.query, restricted to the recipes visible to plan_id (owner OR
    linked) - see visible_recipe_ids_subquery()."""
    return Recipe.query.filter(Recipe.id.in_(visible_recipe_ids_subquery(plan_id)))


def is_recipe_visible_to_plan(recipe, plan_id):
    """Shorthand for a single, already-loaded Recipe record - avoids its own
    database query if recipe.plan_links (see models/recipe.py: Recipe.plan_links)
    has already been (eagerly) loaded."""
    if recipe.owner_plan_id == plan_id:
        return True
    return any(link.plan_id == plan_id for link in recipe.plan_links)
