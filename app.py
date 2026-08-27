import os
import random
from flask import Flask, render_template, request, redirect, url_for, jsonify
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
    # Holt alle einzigartigen Zutatennamen, alphabetisch sortiert
    existing_ingredients = db.session.query(Ingredient.name).distinct().order_by(Ingredient.name).all()
    ingredient_list = [ing[0] for ing in existing_ingredients if ing[0]]

    return render_template('recipe_create.html', categories=categories, ingredient_list=ingredient_list)

@app.route('/manage/recipe/edit-list')
def recipe_edit_list_view():
    recipes = Recipe.query.all()
    categories = Category.query.all()
    # Holt alle einzigartigen Zutatennamen, alphabetisch sortiert
    existing_ingredients = db.session.query(Ingredient.name).distinct().order_by(Ingredient.name).all()
    ingredient_list = [ing[0] for ing in existing_ingredients if ing[0]]

    return render_template('recipe_edit_list.html', recipes=recipes, categories=categories, ingredient_list=ingredient_list)

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

# --- DIESE FUNKTIONEN IN DER APP.PY ERSETZEN ---

def get_balanced_category_slots(all_categories):
    """Hilfsfunktion zur Berechnung der perfekten Kategorie-Verteilung für 7 Tage"""
    cat_ids = [c.id for c in all_categories]
    if not cat_ids:
        return []

    import random
    # Regel 1: Wenn es 7 oder mehr Kategorien gibt, wähle 7 eindeutige aus
    if len(cat_ids) >= 7:
        return random.sample(cat_ids, 7)

    # Regel 2: Wenn es weniger als 7 sind, muss jede vertreten sein und gleich oft vorkommen
    slots = list(cat_ids) # Jede ist 1x vertreten
    while len(slots) < 7:
        # Füge die Kategorien hinzu, die im Slot-Pool aktuell am seltensten sind
        from collections import Counter
        counts = Counter(slots)
        min_count = min(counts.values())
        candidates = [cid for cid in cat_ids if counts[cid] == min_count]
        slots.append(random.choice(candidates))

    random.shuffle(slots)
    return slots

@app.route('/generate-plan', methods=['POST'])
def generate_plan():
    selected_ids = request.form.getlist('selected_recipes')
    selected_recipes = Recipe.query.filter(Recipe.id.in_(selected_ids)).all()

    all_categories = Category.query.all()

    # Berechne den idealen Kategorie-Fahrplan für eine Woche (7 Tage)
    target_category_ids = get_balanced_category_slots(all_categories)

    final_plan = []

    # 1. Platziere zuerst die vom Nutzer fest ausgewählten Gerichte
    for recipe in selected_recipes:
        if len(final_plan) >= 7:
            break
        final_plan.append(recipe)
        # Entferne die Kategorie dieses Rezepts aus unseren Ziel-Slots, um die Balance zu halten
        if recipe.category_id in target_category_ids:
            target_category_ids.remove(recipe.category_id)
        elif target_category_ids:
            target_category_ids.pop(0) # Fallback, falls der Nutzer exotische Kombinationen wählt

    # 2. Fülle die restlichen Tage strikt nach den balancierten Kategorie-Slots auf
    import random
    for needed_cat_id in target_category_ids:
        if len(final_plan) >= 7:
            break

        # Rezepte aus dieser Kategorie suchen, die noch nicht im Plan sind
        already_included_ids = [r.id for r in final_plan]
        cat_recipes = Recipe.query.filter(
            Recipe.category_id == needed_cat_id,
            ~Recipe.id.in_(already_included_ids)
        ).all()

        if cat_recipes:
            final_plan.append(random.choice(cat_recipes))
        else:
            # Fallback: Wenn die Wunschkategorie leer ist, nimm irgendein anderes freies Rezept
            fallback_recipes = Recipe.query.filter(~Recipe.id.in_(already_included_ids)).all()
            if fallback_recipes:
                final_plan.append(random.choice(fallback_recipes))

    # Sortierung sichern (falls weniger als 7 Rezepte in der DB existieren)
    shopping_list = {}
    for recipe in final_plan:
        for ing in recipe.ingredients:
            key = (ing.name.strip().title(), ing.unit.strip())
            shopping_list[key] = shopping_list.get(key, 0) + ing.amount

    return render_template('plan.html', plan=final_plan, shopping_list=shopping_list)


@app.route('/reroll-day', methods=['POST'])
def reroll_day():
    data = request.get_json() or {}
    current_ids = data.get('current_recipe_ids', [])

    # KORRIGIERT: Wir erzwingen einen Integer-Typ oder setzen einen sicheren Fallback
    day_index_raw = data.get('day_index')
    day_index = int(day_index_raw) if day_index_raw is not None else 999

    # 1. Analysiere die Kategorien der ANDEREN 6 Tage im aktuellen Plan
    other_recipes = Recipe.query.filter(Recipe.id.in_(current_ids)).all()

    from collections import Counter
    all_categories = Category.query.all()
    all_cat_ids = [c.id for c in all_categories]

    other_cat_counts = {cid: 0 for cid in all_cat_ids}
    for r in other_recipes:
        other_cat_counts[r.category_id] = other_cat_counts.get(r.category_id, 0) + 1

    # KORRIGIERT: Die Abfrage ist jetzt absolut sicher vor NoneType-Fehlern
    target_card_recipe_id = current_ids[day_index] if day_index < len(current_ids) else None
    if target_card_recipe_id:
        old_recipe = Recipe.query.get(target_card_recipe_id)
        if old_recipe and other_cat_counts[old_recipe.category_id] > 0:
            other_cat_counts[old_recipe.category_id] -= 1

    
    # 2. Sortiere die Kategorien danach, welche im restlichen Plan am SELTENSTEN vorkommt
    sorted_target_categories = sorted(all_cat_ids, key=lambda cid: other_cat_counts[cid])

    import random
    # 3. Gehe die seltensten Kategorien nacheinander durch und suche ein freies Rezept
    for best_cat_id in sorted_target_categories:
        chosen_recipe = Recipe.query.filter(
            Recipe.category_id == best_cat_id,
            ~Recipe.id.in_(current_ids) # Darf an keinem anderen Tag vorkommen
        ).all()

        if chosen_recipe:
            return jsonify_recipe(random.choice(chosen_recipe))

    # Absoluter Notfall-Fallback: Nimm einfach irgendein freies Rezept, egal welche Kategorie
    fallback_recipes = Recipe.query.filter(~Recipe.id.in_(current_ids)).all()
    if fallback_recipes:
        return jsonify_recipe(random.choice(fallback_recipes))

    return {"error": "Keine weiteren Rezepte in der Datenbank verfügbar!"}, 400

def jsonify_recipe(recipe):
    # Hilfsfunktion, um Rezeptdaten lesbar für JavaScript bereitzustellen
    return {
        "id": recipe.id,
        "name": recipe.name,
        "category_name": recipe.category.name,
        "category_id": recipe.category_id,
        "calories": recipe.calories,
        "protein": recipe.protein,
        "carbs": recipe.carbs,
        "fat": recipe.fat,
        "ingredients": [{"name": ing.name.strip().title(), "amount": ing.amount, "unit": ing.unit} for ing in recipe.ingredients]
    }
if __name__ == '__main__':
    app.run(debug=True)

