from flask import Blueprint, render_template, request, redirect, url_for

from models import db, Category, Recipe, Ingredient
from services.seasons import (
    SEASONS, save_recipe_seasons, describe_recipe_seasons, format_recipe_seasons
)

recipes_bp = Blueprint('recipes', __name__)


@recipes_bp.route('/manage/recipe/create')
def recipe_create_view():
    categories = Category.query.all()
    # Holt alle einzigartigen Zutatennamen, alphabetisch sortiert
    existing_ingredients = db.session.query(Ingredient.name).distinct().order_by(Ingredient.name).all()
    ingredient_list = [ing[0] for ing in existing_ingredients if ing[0]]

    return render_template('recipe_create.html', categories=categories, ingredient_list=ingredient_list, seasons=SEASONS)


@recipes_bp.route('/manage/recipe/edit-list')
def recipe_edit_list_view():
    recipes = Recipe.query.all()
    categories = Category.query.all()
    # Holt alle einzigartigen Zutatennamen, alphabetisch sortiert
    existing_ingredients = db.session.query(Ingredient.name).distinct().order_by(Ingredient.name).all()
    ingredient_list = [ing[0] for ing in existing_ingredients if ing[0]]

    # Für jedes Rezept: welche Saison-Checkboxen vorbelegt sein sollen, ein
    # eigener Zeitraum zum Vorbefüllen der Datumsfelder sowie die Badge-Labels
    recipe_season_info = {}
    for recipe in recipes:
        selected_presets, custom_range = describe_recipe_seasons(recipe)
        recipe_season_info[recipe.id] = {
            'selected_presets': selected_presets,
            # Beliebiges (Schaltjahr-)Jahr, da <input type="date"> volle Daten
            # verlangt - beim Speichern wird ohnehin nur Monat/Tag ausgewertet
            'custom_start': f"2000-{custom_range.start_month:02d}-{custom_range.start_day:02d}" if custom_range else '',
            'custom_end': f"2000-{custom_range.end_month:02d}-{custom_range.end_day:02d}" if custom_range else '',
            'labels': format_recipe_seasons(recipe),
        }

    return render_template(
        'recipe_edit_list.html', recipes=recipes, categories=categories,
        ingredient_list=ingredient_list, seasons=SEASONS, recipe_season_info=recipe_season_info
    )


@recipes_bp.route('/add-recipe', methods=['POST'])
def add_recipe():
    name = request.form.get('name')
    category_id = request.form.get('category_id')
    calories = int(request.form.get('calories') or 0)
    protein = float(request.form.get('protein') or 0)
    carbs = float(request.form.get('carbs') or 0)
    fat = float(request.form.get('fat') or 0)
    is_side_dish = request.form.get('is_side_dish') == '1'
    is_favorite = request.form.get('is_favorite') == '1'
    servings = max(1, int(request.form.get('servings') or 2))

    new_recipe = Recipe(
        name=name, category_id=category_id,
        calories=calories, protein=protein, carbs=carbs, fat=fat,
        is_side_dish=is_side_dish, is_favorite=is_favorite, servings=servings
    )
    db.session.add(new_recipe)
    db.session.flush()

    save_recipe_seasons(new_recipe.id, request.form)

    ing_names = request.form.getlist('ing_name[]')
    ing_amounts = request.form.getlist('ing_amount[]')
    ing_units = request.form.getlist('ing_unit[]')

    for i in range(len(ing_names)):
        if ing_names[i].strip():
            amount = float(ing_amounts[i] or 0)
            ingredient = Ingredient(recipe_id=new_recipe.id, name=ing_names[i], amount=amount, unit=ing_units[i])
            db.session.add(ingredient)

    db.session.commit()
    # Zurück zur "Erstellen"-Unterseite für den nächsten Eintrag
    return redirect(url_for('recipes.recipe_create_view'))


@recipes_bp.route('/edit-recipe/<int:id>', methods=['POST'])
def edit_recipe(id):
    recipe = Recipe.query.get_or_404(id)

    recipe.name = request.form.get('name')
    recipe.category_id = request.form.get('category_id')
    recipe.calories = int(request.form.get('calories') or 0)
    recipe.protein = float(request.form.get('protein') or 0)
    recipe.carbs = float(request.form.get('carbs') or 0)
    recipe.fat = float(request.form.get('fat') or 0)
    recipe.is_side_dish = request.form.get('is_side_dish') == '1'
    recipe.is_favorite = request.form.get('is_favorite') == '1'
    recipe.servings = max(1, int(request.form.get('servings') or 2))

    save_recipe_seasons(recipe.id, request.form)

    Ingredient.query.filter_by(recipe_id=recipe.id).delete()

    ing_names = request.form.getlist('ing_name[]')
    ing_amounts = request.form.getlist('ing_amount[]')
    ing_units = request.form.getlist('ing_unit[]')

    for i in range(len(ing_names)):
        if ing_names[i].strip():
            amount = float(ing_amounts[i] or 0)
            ingredient = Ingredient(recipe_id=recipe.id, name=ing_names[i], amount=amount, unit=ing_units[i])
            db.session.add(ingredient)

    db.session.commit()
    # Zurück zur Bearbeitungsliste
    return redirect(url_for('recipes.recipe_edit_list_view'))


@recipes_bp.route('/delete-recipe/<int:id>', methods=['POST'])
def delete_recipe(id):
    recipe = Recipe.query.get_or_404(id)
    db.session.delete(recipe)
    db.session.commit()
    return redirect(url_for('recipes.recipe_edit_list_view'))
