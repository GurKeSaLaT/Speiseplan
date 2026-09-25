"""Recipe create/edit/delete/list views and the import-preview endpoint.

Creating a recipe takes one explicit submit; add_recipe() then redirects
into the edit view, where static/recipe_form.js autosaves every change
by resubmitting the whole form to edit_recipe() (which answers JSON for
those requests).
"""

from datetime import datetime, timezone

from flask import abort, render_template, request, redirect, url_for
from flask_babel import gettext as _

from models import db, Category, Recipe, Ingredient, PlanDay, PlanDaySide
from routes.recipes import recipes_bp
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


def _parse_float(raw, default=0.0):
    """float(raw), falling back to default for missing/non-numeric input."""
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def _parse_int(raw, default):
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def _canonical_ingredient_list(plan_id):
    """Sorted, alias-resolved ingredient names for the form's autocomplete,
    so new entries reuse the already-merged spelling."""
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
    """The target plan defaults to the starred one (default_plan_id), not
    the last viewed one."""
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
    """404 unless the recipe is visible to the selected plan. Categories come
    from the owner plan (category_id always points there); aliases and
    display units from the selected plan."""
    user = current_user()
    plan_id = selected_plan_id(request.args, user)
    recipe = visible_recipes_query(plan_id).filter(Recipe.id == id).first()
    if recipe is None:
        abort(404)
    categories = Category.query.filter_by(plan_id=recipe.owner_plan_id).order_by(Category.name).all()

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
    """own_plan_id decides which recipes are deletable (owned) vs. only
    unlinkable (linked in from another plan)."""
    user = current_user()
    plan_id = selected_plan_id(request.args, user)
    recipes = visible_recipes_query(plan_id).all()
    recipe_labels = {recipe.id: format_recipe_seasons(recipe) for recipe in recipes}
    return render_template(
        'recipe_edit_list.html', recipes=recipes, recipe_labels=recipe_labels, own_plan_id=plan_id,
        plan_id=plan_id, user_plans=user_plan_memberships(user),
    )


def _parse_ingredient_rows(form):
    """Ingredients arrive as parallel ing_*[] lists; rows without a name are
    skipped. ing_pantry[] has exactly one entry per row (a hidden mirror
    input), so unchecked boxes don't shift the alignment."""
    ing_names = form.getlist('ing_name[]')
    ing_amounts = form.getlist('ing_amount[]')
    ing_units = form.getlist('ing_unit[]')
    ing_categories = form.getlist('ing_category[]')
    ing_pantry_flags = form.getlist('ing_pantry[]')

    ingredients = []
    for i in range(len(ing_names)):
        if ing_names[i].strip():
            amount = _parse_float(ing_amounts[i])
            category = ing_categories[i].strip() or None if i < len(ing_categories) else None
            is_pantry = ing_pantry_flags[i] == '1' if i < len(ing_pantry_flags) else False
            amount, unit = normalize_amount_unit(amount, ing_units[i])
            ingredients.append({
                "name": ing_names[i], "amount": amount, "unit": unit,
                "category": category, "is_pantry": is_pantry,
            })
    return ingredients


def _nutrition_from_form(form, plan_id, ingredients, servings, nutrition_override):
    """Manual values if nutrition_override is set, otherwise computed from
    the ingredients. Calories are always derived from protein/carbs/fat.
    Returns (calories, protein, carbs, fat)."""
    if nutrition_override:
        protein = _parse_float(form.get('protein'))
        carbs = _parse_float(form.get('carbs'))
        fat = _parse_float(form.get('fat'))
        return compute_calories(protein, carbs, fat), protein, carbs, fat
    computed = compute_recipe_nutrition(plan_id, ingredients, servings)
    return computed["calories"], computed["protein"], computed["carbs"], computed["fat"]


def _add_ingredients(recipe_id, ingredients):
    for ing in ingredients:
        db.session.add(Ingredient(
            recipe_id=recipe_id, name=ing["name"], amount=ing["amount"], unit=ing["unit"],
            category=ing["category"], is_pantry=ing["is_pantry"],
        ))


