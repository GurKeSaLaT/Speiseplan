import os
import random
from collections import Counter
from datetime import date

from sqlalchemy import text
from flask import Flask, render_template, request, redirect, url_for
from models import db, Category, Recipe, Ingredient, RecipeSeason

SEASONS = ['Frühling', 'Sommer', 'Herbst', 'Winter']
# Jahresunabhängige (Monat, Tag)-Zeiträume je Standard-Saison
SEASON_PRESETS = {
    'Frühling': (3, 1, 5, 31),
    'Sommer': (6, 1, 8, 31),
    'Herbst': (9, 1, 11, 30),
    'Winter': (12, 1, 2, 28),
}
SEASON_PRESET_BY_RANGE = {v: k for k, v in SEASON_PRESETS.items()}


def _season_range(rs):
    return (rs.start_month, rs.start_day, rs.end_month, rs.end_day)


def date_in_range(month, day, start_month, start_day, end_month, end_day):
    """Prüft, ob (month, day) in einem jahresunabhängigen Monat/Tag-Zeitraum liegt.
    Unterstützt über den Jahreswechsel laufende Zeiträume (z.B. Winter: Dez-Feb)."""
    current = (month, day)
    start = (start_month, start_day)
    end = (end_month, end_day)
    if start <= end:
        return start <= current <= end
    return current >= start or current <= end


def recipe_available_now(recipe):
    """Ganzjährig verfügbar, wenn das Rezept keine Zeiträume hinterlegt hat -
    sonst verfügbar, sobald heute in mindestens einen davon fällt."""
    if not recipe.seasons:
        return True
    today = date.today()
    return any(date_in_range(today.month, today.day, *_season_range(rs)) for rs in recipe.seasons)


def parse_recipe_seasons(form):
    """Liest die Saison-Auswahl aus dem Formular: mehrere angehakte Standard-
    Saisons und/oder ein eigener Zeitraum. Gibt eine Liste von
    (start_month, start_day, end_month, end_day)-Tupeln zurück."""
    ranges = []
    for season_name in form.getlist('seasons'):
        preset = SEASON_PRESETS.get(season_name)
        if preset:
            ranges.append(preset)

    custom_start = form.get('season_custom_start')
    custom_end = form.get('season_custom_end')
    if custom_start and custom_end:
        try:
            start_month, start_day = (int(p) for p in custom_start.split('-')[1:])
            end_month, end_day = (int(p) for p in custom_end.split('-')[1:])
            ranges.append((start_month, start_day, end_month, end_day))
        except (ValueError, IndexError):
            pass

    return ranges


def save_recipe_seasons(recipe_id, form):
    RecipeSeason.query.filter_by(recipe_id=recipe_id).delete()
    for start_month, start_day, end_month, end_day in parse_recipe_seasons(form):
        db.session.add(RecipeSeason(
            recipe_id=recipe_id,
            start_month=start_month, start_day=start_day,
            end_month=end_month, end_day=end_day
        ))


def describe_recipe_seasons(recipe):
    """Für die Bearbeiten-Ansicht: welche Standard-Saison-Checkboxen sollen
    angehakt sein, und gibt es einen (ersten) eigenen Zeitraum zum Vorbefüllen?"""
    selected_presets = set()
    custom_range = None
    for rs in recipe.seasons:
        preset_name = SEASON_PRESET_BY_RANGE.get(_season_range(rs))
        if preset_name:
            selected_presets.add(preset_name)
        elif custom_range is None:
            custom_range = rs
    return selected_presets, custom_range


