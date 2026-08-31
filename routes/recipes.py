"""Recipe management: the create/edit/delete pages for individual dishes
(Recipe), including their ingredients (Ingredient), season assignment
(RecipeSeason, managed via services/seasons.py) and the import from
chefkoch.de (via services/recipe_import.py).

recipe_create_view() and recipe_edit_view() both render the same form
template (templates/recipe_form.html), once with recipe=None (create) and
once with a loaded Recipe (edit) - recipe_edit_list_view() now only shows
the plain overview list that links there. Three POST handlers (add_recipe,
edit_recipe, delete_recipe) process the submission. import_recipe_preview()
is a fourth, JSON-based POST handler for the AJAX import button on the
create page - it saves NOTHING, but only returns the recipe data read from
a chefkoch.de URL, with which recipe_form.html pre-fills the normal form
(see services/recipe_import.py for the reason: the user has to choose the
category themselves anyway, a direct save without review would be
riskier).

A recipe belongs to ONE plan (Recipe.owner_plan_id) and can additionally be
linked into any number of further plans (RecipePlanLink, see models/recipe.py and
services/recipe_visibility.py: link_recipe_to_plan/
unlink_recipe_from_plan below) - a genuine link, not a copy. A recipe is
visible (viewable/editable) in EVERY plan that either owns it or has such a
link.

The actual season form logic (parsing checkboxes + custom date range,
pre-filling for the edit view) deliberately does NOT live here, but in
services/seasons.py - this file stays focused on "create, change, delete
Recipe/Ingredient".
"""

from datetime import datetime, timezone

from flask import Blueprint, abort, render_template, request, redirect, url_for
from flask_babel import gettext as _

from models import db, Category, Recipe, RecipePlanLink, Ingredient
from services.auth import current_plan, current_user, default_plan_id, selected_plan_id, user_has_plan_access, user_plan_memberships
from services.seasons import (
    SEASONS, save_recipe_seasons, describe_recipe_seasons, format_recipe_seasons
)
from services.ingredient_aliases import normalize_ingredient_name
from services.nutrition import compute_calories, compute_recipe_nutrition
from services.recipe_import import fetch_recipe_from_url, RecipeImportError
from services.recipe_visibility import visible_recipes_query
from services.settings import get_display_units
from services.units import convert_for_display, normalize_amount_unit

recipes_bp = Blueprint('recipes', __name__)


def _canonical_ingredient_list(plan_id):
    """Alphabetically sorted list, UNIQUE across all recipes VISIBLE for
    plan_id, of canonical (resolved via any alias mapping THIS plan may
    have, see services/ingredient_aliases.py) ingredient names - fills a
    <datalist> element in the recipe forms (autocomplete while typing an
    ingredient), so that e.g. "onion" doesn't end up as "onions" in one
    recipe and "Onion" in the next.

    Deliberately the CANONICAL names rather than the raw, actually stored
    ones: this way it suggests the already-merged name from the outset,
    instead of introducing further variants that would later have to be
    merged again. Side effect: an <input list="..."> with noticeably fewer
    options is also noticeably faster for the browser to build when it
    gains focus."""
    from services.recipe_visibility import visible_recipe_ids_subquery

    existing_ingredients = (
        db.session.query(Ingredient.name)
        .filter(Ingredient.recipe_id.in_(visible_recipe_ids_subquery(plan_id)))
        .distinct().all()
    )
    names = {normalize_ingredient_name(plan_id, name) for (name,) in existing_ingredients if name and name.strip()}
    return sorted(names)


@recipes_bp.route('/manage/recipe/create')
def recipe_create_view():
    """Shows the form for creating a new recipe - the same template as
    recipe_edit_view() below (templates/recipe_form.html), just with
    recipe=None (see the comment there). Which plan the new recipe should
    belong to is chosen explicitly by the user via a select field when
    they have multiple memberships (see templates/recipe_form.html) -
    the default is ALWAYS the starred plan (services/auth.py:
    default_plan_id(), deliberately NOT current_plan(), which could
    instead return a plan previously switched to via tab/sidebar that
    isn't necessarily starred). The "link into other plans" form doesn't
    exist here (a recipe must exist first before it can be linked - see
    recipe_edit_view)."""
    user = current_user()
    plan_id = default_plan_id(request.args, user)
    categories = Category.query.filter_by(plan_id=plan_id).order_by(Category.name).all()
    return render_template(
        'recipe_form.html', categories=categories, recipe=None,
        ingredient_list=_canonical_ingredient_list(plan_id), seasons=SEASONS,
        selected_presets=set(), custom_start='', custom_end='',
        linkable_plans=[], linked_plan_ids=set(),
        plan_id=plan_id, user_plans=user_plan_memberships(user),
    )


