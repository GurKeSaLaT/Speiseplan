import os
import random
from collections import Counter

from sqlalchemy import text
from flask import Flask, render_template, request, redirect, url_for
from models import db, Category, Recipe, Ingredient

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(app.instance_path, 'speiseplan.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

os.makedirs(app.instance_path, exist_ok=True)
db.init_app(app)


def init_db():
    db.create_all()

    # Migration: bestehende Datenbanken hatten noch keine is_side_dish-Spalte
    existing_columns = {row[1] for row in db.session.execute(text("PRAGMA table_info(recipe)"))}
    if 'is_side_dish' not in existing_columns:
        db.session.execute(text("ALTER TABLE recipe ADD COLUMN is_side_dish BOOLEAN NOT NULL DEFAULT 0"))
        db.session.commit()

    if not Category.query.first():
        default_categories = ["Fleisch", "Fisch", "Vegetarisch", "Vegan", "Nudeln/Pasta", "Suppe/Eintopf", "Schnelle Küche"]
        for cat_name in default_categories:
            db.session.add(Category(name=cat_name))
        db.session.commit()


with app.app_context():
    init_db()


@app.context_processor
def inject_css_version():
    # Cache-Bremse für style.css: Änderungsdatum der Datei als Query-Parameter,
    # damit Browser nach einem Update nicht die alte Version aus dem Cache laden
    css_path = os.path.join(app.static_folder, 'style.css')
    try:
        css_version = int(os.path.getmtime(css_path))
    except OSError:
        css_version = 0
    return {'css_version': css_version}


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
    is_side_dish = request.form.get('is_side_dish') == '1'

    new_recipe = Recipe(
        name=name, category_id=category_id,
        calories=calories, protein=protein, carbs=carbs, fat=fat,
        is_side_dish=is_side_dish
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
    recipe.is_side_dish = request.form.get('is_side_dish') == '1'

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


# --- PLANUNGS-LOGIK ---

def get_balanced_category_slots(all_categories, n=7, preexisting_counts=None):
    """Hilfsfunktion zur Berechnung einer möglichst gleichmäßigen Kategorie-Verteilung für n Tage.
    Bereits fest belegte Tage (preexisting_counts) fließen in die Balance mit ein,
    ohne dass sich die Länge des Ergebnisses (== n) dadurch ändert."""
    cat_ids = [c.id for c in all_categories]
    if not cat_ids or n <= 0:
        return []

    counts = Counter(preexisting_counts or {})
    for cid in cat_ids:
        counts.setdefault(cid, 0)

    slots = []
    while len(slots) < n:
        min_count = min(counts[cid] for cid in cat_ids)
        candidates = [cid for cid in cat_ids if counts[cid] == min_count]
        choice = random.choice(candidates)
        slots.append(choice)
        counts[choice] += 1

    random.shuffle(slots)
    return slots


@app.route('/generate-plan', methods=['POST'])
def generate_plan():
    all_categories = Category.query.all()

    # 1. Formulardaten pro Tag auslesen: feste Zuweisung + Ausnahme-Status
    excluded_days = set()
    day_recipe_ids = {}  # Tag-Index -> Hauptgericht-Rezept-ID (String)
    day_side_recipe_ids = {}  # Tag-Index -> Zusatzgericht-Rezept-ID (String)

    for i in range(7):
        if request.form.get(f'day_excluded_{i}') == '1':
            excluded_days.add(i)
            continue
        rid = (request.form.get(f'day_recipe_{i}') or '').strip()
        if rid:
            day_recipe_ids[i] = rid
        side_rid = (request.form.get(f'day_side_recipe_{i}') or '').strip()
        if side_rid:
            day_side_recipe_ids[i] = side_rid

    # 2. Feste Hauptgerichte anhand ihrer ID nachladen
    final_plan = [None] * 7
    used_recipe_ids = set()

    if day_recipe_ids:
        unique_ids = list(set(day_recipe_ids.values()))
        recipes_by_id = {str(r.id): r for r in Recipe.query.filter(Recipe.id.in_(unique_ids)).all()}
        for day_index, rid in day_recipe_ids.items():
            recipe = recipes_by_id.get(rid)
            if recipe:
                final_plan[day_index] = recipe
                used_recipe_ids.add(recipe.id)

    # 2b. Feste Zusatzgerichte (Beilagen) anhand ihrer ID nachladen.
    #     Beilagen werden NIE automatisch gewürfelt - nur was der Nutzer hier
    #     fest zugewiesen hat, landet im Plan (Nachträgliches Würfeln erfolgt
    #     erst auf der Plan-Seite über den 🎲-Button).
    final_side_plan = [None] * 7

    if day_side_recipe_ids:
        unique_side_ids = list(set(day_side_recipe_ids.values()))
        side_recipes_by_id = {
            str(r.id): r for r in Recipe.query.filter(Recipe.id.in_(unique_side_ids)).all()
        }
        for day_index, rid in day_side_recipe_ids.items():
            recipe = side_recipes_by_id.get(rid)
            if recipe:
                final_side_plan[day_index] = recipe

    # 3. Bestimme, welche Tage noch automatisch aufgefüllt werden müssen
    #    (weder ausgenommen, noch bereits fest belegt)
    days_to_fill = [i for i in range(7) if i not in excluded_days and final_plan[i] is None]

    # 4. Balancierte Kategorie-Slots für die verbleibenden Tage berechnen.
    #    Bereits fest zugewiesene Tage fließen als Vorbelastung in die Balance ein,
    #    damit die Anzahl der Slots exakt der Anzahl der aufzufüllenden Tage entspricht.
    preexisting_counts = Counter(
        final_plan[day_index].category_id
        for day_index in day_recipe_ids
        if final_plan[day_index] is not None
    )
    target_category_ids = get_balanced_category_slots(
        all_categories, n=len(days_to_fill), preexisting_counts=preexisting_counts
    )

    # 5. Restliche Tage nacheinander mit passenden, noch nicht verwendeten Hauptgerichten auffüllen
    #    (Zusatzgerichte/Beilagen sind hiervon ausgeschlossen)
    for day_index, needed_cat_id in zip(days_to_fill, target_category_ids):
        cat_recipes = Recipe.query.filter(
            Recipe.category_id == needed_cat_id,
            Recipe.is_side_dish.is_(False),
            ~Recipe.id.in_(used_recipe_ids)
        ).all()

        chosen = None
        if cat_recipes:
            chosen = random.choice(cat_recipes)
        else:
            fallback_recipes = Recipe.query.filter(
                Recipe.is_side_dish.is_(False),
                ~Recipe.id.in_(used_recipe_ids)
            ).all()
            if fallback_recipes:
                chosen = random.choice(fallback_recipes)

        if chosen:
            final_plan[day_index] = chosen
            used_recipe_ids.add(chosen.id)

    return render_template(
        'plan.html', plan=final_plan, side_plan=final_side_plan, excluded_days=excluded_days
    )


@app.route('/reroll-day', methods=['POST'])
def reroll_day():
    data = request.get_json() or {}
    # current_recipe_ids ist jetzt immer 7 Einträge lang; leere/ausgenommene Tage sind null
    current_ids_raw = data.get('current_recipe_ids', [])

    day_index_raw = data.get('day_index')
    day_index = int(day_index_raw) if day_index_raw is not None else 999

    # Nur echte, gültige IDs für die DB-Abfragen verwenden
    current_ids = [cid for cid in current_ids_raw if cid]

    other_recipes = Recipe.query.filter(Recipe.id.in_(current_ids)).all()

    all_categories = Category.query.all()
    all_cat_ids = [c.id for c in all_categories]

    other_cat_counts = {cid: 0 for cid in all_cat_ids}
    for r in other_recipes:
        other_cat_counts[r.category_id] = other_cat_counts.get(r.category_id, 0) + 1

    target_card_recipe_id = current_ids_raw[day_index] if day_index < len(current_ids_raw) else None
    if target_card_recipe_id:
        old_recipe = Recipe.query.get(target_card_recipe_id)
        if old_recipe and other_cat_counts.get(old_recipe.category_id, 0) > 0:
            other_cat_counts[old_recipe.category_id] -= 1

    sorted_target_categories = sorted(all_cat_ids, key=lambda cid: other_cat_counts[cid])

    for best_cat_id in sorted_target_categories:
        chosen_recipe = Recipe.query.filter(
            Recipe.category_id == best_cat_id,
            Recipe.is_side_dish.is_(False),
            ~Recipe.id.in_(current_ids)
        ).all()

        if chosen_recipe:
            return jsonify_recipe(random.choice(chosen_recipe))

    fallback_recipes = Recipe.query.filter(
        Recipe.is_side_dish.is_(False),
        ~Recipe.id.in_(current_ids)
    ).all()
    if fallback_recipes:
        return jsonify_recipe(random.choice(fallback_recipes))

    return {"error": "Keine weiteren Rezepte in der Datenbank verfügbar!"}, 400


@app.route('/reroll-side-day', methods=['POST'])
def reroll_side_day():
    data = request.get_json() or {}
    # current_side_recipe_ids ist immer 7 Einträge lang; Tage ohne Beilage sind null
    current_ids_raw = data.get('current_side_recipe_ids', [])
    current_ids = [cid for cid in current_ids_raw if cid]

    candidates = Recipe.query.filter(
        Recipe.is_side_dish.is_(True),
        ~Recipe.id.in_(current_ids)
    ).all()

    if candidates:
        return jsonify_recipe(random.choice(candidates))

    return {"error": "Keine weiteren Beilagen in der Datenbank verfügbar!"}, 400


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
