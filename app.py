import os
import random
from flask import Flask, render_template, request, redirect, url_for
from models import db, Category, Recipe, Ingredient

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(app.instance_path, 'speiseplan.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Sicherstellen, dass der Instanz-Ordner für SQLite existiert
os.makedirs(app.instance_path, exist_ok=True)
db.init_app(app)

# Standard-Kategorien beim ersten Start anlegen
def init_db():
    db.create_all()
    if not Category.query.first():
        default_categories = ["Fleisch", "Fisch", "Vegetarisch", "Vegan", "Nudeln/Pasta", "Suppe/Eintopf", "Schnelle Küche"]
        for cat_name in default_categories:
            db.session.add(Category(name=cat_name))
        db.session.commit()

with app.app_context():
    init_db()

@app.route('/')
def index():
    recipes = Recipe.query.all()
    categories = Category.query.all()
    return render_template('index.html', recipes=recipes, categories=categories)

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
    db.session.flush() # Holt die ID für das Rezept vor dem finalen Commit
    
    # Zutaten aus dem Formular auslesen (bis zu 10 dynamische Felder)
    ing_names = request.form.getlist('ing_name[]')
    ing_amounts = request.form.getlist('ing_amount[]')
    ing_units = request.form.getlist('ing_unit[]')
    
    for i in range(len(ing_names)):
        if ing_names[i].strip():
            amount = float(ing_amounts[i] or 0)
            ingredient = Ingredient(recipe_id=new_recipe.id, name=ing_names[i], amount=amount, unit=ing_units[i])
            db.session.add(ingredient)
            
    db.session.commit()
    return redirect(url_for('index'))

@app.route('/generate-plan', methods=['POST'])
def generate_plan():
    selected_ids = request.form.getlist('selected_recipes')
    selected_recipes = Recipe.query.filter(Recipe.id.in_(selected_ids)).all()
    
    final_plan = list(selected_recipes)
    used_categories = {r.category_id for r in final_plan}
    
    # Restliche Tage bis zur vollen Woche (7 Tage) auffüllen
    slots_needed = max(0, 7 - len(final_plan))
    
    if slots_needed > 0:
        all_categories = Category.query.all()
        # Priorisiere Kategorien, die noch gar nicht im Plan sind
        missing_cat_ids = [c.id for c in all_categories if c.id not in used_categories]
        
        fill_recipes = Recipe.query.filter(Recipe.category_id.in_(missing_cat_ids)).all()
        
        # Falls nicht genug Rezepte in fehlenden Kategorien, nimm alle anderen verfügbaren
        if len(fill_recipes) < slots_needed:
            already_included_ids = [r.id for r in final_plan]
            fill_recipes += Recipe.query.filter(~Recipe.id.in_(already_included_ids)).all()
            
        random.shuffle(fill_recipes)
        # Verhindere Duplikate, falls die Auswahl knapp ist
        for r in fill_recipes:
            if len(final_plan) >= 7:
                break
            if r not in final_plan:
                final_plan.append(r)
                
    # Konsolidierte Einkaufsliste berechnen
    shopping_list = {}
    for recipe in final_plan:
        for ing in recipe.ingredients:
            # Key kombiniert Name und Einheit (z.B. ("nudeln", "g")) um Schreibfehler abzufangen
            key = (ing.name.strip().title(), ing.unit.strip())
            shopping_list[key] = shopping_list.get(key, 0) + ing.amount
            
    return render_template('plan.html', plan=final_plan, shopping_list=shopping_list)
@app.route('/add-category', methods=['POST'])
def add_category():
    name = request.form.get('category_name').strip()
    if name:
        # Prüfen, ob Kategorie schon existiert
        existing = Category.query.filter_by(name=name).first()
        if not existing:
            new_cat = Category(name=name)
            db.session.add(new_cat)
            db.session.commit()
    return redirect(url_for('index'))

@app.route('/delete-category/<int:id>', methods=['POST'])
def delete_category(id):
    category = Category.query.get_or_404(id)
    # Wichtig: Rezepte, die dieser Kategorie angehören, könnten fehlschlagen.
    # Wir prüfen kurz, ob noch Rezepte diese Kategorie nutzen:
    if len(category.recipes) > 0:
        # Optional: Hier könnte man eine Fehlermeldung zeigen. 
        # Für den Anfang löschen wir die Kategorie nur, wenn sie leer ist.
        return "Fehler: Diese Kategorie enthält noch Rezepte und kann nicht gelöscht werden!", 400
        
    db.session.delete(category)
    db.session.commit()
    return redirect(url_for('index'))
@app.route('/delete-recipe/<int:id>', methods=['POST'])
def delete_recipe(id):
    recipe = Recipe.query.get_or_404(id)
    db.session.delete(recipe)
    db.session.commit()
    return redirect(url_for('index'))

@app.route('/edit-recipe/<int:id>', methods=['POST'])
def edit_recipe(id):
    recipe = Recipe.query.get_or_404(id)
    
    # Basisdaten aktualisieren
    recipe.name = request.form.get('name')
    recipe.category_id = request.form.get('category_id')
    recipe.calories = int(request.form.get('calories') or 0)
    recipe.protein = float(request.form.get('protein') or 0)
    recipe.carbs = float(request.form.get('carbs') or 0)
    recipe.fat = float(request.form.get('fat') or 0)
    
    # Alte Zutaten löschen und neue eintragen (einfachster Weg für Updates)
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
    return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(debug=True)