@recipes_bp.route('/manage/recipe/edit/<int:id>')
def recipe_edit_view(id):
    """Shows the form for editing ONE existing recipe - the same template
    as recipe_create_view() above, just with recipe set. Only reachable if
    the recipe is VISIBLE for the SELECTED plan (see services/auth.py:
    selected_plan_id - usually the tab that recipe_edit_list.html linked
    from, otherwise the active plan; see owner OR linked via
    RecipePlanLink, services/recipe_visibility.py) - anything else is to
    be treated as "doesn't exist", a 404 instead of a 403 doesn't even
    reveal whether the ID belongs to a real recipe at all.

    Categories deliberately come from the recipe's OWNER plan
    (recipe.owner_plan_id), not from the selected plan: Recipe.
    category_id always points to a category of the owner (see models/recipe.py:
    Recipe docstring) - for a merely linked-in recipe, no matching
    category could otherwise be shown/changed at all.
    linkable_plans/linked_plan_ids feed the "link into another plan"
    control (see templates/recipe_form.html). plan_id travels as a hidden
    field into the form (see there) and from there into
    edit_recipe()/link_recipe_to_plan()/unlink_recipe_from_plan() - the
    same point of view is preserved across the entire editing process,
    independent of the otherwise active plan (current_plan())."""
    user = current_user()
    plan_id = selected_plan_id(request.args, user)
    recipe = visible_recipes_query(plan_id).filter(Recipe.id == id).first()
    if recipe is None:
        abort(404)
    categories = Category.query.filter_by(plan_id=recipe.owner_plan_id).order_by(Category.name).all()

    # See the former recipe_edit_list_view() further below for the same
    # conversion/preparation step, here now only for EXACTLY ONE recipe
    # instead of for all at once. The alias/units context is deliberately
    # that of the SELECTED plan (not the owner) - someone editing a
    # merely linked-in recipe should see their OWN alias mappings/display
    # units, see services/planning.py: jsonify_recipe docstring for the
    # same principle on the plan page.
    selected_presets, custom_range = describe_recipe_seasons(recipe)
    display_units = get_display_units(plan_id)
    ingredient_display = {}
    for ing in recipe.ingredients:
        display_amount, display_unit = convert_for_display(ing.amount, ing.unit, display_units)
        ingredient_display[ing.id] = (display_amount, display_unit, normalize_ingredient_name(plan_id, ing.name))

    linked_plan_ids = {link.plan_id for link in recipe.plan_links} | {recipe.owner_plan_id}
    linkable_plans = [
        m.plan for m in user_plan_memberships(user)
        if m.plan_id not in linked_plan_ids
    ]

    return render_template(
        'recipe_form.html', categories=categories, recipe=recipe,
        ingredient_list=_canonical_ingredient_list(plan_id), seasons=SEASONS,
        selected_presets=selected_presets,
        custom_start=f"2000-{custom_range.start_month:02d}-{custom_range.start_day:02d}" if custom_range else '',
        custom_end=f"2000-{custom_range.end_month:02d}-{custom_range.end_day:02d}" if custom_range else '',
        ingredient_display=ingredient_display,
        linkable_plans=linkable_plans, linked_plan_ids=linked_plan_ids,
        plan_id=plan_id,
    )


@recipes_bp.route('/manage/recipe/edit-list')
def recipe_edit_list_view():
    """Shows the plain overview list of all recipes VISIBLE for the
    selected plan (search/filter, badges, edit/delete link) - the actual
    editing form has, since recipe_edit_view() above, lived on its own
    page per recipe; this list now only links there (see
    templates/recipe_edit_list.html: "Edit ✏️" button).

    If a user has access to more than one plan (own + shared), the page
    shows a tab switcher (see services/auth.py:
    selected_plan_id/user_plan_memberships, analogous to
    routes/categories.py) - own_plan_id is the currently selected plan
    (tab), not necessarily the otherwise active one (current_plan()):
    determines which recipes count as "own" (deletable) rather than
    merely "linked" (only removable)."""
    user = current_user()
    plan_id = selected_plan_id(request.args, user)
    recipes = visible_recipes_query(plan_id).all()
    recipe_labels = {recipe.id: format_recipe_seasons(recipe) for recipe in recipes}
    return render_template(
        'recipe_edit_list.html', recipes=recipes, recipe_labels=recipe_labels, own_plan_id=plan_id,
        plan_id=plan_id, user_plans=user_plan_memberships(user),
    )