def format_recipe_seasons(recipe):
    """Kurze, menschenlesbare Labels aller Zeiträume eines Rezepts, für die Badge-Anzeige."""
    labels = []
    for rs in recipe.seasons:
        preset_name = SEASON_PRESET_BY_RANGE.get(_season_range(rs))
        if preset_name:
            labels.append(preset_name)
        else:
            labels.append(f"{rs.start_day}.{rs.start_month}.–{rs.end_day}.{rs.end_month}.")
    return labels


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
    if 'servings' not in existing_columns:
        db.session.execute(text("ALTER TABLE recipe ADD COLUMN servings INTEGER NOT NULL DEFAULT 2"))
        db.session.commit()

    # Migration: die frühere einzelne season-Spalte gibt es nicht mehr (ersetzt durch
    # die recipe_season-Tabelle, die mehrere Zeiträume pro Rezept erlaubt). Bestehende
    # Werte einmalig in die neue Tabelle übernehmen, dann die alte Spalte entfernen.
    if 'season' in existing_columns:
        old_seasons = db.session.execute(text("SELECT id, season FROM recipe WHERE season IS NOT NULL")).fetchall()
        for recipe_id, season_name in old_seasons:
            preset = SEASON_PRESETS.get(season_name)
            if preset:
                db.session.add(RecipeSeason(
                    recipe_id=recipe_id,
                    start_month=preset[0], start_day=preset[1],
                    end_month=preset[2], end_day=preset[3]
                ))
        db.session.commit()
        db.session.execute(text("ALTER TABLE recipe DROP COLUMN season"))
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

    return render_template('recipe_create.html', categories=categories, ingredient_list=ingredient_list, seasons=SEASONS)


