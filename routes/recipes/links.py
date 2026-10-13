"""Linking a recipe into further plans (a shared row, not a copy). A recipe
tree is linked and unlinked as a whole (services/recipe_trees.py)."""

from flask import abort, redirect, request, url_for

from models import db, Recipe
from routes.recipes import recipes_bp
from services.auth import current_user, selected_plan_id, user_has_plan_access
from services.recipe_trees import TreeUnlinkError, link_tree, unlink_tree
from services.recipe_visibility import visible_recipes_query


@recipes_bp.route('/manage/recipe/<int:id>/link/<int:target_plan_id>', methods=['POST'])
def link_recipe_to_plan(id, target_plan_id):
    """The user must be a member of the target plan, so recipes can't be
    pushed into other people's plans."""
    user = current_user()
    plan_id = selected_plan_id(request.form, user)
    recipe = visible_recipes_query(plan_id).filter(Recipe.id == id).first()
    if recipe is None:
        abort(404)
    if not user_has_plan_access(user, target_plan_id):
        abort(403)
    link_tree(recipe.id, target_plan_id)
    db.session.commit()
    return redirect(url_for('recipes.recipe_edit_view', id=id, plan_id=plan_id))


@recipes_bp.route('/manage/recipe/<int:id>/unlink/<int:target_plan_id>', methods=['POST'])
def unlink_recipe_from_plan(id, target_plan_id):
    """A plan owning a recipe of the tree can't be unlinked (delete the
    recipe instead). Unlinking the plan being viewed makes the recipe
    invisible there, so that case returns to the list instead of the (now
    404) edit page."""
    user = current_user()
    plan_id = selected_plan_id(request.form, user)
    recipe = visible_recipes_query(plan_id).filter(Recipe.id == id).first()
    if recipe is None:
        abort(404)
    try:
        unlink_tree(recipe.id, target_plan_id)
    except TreeUnlinkError as error:
        abort(400, description=str(error))
    db.session.commit()
    if target_plan_id == plan_id:
        return redirect(url_for('recipes.recipe_edit_list_view', plan_id=plan_id))
    return redirect(url_for('recipes.recipe_edit_view', id=id, plan_id=plan_id))
