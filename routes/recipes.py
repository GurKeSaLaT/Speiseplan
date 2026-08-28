"""Rezept-Verwaltung: die Erstellen-/Bearbeiten-/Löschen-Seiten für einzelne
Gerichte (Recipe), inklusive ihrer Zutaten (Ingredient) und
Saison-Zuordnung (RecipeSeason, über services/seasons.py verwaltet).

Zwei GET-Ansichten (recipe_create_view, recipe_edit_list_view) rendern die
Formulare; drei POST-Handler (add_recipe, edit_recipe, delete_recipe)
verarbeiten deren Absenden. Die eigentliche Saison-Formular-Logik
(Checkboxen + eigener Zeitraum parsen, für die Bearbeiten-Ansicht
vorbefüllen) liegt bewusst NICHT hier, sondern in services/seasons.py -
diese Datei bleibt auf "Recipe/Ingredient anlegen, ändern, löschen"
fokussiert.
"""

from flask import Blueprint, render_template, request, redirect, url_for

from models import db, Category, Recipe, Ingredient
from services.seasons import (
    SEASONS, save_recipe_seasons, describe_recipe_seasons, format_recipe_seasons
)

recipes_bp = Blueprint('recipes', __name__)


@recipes_bp.route('/manage/recipe/create')
def recipe_create_view():
    """Zeigt das Formular zum Anlegen eines neuen Rezepts.

    Neben den Kategorien wird auch eine alphabetisch sortierte, über alle
    bestehenden Rezepte hinweg EINZIGARTIGE Liste bereits verwendeter
    Zutatennamen mitgeliefert (ingredient_list). Diese füllt im Formular
    ein <datalist>-Element (Autovervollständigung beim Tippen einer neuen
    Zutat), damit z.B. "Zwiebel" nicht in einem Rezept als "Zwiebeln" und
    im nächsten als "zwiebel" landet.
    """
    categories = Category.query.all()
    # distinct() dedupliziert auf DB-Ebene; das "if ing[0]" filtert defensiv
    # rein leere Strings heraus, falls je ein Formular mit leerem
    # Zutatennamen abgeschickt wurde.
    existing_ingredients = db.session.query(Ingredient.name).distinct().order_by(Ingredient.name).all()
    ingredient_list = [ing[0] for ing in existing_ingredients if ing[0]]

    return render_template('recipe_create.html', categories=categories, ingredient_list=ingredient_list, seasons=SEASONS)


@recipes_bp.route('/manage/recipe/edit-list')
def recipe_edit_list_view():
    """Zeigt die Liste aller Rezepte mit einem Bearbeiten-Modal pro Rezept
    (siehe templates/recipe_edit_list.html - ein <div class="modal"> je
    Rezept, per Bootstrap-Button geöffnet).

    Da jedes Modal sein eigenes vorbefülltes Saison-Formular braucht (welche
    Standard-Saison-Checkboxen sind angehakt, welcher eigene Zeitraum steht
    in den Datumsfeldern), wird das für JEDES Rezept einzeln über
    describe_recipe_seasons() aufbereitet und in recipe_season_info
    (ein Dict, Rezept-ID -> aufbereitete Daten) an das Template gereicht.
    Die 'custom_start'/'custom_end'-Werte bekommen dabei ein beliebiges
    (Schaltjahr-taugliches) Platzhalterjahr vorangestellt, weil
    <input type="date"> zwingend ein vollständiges Datum erwartet, obwohl
    beim Speichern ohnehin nur Monat und Tag ausgewertet werden (siehe
    services/seasons.py: parse_recipe_seasons).
    """
    recipes = Recipe.query.all()
    categories = Category.query.all()
    existing_ingredients = db.session.query(Ingredient.name).distinct().order_by(Ingredient.name).all()
    ingredient_list = [ing[0] for ing in existing_ingredients if ing[0]]

    recipe_season_info = {}
    for recipe in recipes:
        selected_presets, custom_range = describe_recipe_seasons(recipe)
        recipe_season_info[recipe.id] = {
            'selected_presets': selected_presets,
            'custom_start': f"2000-{custom_range.start_month:02d}-{custom_range.start_day:02d}" if custom_range else '',
            'custom_end': f"2000-{custom_range.end_month:02d}-{custom_range.end_day:02d}" if custom_range else '',
            # Fertig formatierte Badge-Labels (z.B. "Sommer", "15.5.–20.6."),
            # damit das Template selbst keine Formatierungslogik braucht.
            'labels': format_recipe_seasons(recipe),
        }

    return render_template(
        'recipe_edit_list.html', recipes=recipes, categories=categories,
        ingredient_list=ingredient_list, seasons=SEASONS, recipe_season_info=recipe_season_info
    )