@app.route('/manage/recipe/edit-list')
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
    servings = max(1, int(request.form.get('servings') or 2))

    new_recipe = Recipe(
        name=name, category_id=category_id,
        calories=calories, protein=protein, carbs=carbs, fat=fat,
        is_side_dish=is_side_dish, servings=servings
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

def assign_balanced_categories(all_categories, days_to_fill, final_plan, preexisting_counts=None):
    """Weist jedem aufzufüllenden Tag (days_to_fill, Tag-Indizes 0-6) eine Kategorie zu:
    möglichst gleichmäßig über die Woche balanciert, aber nach Möglichkeit nie dieselbe
    Kategorie wie der direkte Vorgänger- oder Nachfolgetag (bereits fest belegte Tage
    zählen dabei als bekannter Nachbar). Ist das nicht vermeidbar (z.B. nur eine
    Kategorie insgesamt vorhanden), wird die Nachbarschaftsregel zugunsten der Balance
    aufgeweicht statt einen Tag unbefüllt zu lassen."""
    cat_ids = [c.id for c in all_categories]
    if not cat_ids:
        return {}

    counts = Counter(preexisting_counts or {})
    for cid in cat_ids:
        counts.setdefault(cid, 0)

    known_category_by_day = {
        i: final_plan[i].category_id for i in range(7) if final_plan[i] is not None
    }

    assigned = {}
    for day_index in days_to_fill:
        neighbor_cats = {
            known_category_by_day[n] for n in (day_index - 1, day_index + 1)
            if 0 <= n <= 6 and n in known_category_by_day
        }

        def sort_key(cid):
            return (cid in neighbor_cats, counts[cid])

        best_key = min(sort_key(cid) for cid in cat_ids)
        candidates = [cid for cid in cat_ids if sort_key(cid) == best_key]
        choice = random.choice(candidates)

        assigned[day_index] = choice
        counts[choice] += 1
        known_category_by_day[day_index] = choice

    return assigned


def choose_recipe(is_side_dish, exclude_ids, category_id=None, prefer_season=True):
    """Wählt zufällig ein passendes, noch nicht verwendetes Rezept aus. Bevorzugt
    (falls prefer_season) gerade jahreszeitlich verfügbare Rezepte (siehe
    recipe_available_now), weicht aber auf alle aus, wenn dafür keine Kandidaten
    existieren - eine Saison-Zuordnung schränkt die automatische Auswahl also nie
    komplett ein."""
    base_query = Recipe.query.filter(
        Recipe.is_side_dish.is_(is_side_dish),
        ~Recipe.id.in_(exclude_ids)
    )
    if category_id is not None:
        base_query = base_query.filter(Recipe.category_id == category_id)

    candidates = base_query.all()
    if not candidates:
        return None

    if prefer_season:
        seasonal_candidates = [r for r in candidates if recipe_available_now(r)]
        if seasonal_candidates:
            return random.choice(seasonal_candidates)

    return random.choice(candidates)


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
        else:
            rid = (request.form.get(f'day_recipe_{i}') or '').strip()
            if rid:
                day_recipe_ids[i] = rid

        # Beilagen werden unabhängig vom Ausnahme-Status eines Tages gelesen:
        # auch ein von der Hauptgericht-Planung ausgenommener Tag darf eine
        # fest zugewiesene Beilage haben.
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

    # 4. Kategorie je aufzufüllendem Tag bestimmen: möglichst gleichmäßig über die
    #    Woche balanciert und nach Möglichkeit nicht dieselbe Kategorie wie der
    #    direkte Vorgänger-/Nachfolgetag. Bereits fest zugewiesene Tage fließen als
    #    Vorbelastung in die Balance und als bekannte Nachbarn mit ein.
    preexisting_counts = Counter(
        final_plan[day_index].category_id
        for day_index in day_recipe_ids
        if final_plan[day_index] is not None
    )
    category_by_day = assign_balanced_categories(
        all_categories, days_to_fill, final_plan, preexisting_counts=preexisting_counts
    )

    # 5. Restliche Tage mit passenden, noch nicht verwendeten Hauptgerichten auffüllen
    #    (Zusatzgerichte/Beilagen sind hiervon ausgeschlossen). Bevorzugt Rezepte der
    #    aktuellen Saison, weicht aber auf jede Kategorie/Saison aus statt einen Tag
    #    leer zu lassen.
    for day_index, needed_cat_id in category_by_day.items():
        chosen = choose_recipe(is_side_dish=False, exclude_ids=used_recipe_ids, category_id=needed_cat_id)
        if not chosen:
            chosen = choose_recipe(is_side_dish=False, exclude_ids=used_recipe_ids)

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

    # Kategorien der direkten Nachbartage meiden (nach Möglichkeit - siehe unten),
    # damit ein Reroll nicht zwei aufeinanderfolgende Tage in dieselbe Kategorie legt.
    neighbor_ids = [
        current_ids_raw[n] for n in (day_index - 1, day_index + 1)
        if 0 <= n < len(current_ids_raw) and current_ids_raw[n]
    ]
    neighbor_categories = {r.category_id for r in Recipe.query.filter(Recipe.id.in_(neighbor_ids)).all()}

    sorted_target_categories = sorted(
        all_cat_ids, key=lambda cid: (cid in neighbor_categories, other_cat_counts[cid])
    )

    for best_cat_id in sorted_target_categories:
        chosen = choose_recipe(is_side_dish=False, exclude_ids=current_ids, category_id=best_cat_id)
        if chosen:
            return jsonify_recipe(chosen)

    chosen = choose_recipe(is_side_dish=False, exclude_ids=current_ids)
    if chosen:
        return jsonify_recipe(chosen)

    return {"error": "Keine weiteren Rezepte in der Datenbank verfügbar!"}, 400


@app.route('/reroll-side-day', methods=['POST'])
def reroll_side_day():
    data = request.get_json() or {}
    # current_side_recipe_ids ist immer 7 Einträge lang; Tage ohne Beilage sind null
    current_ids_raw = data.get('current_side_recipe_ids', [])
    current_ids = [cid for cid in current_ids_raw if cid]

    chosen = choose_recipe(is_side_dish=True, exclude_ids=current_ids)
    if chosen:
        return jsonify_recipe(chosen)

    return {"error": "Keine weiteren Beilagen in der Datenbank verfügbar!"}, 400


def jsonify_recipe(recipe):
    # Hilfsfunktion, um Rezeptdaten lesbar für JavaScript bereitzustellen
    return {
        "id": recipe.id,
        "name": recipe.name,
        "category_name": recipe.category.name,
        "category_id": recipe.category_id,
        "servings": recipe.servings,
        "calories": recipe.calories,
        "protein": recipe.protein,
        "carbs": recipe.carbs,
        "fat": recipe.fat,
        "ingredients": [{"name": ing.name.strip().title(), "amount": ing.amount, "unit": ing.unit} for ing in recipe.ingredients]
    }


if __name__ == '__main__':
    # FLASK_DEBUG=0 und PORT=80 im Docker-Deployment gesetzt (siehe Dockerfile) -
    # lokal ohne gesetzte Variablen bleiben Debug-/Autoreload-Modus und Port 5000
    # (kein Root fuer privilegierte Ports noetig) wie gewohnt.
    # Im Container: 0.0.0.0-Bindung noetig, sonst ist die App von aussen nicht erreichbar.
    debug_mode = os.environ.get('FLASK_DEBUG', '1') == '1'
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=debug_mode)
