import os
import random
from flask import Flask, render_template, request, redirect, url_for
from models import db, Category, Recipe, Ingredient

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(app.instance_path, 'speiseplan.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

os.makedirs(app.instance_path, exist_ok=True)
db.init_app(app)

def init_db():
    db.create_all()
    if not Category.query.first():
        default_categories = ["Fleisch", "Fisch", "Vegetarisch", "Vegan", "Nudeln/Pasta", "Suppe/Eintopf", "Schnelle Küche"]
        for cat_name in default_categories:
            db.session.add(Category(name=cat_name))
        db.session.commit()

with app.app_context():
    init_db()

# 1. HAUPTSEITE: Reine Essensauswahl
@app.route('/')
def index():
    recipes = Recipe.query.all()
    categories = Category.query.all()
    return render_template('index.html', recipes=recipes, categories=categories)

# --- NEU STRUKTURIERTE VERWALTUNGS-ROUTEN ---

@app.route('/manage')
def manage():
    return render_template('manage.html')

@app.route('/manage/recipe/create')
def recipe_create_view():
    categories = Category.query.all()
    return render_template('recipe_create.html', categories=categories)

@app.route('/manage/recipe/edit-list')
def recipe_edit_list_view():
    recipes = Recipe.query.all()
    categories = Category.query.all()
    return render_template('recipe_edit_list.html', recipes=recipes, categories=categories)

@app.route('/manage/categories')
def category_manage_view():
    categories = Category.query.all()
    return render_template('category_manage.html', categories=categories)


# --- SPEICHER- UND LÖSCH-AKTIONEN (Leiten nun auf die jeweiligen Unterseiten zurück) ---

@app.route('/add-recipe', methods=['POST'])
def add_recipe():
    name = request.form.get('name')
    category_id = request.form.get('category_id')
    calories = int(request.form.get('calories') or 0)
    protein = float(request.form.get('protein') or 0)
    carbs = float(request.form.get('carbs') or 0)
    fat = float(request.form.get('fat') or 0)

    new_recipe = Recipe(
        name=name, category_id=category_id,
        calories=calories, protein=protein, carbs=carbs, fat=fat
    )
    db.session.add(new_recipe)
    db.session.flush()

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
    return redirect(url_for('recipe_create_view'))

@app.route('/edit-recipe/<int:id>', methods=['POST'])
def edit_recipe(id):
    recipe = Recipe.query.get_or_404(id)

    recipe.name = request.form.get('name')
    recipe.category_id = request.form.get('category_id')
    recipe.calories = int(request.form.get('calories') or 0)
    recipe.protein = float(request.form.get('protein') or 0)
    recipe.carbs = float(request.form.get('carbs') or 0)
    recipe.fat = float(request.form.get('fat') or 0)

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
    return redirect(url_for('recipe_edit_list_view'))

@app.route('/delete-recipe/<int:id>', methods=['POST'])
def delete_recipe(id):
    recipe = Recipe.query.get_or_404(id)
    db.session.delete(recipe)
    db.session.commit()
    return redirect(url_for('recipe_edit_list_view'))

@app.route('/add-category', methods=['POST'])
def add_category():
    name = request.form.get('category_name').strip()
    if name:
        existing = Category.query.filter_by(name=name).first()
        if not existing:
            new_cat = Category(name=name)
            db.session.add(new_cat)
            db.session.commit()
    return redirect(url_for('category_manage_view'))

@app.route('/delete-category/<int:id>', methods=['POST'])
def delete_category(id):
    category = Category.query.get_or_404(id)
    if len(category.recipes) > 0:
        return "Fehler: Diese Kategorie enthält noch Rezepte!", 400
    db.session.delete(category)
    db.session.commit()
    return redirect(url_for('category_manage_view'))

@app.route('/generate-plan', methods=['POST'])
def generate_plan():
    selected_ids = request.form.getlist('selected_recipes')
    selected_recipes = Recipe.query.filter(Recipe.id.in_(selected_ids)).all()
    
    final_plan = list(selected_recipes)
    used_categories = {r.category_id for r in final_plan}
    
    slots_needed = max(0, 7 - len(final_plan))
    
    if slots_needed > 0:
        all_categories = Category.query.all()
        missing_cat_ids = [c.id for c in all_categories if c.id not in used_categories]
        
        fill_recipes = Recipe.query.filter(Recipe.category_id.in_(missing_cat_ids)).all()
        
        if len(fill_recipes) < slots_needed:
            already_included_ids = [r.id for r in final_plan]
            fill_recipes += Recipe.query.filter(~Recipe.id.in_(already_included_ids)).all()
            
        random.shuffle(fill_recipes)
        for r in fill_recipes:
            if len(final_plan) >= 7:
                break
            if r not in final_plan:
                final_plan.append(r)
                
    shopping_list = {}
    for recipe in final_plan:
        for ing in recipe.ingredients:
            key = (ing.name.strip().title(), ing.unit.strip())
            shopping_list[key] = shopping_list.get(key, 0) + ing.amount
            
    return render_template('plan.html', plan=final_plan, shopping_list=shopping_list)

# Verhindert, dass der Browser das CSS im Cache speichert
@app.context_processor
def inject_css_version():
    import time
    return dict(css_version=int(time.time()))

if __name__ == '__main__':
    app.run(debug=True)