@recipes_bp.route('/add-recipe', methods=['POST'])
def add_recipe():
    user = current_user()
    plan_id = default_plan_id(request.form, user)
    name = request.form.get('name')
    category_id = request.form.get('category_id')
    is_side_dish = request.form.get('is_side_dish') == '1'
    is_favorite = request.form.get('is_favorite') == '1'
    nutrition_override = request.form.get('nutrition_override') == '1'
    servings = max(1, _parse_int(request.form.get('servings'), 2))
    source_url = (request.form.get('source_url') or '').strip() or None
    instructions = (request.form.get('instructions') or '').strip() or None

    ingredients = _parse_ingredient_rows(request.form)
    calories, protein, carbs, fat = _nutrition_from_form(
        request.form, plan_id, ingredients, servings, nutrition_override)

    new_recipe = Recipe(
        name=name, owner_plan_id=plan_id, category_id=category_id,
        calories=calories, protein=protein, carbs=carbs, fat=fat, nutrition_override=nutrition_override,
        is_side_dish=is_side_dish, is_favorite=is_favorite, servings=servings,
        source_url=source_url, instructions=instructions
    )
    db.session.add(new_recipe)
    db.session.flush()

    save_recipe_seasons(new_recipe.id, request.form)
    _add_ingredients(new_recipe.id, ingredients)

    db.session.commit()
    return redirect(url_for('recipes.recipe_edit_view', id=new_recipe.id, plan_id=plan_id))


@recipes_bp.route('/edit-recipe/<int:id>', methods=['POST'])
def edit_recipe(id):
    """Overwrites the recipe with the full form (also used by autosave).
    Ingredients are deleted and recreated rather than diffed - the form
    always submits all of them."""
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
    recipe.servings = max(1, _parse_int(request.form.get('servings'), 2))
    recipe.source_url = (request.form.get('source_url') or '').strip() or None
    recipe.instructions = (request.form.get('instructions') or '').strip() or None
    # Set explicitly: onupdate only fires when a column value changes.
    recipe.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)

    save_recipe_seasons(recipe.id, request.form)

    Ingredient.query.filter_by(recipe_id=recipe.id).delete()
    ingredients = _parse_ingredient_rows(request.form)
    _add_ingredients(recipe.id, ingredients)

    recipe.calories, recipe.protein, recipe.carbs, recipe.fat = _nutrition_from_form(
        request.form, plan_id, ingredients, recipe.servings, recipe.nutrition_override)

    db.session.commit()

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return {
            "ok": True, "calories": recipe.calories, "protein": recipe.protein,
            "carbs": recipe.carbs, "fat": recipe.fat,
        }
    return redirect(url_for('recipes.recipe_edit_list_view', plan_id=plan_id))


@recipes_bp.route('/delete-recipe/<int:id>', methods=['POST'])
def delete_recipe(id):
    """Owner plan members only; linked plans unlink instead. Calendar
    references are cleared by hand since SQLite doesn't enforce ON DELETE."""
    user = current_user()
    recipe = Recipe.query.get_or_404(id)
    if not user_has_plan_access(user, recipe.owner_plan_id):
        abort(403)
    owner_plan_id = recipe.owner_plan_id
    PlanDay.query.filter_by(main_recipe_id=recipe.id).update({"main_recipe_id": None, "cooked": False})
    PlanDaySide.query.filter_by(recipe_id=recipe.id).delete()
    db.session.delete(recipe)
    db.session.commit()
    return redirect(url_for('recipes.recipe_edit_list_view', plan_id=owner_plan_id))


@recipes_bp.route('/manage/recipe/import-preview', methods=['POST'])
def import_recipe_preview():
    """Returns recipe data scraped from a URL to pre-fill the create form;
    saves nothing. Body: {"url": str}."""
    data = request.get_json() or {}
    url = (data.get('url') or '').strip()
    if not url:
        return {"error": _("Please enter a link.")}, 400

    try:
        imported = fetch_recipe_from_url(url)
    except RecipeImportError as e:
        return {"error": str(e)}, 400

    display_units = get_display_units(current_plan().id)
    imported['ingredients'] = [
        {**ing, **dict(zip(('amount', 'unit'), convert_for_display(ing['amount'], ing['unit'], display_units)))}
        for ing in imported['ingredients']
    ]
    return imported
