"""Rezept-Verwaltung: die Erstellen-/Bearbeiten-/Löschen-Seiten für einzelne
Gerichte (Recipe), inklusive ihrer Zutaten (Ingredient), Saison-Zuordnung
(RecipeSeason, über services/seasons.py verwaltet) und dem Import von
chefkoch.de (über services/recipe_import.py).

Zwei GET-Ansichten (recipe_create_view, recipe_edit_list_view) rendern die
Formulare; drei POST-Handler (add_recipe, edit_recipe, delete_recipe)
verarbeiten deren Absenden. import_recipe_preview() ist ein vierter,
JSON-basierter POST-Handler für den AJAX-Import-Button auf der
Erstellen-Seite - er speichert NICHTS, sondern liefert nur die aus einer
chefkoch.de-URL ausgelesenen Rezeptdaten zurück, mit denen
recipe_create.html das normale Formular vorbefüllt (siehe
services/recipe_import.py für den Grund: die Kategorie muss der Nutzer
ohnehin selbst wählen, ein direktes Speichern ohne Review wäre riskanter).

Die eigentliche Saison-Formular-Logik (Checkboxen + eigener Zeitraum
parsen, für die Bearbeiten-Ansicht vorbefüllen) liegt bewusst NICHT hier,
sondern in services/seasons.py - diese Datei bleibt auf "Recipe/Ingredient
anlegen, ändern, löschen" fokussiert.
"""

from flask import Blueprint, render_template, request, redirect, url_for

