"""Which recipes a plan can use: the ones it owns plus the ones linked into
it. A separate module with no service imports to avoid circular imports."""

from models import Recipe, RecipePlanLink, db


def visible_recipe_ids_subquery(plan_id):
    owned = db.session.query(Recipe.id).filter(Recipe.owner_plan_id == plan_id)
    linked = db.session.query(RecipePlanLink.recipe_id).filter(RecipePlanLink.plan_id == plan_id)
    return owned.union(linked)


def visible_recipes_query(plan_id):
    return Recipe.query.filter(Recipe.id.in_(visible_recipe_ids_subquery(plan_id)))


def is_recipe_visible_to_plan(recipe, plan_id):
    if recipe.owner_plan_id == plan_id:
        return True
    return any(link.plan_id == plan_id for link in recipe.plan_links)
