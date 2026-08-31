"""Linking one recipe into another plan (see routes/recipes/__init__.py
for how this fits into the recipes_bp package) - a distinct concern from
routes/recipes/crud.py: sharing an existing recipe across plans, not
creating/editing/deleting the recipe itself.

A recipe belongs to ONE plan (Recipe.owner_plan_id) and can additionally
be linked into any number of further plans (RecipePlanLink, see
models/recipe.py) - a genuine link, not a copy. A recipe is visible
(viewable/editable) in EVERY plan that either owns it or has such a link.
"""

from flask import abort, redirect, request, url_for

from models import db, Recipe, RecipePlanLink
from routes.recipes import recipes_bp
from services.auth import current_user, selected_plan_id, user_has_plan_access
from services.recipe_visibility import visible_recipes_query


@recipes_bp.route('/manage/recipe/<int:id>/link/<int:target_plan_id>', methods=['POST'])
def link_recipe_to_plan(id, target_plan_id):
    """"Add dish to another plan": links a recipe visible for the
    selected plan (see routes/recipes/crud.py: recipe_edit_view())
    ADDITIONALLY into target_plan_id (see models/recipe.py:
    RecipePlanLink) - a genuine link, not a copy. Requires that the
    logged-in user is actually a member of target_plan_id (otherwise they
    could "spam" other people's plans they themselves have no access to
    with recipes)."""
    user = current_user()
    plan_id = selected_plan_id(request.form, user)
    recipe = visible_recipes_query(plan_id).filter(Recipe.id == id).first()
    if recipe is None:
        abort(404)
    if not user_has_plan_access(user, target_plan_id):
        abort(403)
    if target_plan_id != recipe.owner_plan_id and not RecipePlanLink.query.filter_by(
        recipe_id=recipe.id, plan_id=target_plan_id
    ).first():
        db.session.add(RecipePlanLink(recipe_id=recipe.id, plan_id=target_plan_id))
        db.session.commit()
    return redirect(url_for('recipes.recipe_edit_view', id=id, plan_id=plan_id))


@recipes_bp.route('/manage/recipe/<int:id>/unlink/<int:target_plan_id>', methods=['POST'])
def unlink_recipe_from_plan(id, target_plan_id):
    """Removes a link set via link_recipe_to_plan() again - the OWNER
    plan itself CANNOT be removed via this (routes/recipes/crud.py:
    delete_recipe() exists for that), the recipe would otherwise be left
    without any plan it belongs to.

    If, of all plans, the currently selected plan (plan_id) is the target
    of the removal (the normal case for the "Remove 🔗" button on
    recipe_edit_list.html - see target_plan_id=own_plan_id there), the
    recipe becomes invisible for THIS view: a redirect back to
    recipe_edit_view() would then immediately return 404, since
    visible_recipes_query(plan_id) no longer finds it - hence in this
    case, back to the list instead of the (no longer reachable) detail
    page. If instead ANOTHER plan is removed (the "✕" badges in
    templates/recipe_form.html for the remaining links), the recipe
    remains visible via plan_id - back to the detail page there."""
    user = current_user()
    plan_id = selected_plan_id(request.form, user)
    recipe = visible_recipes_query(plan_id).filter(Recipe.id == id).first()
    if recipe is None:
        abort(404)
    if target_plan_id == recipe.owner_plan_id:
        abort(400)
    RecipePlanLink.query.filter_by(recipe_id=recipe.id, plan_id=target_plan_id).delete()
    db.session.commit()
    if target_plan_id == plan_id:
        return redirect(url_for('recipes.recipe_edit_list_view', plan_id=plan_id))
    return redirect(url_for('recipes.recipe_edit_view', id=id, plan_id=plan_id))