@recipes_bp.route('/add-recipe', methods=['POST'])
def add_recipe():
    """Legt ein neues Rezept samt seiner Zutaten und Saison-Zuordnung an.

    Ablauf: zuerst wird das Recipe-Objekt angelegt und per db.session.flush()
    (statt commit()) in die Datenbank geschrieben - flush() weist bereits
    eine ID zu, OHNE die Transaktion abzuschließen, damit diese ID direkt
    für die abhängigen RecipeSeason- und Ingredient-Zeilen verwendet werden
    kann. Erst der abschließende commit() macht alles zusammen dauerhaft
    (bei einem Fehler dazwischen würde alles zurückgerollt).

    Die Zutaten kommen als vier parallele Listen aus dem Formular
    (ing_name[], ing_amount[], ing_unit[], ing_category[] - ein
    HTML-Formular mit dynamisch per JavaScript hinzugefügten Zeilen, siehe
    recipe_create.html), werden über den gemeinsamen Index paarweise
    zusammengeführt und Zeilen mit leerem Namen übersprungen (z.B. eine
    ungenutzte letzte leere Zeile im Formular). ing_category[] ist dabei
    der einzige der vier optional: ein leerer String wird zu None (siehe
    services/shopping.py: UNCATEGORIZED - None landet in der Einkaufsliste
    in der Sonstiges-Sammelgruppe, ganz ohne extra Sonderfall hier).
    """
    name = request.form.get('name')
    category_id = request.form.get('category_id')
    calories = int(request.form.get('calories') or 0)
    protein = float(request.form.get('protein') or 0)
    carbs = float(request.form.get('carbs') or 0)
    fat = float(request.form.get('fat') or 0)
    is_side_dish = request.form.get('is_side_dish') == '1'
    is_favorite = request.form.get('is_favorite') == '1'
    # Mindestens 1 Person, auch falls das Formularfeld leer/fehlerhaft ist.
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
    ing_categories = request.form.getlist('ing_category[]')

    for i in range(len(ing_names)):
        if ing_names[i].strip():
            amount = float(ing_amounts[i] or 0)
            category = ing_categories[i].strip() or None if i < len(ing_categories) else None
            ingredient = Ingredient(
                recipe_id=new_recipe.id, name=ing_names[i], amount=amount, unit=ing_units[i], category=category
            )
            db.session.add(ingredient)

    db.session.commit()
    # Zurück zur "Erstellen"-Unterseite (nicht zur Liste), damit direkt das
    # nächste Rezept eingetragen werden kann, ohne erst zu navigieren.
    return redirect(url_for('recipes.recipe_create_view'))


@recipes_bp.route('/edit-recipe/<int:id>', methods=['POST'])
def edit_recipe(id):
    """Überschreibt ein bestehendes Rezept vollständig mit den Formulardaten.

    Die Zutaten werden dabei nicht einzeln abgeglichen (kein Diff aus
    "geändert/neu/gelöscht"), sondern komplett gelöscht und aus dem
    Formularinhalt neu angelegt - deutlich einfacher als ein Merge, und da
    das Formular ohnehin immer ALLE aktuellen Zutaten mitschickt (auch
    unveränderte), verliert dieser Ansatz keine Daten. Ebenso verfährt
    save_recipe_seasons() mit den Saison-Zeiträumen.
    """
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
    ing_categories = request.form.getlist('ing_category[]')

    for i in range(len(ing_names)):
        if ing_names[i].strip():
            amount = float(ing_amounts[i] or 0)
            category = ing_categories[i].strip() or None if i < len(ing_categories) else None
            ingredient = Ingredient(
                recipe_id=recipe.id, name=ing_names[i], amount=amount, unit=ing_units[i], category=category
            )
            db.session.add(ingredient)

    db.session.commit()
    # Zurück zur Bearbeitungsliste (im Gegensatz zu add_recipe, das zurück
    # zur Erstellen-Seite leitet) - hier gibt es kein "nächstes" Rezept,
    # zu dem man direkt weiterspringen würde.
    return redirect(url_for('recipes.recipe_edit_list_view'))


@recipes_bp.route('/delete-recipe/<int:id>', methods=['POST'])
def delete_recipe(id):
    """Löscht ein Rezept unwiderruflich. Zugehörige Ingredient- und
    RecipeSeason-Zeilen werden durch die cascade="all, delete-orphan"-
    Konfiguration in models.py automatisch mitgelöscht.

    Bewusst KEINE Prüfung, ob das Rezept noch in einem PlanDay (dem
    Wochenplan-Kalender) referenziert wird: main_recipe_id/side_recipe_id
    in PlanDay sind nullable und ohne ON DELETE-Constraint, ein gelöschtes
    Rezept hinterlässt dort einfach eine "hängende" ID. Das ist ein
    bekanntes, in Kauf genommenes Verhalten (siehe IDEAS.md) - für die
    kleine, persönliche Nutzung dieser App bislang nicht relevant genug,
    um dafür extra eine Lösch-Sperre oder Kaskade einzubauen.
    """
    recipe = Recipe.query.get_or_404(id)
    db.session.delete(recipe)
    db.session.commit()
    return redirect(url_for('recipes.recipe_edit_list_view'))