@recipes_bp.route('/add-recipe', methods=['POST'])
def add_recipe():
    """Creates a new recipe along with its ingredients and season
    assignment, as the property of the currently active plan
    (Recipe.owner_plan_id).

    Flow: first the Recipe object is created and written to the database
    via db.session.flush() (instead of commit()) - flush() already
    assigns an ID WITHOUT closing out the transaction, so that this ID can
    be used directly for the dependent RecipeSeason and Ingredient rows.
    Only the final commit() makes everything durable together (if an
    error occurred in between, everything would be rolled back).

    The ingredients come as four parallel lists from the form
    (ing_name[], ing_amount[], ing_unit[], ing_category[] - an HTML form
    with rows added dynamically via JavaScript, see recipe_form.html),
    are merged pairwise via the shared index, and rows with an empty name
    are skipped (e.g. an unused trailing empty row in the form).
    ing_category[] is the only one of the four that is optional: an empty
    string becomes None (see services/shopping.py: UNCATEGORIZED - None
    ends up in the shopping list's miscellaneous catch-all group, with no
    extra special case needed here).

    Nutrition: is by default calculated from the ingredients (see
    services/nutrition.py: compute_recipe_nutrition(), based on the
    nutrition references OF THE ACTIVE PLAN) instead of taking the form
    fields unchecked - only when the nutrition_override checkbox is set
    (fields disabled via JS in the form, but still submitted) do the
    entered protein/carbs/fat values apply directly. calories is NEVER
    taken from the form, not even in the override case - it always
    results from protein/carbs/fat (services/nutrition.py:
    compute_calories()), so as not to allow a redundant, potentially
    contradictory calorie value. For this, the ingredient rows are
    normalized (amount/unit) BEFORE the Recipe object is created, so that
    both the calculation and the later Ingredient rows use the same,
    already canonical values.
    """
    user = current_user()
    plan_id = default_plan_id(request.form, user)
    name = request.form.get('name')
    category_id = request.form.get('category_id')
    is_side_dish = request.form.get('is_side_dish') == '1'
    is_favorite = request.form.get('is_favorite') == '1'
    nutrition_override = request.form.get('nutrition_override') == '1'
    # At least 1 serving, even if the form field is empty/invalid.
    servings = max(1, int(request.form.get('servings') or 2))
    source_url = (request.form.get('source_url') or '').strip() or None
    instructions = (request.form.get('instructions') or '').strip() or None

    ing_names = request.form.getlist('ing_name[]')
    ing_amounts = request.form.getlist('ing_amount[]')
    ing_units = request.form.getlist('ing_unit[]')
    ing_categories = request.form.getlist('ing_category[]')

    normalized_ingredients = []
    for i in range(len(ing_names)):
        if ing_names[i].strip():
            amount = float(ing_amounts[i] or 0)
            category = ing_categories[i].strip() or None if i < len(ing_categories) else None
            # Bring amount+unit into canonical form (always g/ml within
            # their family, see services/units.py) - regardless of
            # whether the user typed "1kg"/"1 kilo"/"2 tbsp" or left an
            # import/edit row already pre-filled in the display unit
            # unchanged.
            amount, unit = normalize_amount_unit(amount, ing_units[i])
            normalized_ingredients.append({"name": ing_names[i], "amount": amount, "unit": unit, "category": category})

    if nutrition_override:
        protein = float(request.form.get('protein') or 0)
        carbs = float(request.form.get('carbs') or 0)
        fat = float(request.form.get('fat') or 0)
        calories = compute_calories(protein, carbs, fat)
    else:
        computed = compute_recipe_nutrition(plan_id, normalized_ingredients, servings)
        calories, protein, carbs, fat = computed["calories"], computed["protein"], computed["carbs"], computed["fat"]

    new_recipe = Recipe(
        name=name, owner_plan_id=plan_id, category_id=category_id,
        calories=calories, protein=protein, carbs=carbs, fat=fat, nutrition_override=nutrition_override,
        is_side_dish=is_side_dish, is_favorite=is_favorite, servings=servings,
        source_url=source_url, instructions=instructions
    )
    db.session.add(new_recipe)
    db.session.flush()

    save_recipe_seasons(new_recipe.id, request.form)

    for ing in normalized_ingredients:
        db.session.add(Ingredient(
            recipe_id=new_recipe.id, name=ing["name"], amount=ing["amount"], unit=ing["unit"], category=ing["category"]
        ))

    db.session.commit()
    # Back to the "create" subpage (not the list), so the next recipe can
    # be entered right away without navigating first. plan_id ensures the
    # currently chosen plan is preserved, instead of falling back to the
    # starred one again for the next recipe (services/auth.py:
    # default_plan_id()).
    return redirect(url_for('recipes.recipe_create_view', plan_id=plan_id))