from models import db, Category, Recipe, Ingredient
from services.seasons import (
    SEASONS, save_recipe_seasons, describe_recipe_seasons, format_recipe_seasons
)
from services.nutrition import compute_recipe_nutrition
from services.recipe_import import fetch_recipe_from_url, RecipeImportError
from services.settings import get_display_units
from services.units import convert_for_display, normalize_amount_unit

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
    # Zutatenmengen werden kanonisch (immer g/ml) gespeichert, aber in der
    # vom Nutzer gewählten Einheit (siehe services/settings.py) im
    # Bearbeiten-Formular vorbefüllt - Ingredient-ID -> (amount, unit) für
    # die Formularfelder in recipe_edit_list.html. Ein Speichern OHNE
    # Änderung liefert über normalize_amount_unit() wieder exakt denselben
    # kanonischen Wert (siehe services/units.py-Docstring), das Umrechnen
    # hier ist also verlustfrei umkehrbar.
    display_units = get_display_units()
    ingredient_display = {}
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
        for ing in recipe.ingredients:
            ingredient_display[ing.id] = convert_for_display(ing.amount, ing.unit, display_units)

    return render_template(
        'recipe_edit_list.html', recipes=recipes, categories=categories,
        ingredient_list=ingredient_list, seasons=SEASONS, recipe_season_info=recipe_season_info,
        ingredient_display=ingredient_display,
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

    Nährwerte: werden standardmäßig aus den Zutaten berechnet (siehe
    services/nutrition.py: compute_recipe_nutrition()) statt die
    Formularfelder ungeprüft zu übernehmen - nur bei gesetztem
    nutrition_override-Häkchen (im Formular per JS deaktivierte, aber
    weiterhin abgesendete Felder) gelten die eingetragenen Werte direkt.
    Die Zutatenzeilen werden dafür VOR dem Anlegen des Recipe-Objekts
    normalisiert (Menge/Einheit), damit sowohl die Berechnung als auch
    die späteren Ingredient-Zeilen dieselben, bereits kanonischen Werte
    verwenden.
    """
    name = request.form.get('name')
    category_id = request.form.get('category_id')
    is_side_dish = request.form.get('is_side_dish') == '1'
    is_favorite = request.form.get('is_favorite') == '1'
    nutrition_override = request.form.get('nutrition_override') == '1'
    # Mindestens 1 Person, auch falls das Formularfeld leer/fehlerhaft ist.
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
            # Menge+Einheit auf die kanonische Form bringen (immer g/ml
            # innerhalb ihrer Familie, siehe services/units.py) - egal ob
            # der Nutzer "1kg"/"1 Kilo"/"2 EL" eingetippt oder eine bereits
            # in der Anzeige-Einheit vorbefüllte Import-/Bearbeiten-Zeile
            # unverändert übernommen hat.
            amount, unit = normalize_amount_unit(amount, ing_units[i])
            normalized_ingredients.append({"name": ing_names[i], "amount": amount, "unit": unit, "category": category})

    if nutrition_override:
        calories = int(request.form.get('calories') or 0)
        protein = float(request.form.get('protein') or 0)
        carbs = float(request.form.get('carbs') or 0)
        fat = float(request.form.get('fat') or 0)
    else:
        computed = compute_recipe_nutrition(normalized_ingredients, servings)
        calories, protein, carbs, fat = computed["calories"], computed["protein"], computed["carbs"], computed["fat"]

    new_recipe = Recipe(
        name=name, category_id=category_id,
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

    Nährwerte: siehe add_recipe() - werden standardmäßig aus den (neuen)
    Zutaten neu berechnet statt die Formularfelder zu übernehmen, außer
    bei gesetztem nutrition_override-Häkchen.
    """
    recipe = Recipe.query.get_or_404(id)

    recipe.name = request.form.get('name')
    recipe.category_id = request.form.get('category_id')
    recipe.is_side_dish = request.form.get('is_side_dish') == '1'
    recipe.is_favorite = request.form.get('is_favorite') == '1'
    recipe.nutrition_override = request.form.get('nutrition_override') == '1'
    recipe.servings = max(1, int(request.form.get('servings') or 2))
    recipe.source_url = (request.form.get('source_url') or '').strip() or None
    recipe.instructions = (request.form.get('instructions') or '').strip() or None

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
            # Siehe add_recipe() oben - dieselbe Normalisierung auf die
            # kanonische Form. Da die Formularfelder hier mit der bereits
            # in der Anzeige-Einheit umgerechneten Menge vorbefüllt wurden
            # (siehe recipe_edit_list_view: ingredient_display), liefert
            # ein Speichern ohne Änderung wieder exakt den ursprünglichen
            # kanonischen Wert zurück.
            amount, unit = normalize_amount_unit(amount, ing_units[i])
            normalized_ingredients.append({"name": ing_names[i], "amount": amount, "unit": unit, "category": category})

    for ing in normalized_ingredients:
        db.session.add(Ingredient(
            recipe_id=recipe.id, name=ing["name"], amount=ing["amount"], unit=ing["unit"], category=ing["category"]
        ))

    if recipe.nutrition_override:
        recipe.calories = int(request.form.get('calories') or 0)
        recipe.protein = float(request.form.get('protein') or 0)
        recipe.carbs = float(request.form.get('carbs') or 0)
        recipe.fat = float(request.form.get('fat') or 0)
    else:
        computed = compute_recipe_nutrition(normalized_ingredients, recipe.servings)
        recipe.calories, recipe.protein = computed["calories"], computed["protein"]
        recipe.carbs, recipe.fat = computed["carbs"], computed["fat"]

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

    Bewusst KEINE Prüfung, ob das Rezept noch im Wochenplan-Kalender
    referenziert wird: PlanDay.main_recipe_id und PlanDaySide.recipe_id sind
    beide nullable/ohne ON DELETE-Constraint, ein gelöschtes Rezept
    hinterlässt dort einfach eine "hängende" ID. Das ist ein bekanntes, in
    Kauf genommenes Verhalten (siehe IDEAS.md) - für die kleine,
    persönliche Nutzung dieser App bislang nicht relevant genug,
    um dafür extra eine Lösch-Sperre oder Kaskade einzubauen.
    """
    recipe = Recipe.query.get_or_404(id)
    db.session.delete(recipe)
    db.session.commit()
    return redirect(url_for('recipes.recipe_edit_list_view'))


@recipes_bp.route('/manage/recipe/import-preview', methods=['POST'])
def import_recipe_preview():
    """AJAX-Endpunkt hinter dem "Importieren"-Button auf der Erstellen-Seite
    (siehe recipe_create.html): lädt die übergebene chefkoch.de-URL und gibt
    die daraus ausgelesenen Rezeptdaten als JSON zurück (siehe
    services/recipe_import.py: fetch_recipe_from_url). Legt selbst NICHTS
    in der Datenbank an - das Frontend befüllt damit nur das normale
    Anlegen-Formular, gespeichert wird erst über den regulären
    add_recipe()-Absende-Weg, nachdem der Nutzer alles (insbesondere die
    Kategorie) geprüft/ergänzt hat.

    Erwartet einen JSON-Body {"url": str}. Fehler (nicht unterstützte
    Domain, Netzwerkfehler, kein Rezept gefunden) kommen als
    RecipeImportError mit einer bereits fertig formulierten deutschen
    Fehlermeldung zurück, die 1:1 im {"error": ...}-JSON landet.
    """
    data = request.get_json() or {}
    url = (data.get('url') or '').strip()
    if not url:
        return {"error": "Bitte einen Link eingeben."}, 400

    try:
        imported = fetch_recipe_from_url(url)
    except RecipeImportError as e:
        return {"error": str(e)}, 400

    # fetch_recipe_from_url() liefert Zutatenmengen bereits kanonisch
    # (g/ml, siehe services/recipe_import.py: _parse_ingredient_line) -
    # für die Vorschau auf die vom Nutzer gewählte Anzeige-Einheit
    # umrechnen, damit das vorbefüllte Formular konsistent mit jeder
    # anderen Mengen-Anzeige in der App ist (siehe services/units.py).
    display_units = get_display_units()
    imported['ingredients'] = [
        {**ing, **dict(zip(('amount', 'unit'), convert_for_display(ing['amount'], ing['unit'], display_units)))}
        for ing in imported['ingredients']
    ]
    return imported