@recipes_bp.route('/edit-recipe/<int:id>', methods=['POST'])
def edit_recipe(id):
    """Fully overwrites an existing recipe with the form data. Only
    allowed if the recipe is visible for the active plan (see
    recipe_edit_view) - ANY member of a plan that owns the recipe OR that
    it's linked into may fully edit it (no distinction between owner and
    merely linked, see models/recipe.py: RecipePlanLink docstring).

    The ingredients are not reconciled one by one here (no diff of
    "changed/new/deleted"), but completely deleted and recreated from the
    form content - considerably simpler than a merge, and since the form
    always submits ALL current ingredients anyway (including unchanged
    ones), this approach loses no data. save_recipe_seasons() handles the
    season date ranges the same way.

    Nutrition: see add_recipe() - by default recalculated from the (new)
    ingredients (based on the references OF THE ACTIVE PLAN) instead of
    taking the form fields, except when the nutrition_override checkbox
    is set.
    """
    user = current_user()
    plan_id = selected_plan_id(request.form, user)
    recipe = visible_recipes_query(plan_id).filter(Recipe.id == id).first()
    if recipe is None:
        abort(404)

    recipe.name = request.form.get('name')
    recipe.category_id = request.form.get('category_id')
    recipe.is_side_dish = request.form.get('is_side_dish') == '1'
    recipe.is_favorite = request.form.get('is_favorite') == '1'
    recipe.nutrition_override = request.form.get('nutrition_override') == '1'
    recipe.servings = max(1, int(request.form.get('servings') or 2))
    recipe.source_url = (request.form.get('source_url') or '').strip() or None
    recipe.instructions = (request.form.get('instructions') or '').strip() or None
    # Explicit rather than via an onupdate=... on the column (see
    # models/recipe.py: Recipe.updated_at) - that would only trigger if at least
    # one column value actually changes, but here EVERY save should
    # count, even one with unchanged content.
    recipe.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)

    save_recipe_seasons(recipe.id, request.form)

    Ingredient.query.filter_by(recipe_id=recipe.id).delete()

    ing_names = request.form.getlist('ing_name[]')
    ing_amounts = request.form.getlist('ing_amount[]')
    ing_units = request.form.getlist('ing_unit[]')
    ing_categories = request.form.getlist('ing_category[]')

    normalized_ingredients = []
    for i in range(len(ing_names)):
        if ing_names[i].strip():
            amount = float(ing_amounts[i] or 0)
            category = ing_categories[i].strip() or None if i < len(ing_categories) else None
            # See add_recipe() above - the same normalization to canonical
            # form. Since the form fields here were pre-filled with the
            # amount already converted to the display unit (see
            # recipe_edit_view: ingredient_display), saving without any
            # change again yields exactly the original canonical value.
            amount, unit = normalize_amount_unit(amount, ing_units[i])
            normalized_ingredients.append({"name": ing_names[i], "amount": amount, "unit": unit, "category": category})

    for ing in normalized_ingredients:
        db.session.add(Ingredient(
            recipe_id=recipe.id, name=ing["name"], amount=ing["amount"], unit=ing["unit"], category=ing["category"]
        ))

    if recipe.nutrition_override:
        recipe.protein = float(request.form.get('protein') or 0)
        recipe.carbs = float(request.form.get('carbs') or 0)
        recipe.fat = float(request.form.get('fat') or 0)
        recipe.calories = compute_calories(recipe.protein, recipe.carbs, recipe.fat)
    else:
        computed = compute_recipe_nutrition(plan_id, normalized_ingredients, recipe.servings)
        recipe.calories, recipe.protein = computed["calories"], computed["protein"]
        recipe.carbs, recipe.fat = computed["carbs"], computed["fat"]

    db.session.commit()
    # Back to the edit list (unlike add_recipe, which redirects back to
    # the create page) - there's no "next" recipe here to jump directly
    # to. plan_id ensures the previously selected tab (if one was active)
    # is preserved.
    return redirect(url_for('recipes.recipe_edit_list_view', plan_id=plan_id))


@recipes_bp.route('/delete-recipe/<int:id>', methods=['POST'])
def delete_recipe(id):
    """Deletes a recipe irrevocably - only the OWNER plan
    (Recipe.owner_plan_id) may do this; a plan that only has the recipe
    additionally linked in via RecipePlanLink can instead UNLINK it again
    via unlink_recipe_from_plan() below, without deleting the recipe for
    all other plans as well. Associated Ingredient/RecipeSeason/
    RecipePlanLink rows are deleted automatically along with it via the
    cascade="all, delete-orphan" configuration in models/recipe.py.

    Deliberately NO check whether the recipe is still referenced in the
    weekly plan calendar: PlanDay.main_recipe_id and PlanDaySide.recipe_id
    are both nullable/without an ON DELETE constraint, a deleted recipe
    simply leaves a "dangling" ID there. This is a known, accepted
    behavior (see IDEAS.md) - not relevant enough so far for this app's
    small, personal use to warrant building in an extra deletion block or
    cascade for it.

    Permission: membership in the OWNER plan (Recipe.owner_plan_id), not
    necessarily the currently active plan (current_plan()) - someone
    viewing a recipe of ANOTHER own plan via a tab, for example, can still
    delete it without having to switch there first (analogous to
    routes/categories.py: delete_category())."""
    user = current_user()
    recipe = Recipe.query.get_or_404(id)
    if not user_has_plan_access(user, recipe.owner_plan_id):
        abort(403)
    owner_plan_id = recipe.owner_plan_id
    db.session.delete(recipe)
    db.session.commit()
    return redirect(url_for('recipes.recipe_edit_list_view', plan_id=owner_plan_id))


@recipes_bp.route('/manage/recipe/<int:id>/link/<int:target_plan_id>', methods=['POST'])
def link_recipe_to_plan(id, target_plan_id):
    """"Add dish to another plan": links a recipe visible for the
    selected plan (see recipe_edit_view()) ADDITIONALLY into
    target_plan_id (see models/recipe.py: RecipePlanLink) - a genuine link, not
    a copy. Requires that the logged-in user is actually a member of
    target_plan_id (otherwise they could "spam" other people's plans they
    themselves have no access to with recipes)."""
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
    plan itself CANNOT be removed via this (delete_recipe() above exists
    for that), the recipe would otherwise be left without any plan it
    belongs to.

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


@recipes_bp.route('/manage/recipe/import-preview', methods=['POST'])
def import_recipe_preview():
    """AJAX endpoint behind the "Import" button on the create page (see
    recipe_form.html): loads the given chefkoch.de URL and returns the
    recipe data read from it as JSON (see services/recipe_import.py:
    fetch_recipe_from_url). Doesn't create ANYTHING in the database
    itself - the frontend just uses this to pre-fill the normal create
    form, saving only happens via the regular add_recipe() submit path,
    after the user has reviewed/completed everything (especially the
    category).

    Expects a JSON body {"url": str}. Errors (unsupported domain, network
    error, no recipe found) come back as RecipeImportError with an
    already fully phrased error message, which ends up 1:1 in the
    {"error": ...} JSON.
    """
    data = request.get_json() or {}
    url = (data.get('url') or '').strip()
    if not url:
        return {"error": _("Please enter a link.")}, 400

    try:
        imported = fetch_recipe_from_url(url)
    except RecipeImportError as e:
        return {"error": str(e)}, 400

    # fetch_recipe_from_url() already returns ingredient amounts in
    # canonical form (g/ml, see services/recipe_import.py:
    # _parse_ingredient_line) - convert them to the user's chosen display
    # unit for the preview, so the pre-filled form is consistent with
    # every other amount display in the app (see services/units.py).
    display_units = get_display_units(current_plan().id)
    imported['ingredients'] = [
        {**ing, **dict(zip(('amount', 'unit'), convert_for_display(ing['amount'], ing['unit'], display_units)))}
        for ing in imported['ingredients']
    ]
    return imported
