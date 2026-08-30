"""Rezept-Verwaltung: die Erstellen-/Bearbeiten-/Löschen-Seiten für einzelne
Gerichte (Recipe), inklusive ihrer Zutaten (Ingredient), Saison-Zuordnung
(RecipeSeason, über services/seasons.py verwaltet) und dem Import von
chefkoch.de (über services/recipe_import.py).

recipe_create_view() und recipe_edit_view() rendern beide dasselbe Formular-
Template (templates/recipe_form.html), einmal mit recipe=None (Anlegen) und
einmal mit einem geladenen Recipe (Bearbeiten) - recipe_edit_list_view()
zeigt nur noch die reine Übersichtsliste, die dorthin verlinkt. Drei
POST-Handler (add_recipe, edit_recipe, delete_recipe) verarbeiten das
Absenden. import_recipe_preview() ist ein vierter, JSON-basierter
POST-Handler für den AJAX-Import-Button auf der Anlegen-Seite - er
speichert NICHTS, sondern liefert nur die aus einer chefkoch.de-URL
ausgelesenen Rezeptdaten zurück, mit denen recipe_form.html das normale
Formular vorbefüllt (siehe services/recipe_import.py für den Grund: die
Kategorie muss der Nutzer ohnehin selbst wählen, ein direktes Speichern
ohne Review wäre riskanter).

Ein Rezept gehört EINEM Plan (Recipe.owner_plan_id) und kann zusätzlich in
beliebig viele weitere Pläne eingebunden sein (RecipePlanLink, siehe
models.py und services/recipe_visibility.py: link_recipe_to_plan/
unlink_recipe_from_plan unten) - eine echte Verknüpfung, keine Kopie.
Sichtbar (anzeig-/bearbeitbar) ist ein Rezept in JEDEM Plan, der entweder
sein Eigentümer ist oder eine solche Verknüpfung hat.

Die eigentliche Saison-Formular-Logik (Checkboxen + eigener Zeitraum
parsen, für die Bearbeiten-Ansicht vorbefüllen) liegt bewusst NICHT hier,
sondern in services/seasons.py - diese Datei bleibt auf "Recipe/Ingredient
anlegen, ändern, löschen" fokussiert.
"""

from datetime import datetime, timezone

from flask import Blueprint, abort, render_template, request, redirect, url_for

from models import db, Category, Recipe, RecipePlanLink, Ingredient
from services.auth import current_plan, current_user, selected_plan_id, user_has_plan_access, user_plan_memberships
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
    """Alphabetisch sortierte, über alle für plan_id SICHTBAREN Rezepte
    hinweg EINZIGARTIGE Liste kanonischer (über eine evtl. bestehende
    Alias-Zuordnung DIESES Plans aufgelöster, siehe
    services/ingredient_aliases.py) Zutatennamen - füllt in den
    Rezept-Formularen ein <datalist>-Element (Autovervollständigung beim
    Tippen einer Zutat), damit z.B. "Zwiebel" nicht in einem Rezept als
    "Zwiebeln" und im nächsten als "zwiebel" landet.

    Bewusst die KANONISCHEN statt der rohen, tatsächlich gespeicherten
    Namen: schlägt damit von vornherein den bereits gleichgesetzten Namen
    vor, statt weitere Varianten in die Welt zu setzen, die man später
    erst wieder gleichsetzen müsste. Nebeneffekt: ein <input list="...">
    mit deutlich weniger Optionen ist für den Browser beim Fokussieren
    auch spürbar schneller aufzubauen."""
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
    """Zeigt das Formular zum Anlegen eines neuen Rezepts - dasselbe
    Template wie recipe_edit_view() unten (templates/recipe_form.html),
    nur mit recipe=None (siehe dortigen Kommentar). Ein neues Rezept
    gehört immer dem gerade AKTIVEN Plan (current_plan()) - dessen
    Kategorien werden zur Auswahl angeboten, das "in andere Pläne
    einbinden"-Formular gibt es hier nicht (ein Rezept muss erst
    existieren, bevor es verknüpft werden kann - siehe recipe_edit_view)."""
    plan = current_plan()
    categories = Category.query.filter_by(plan_id=plan.id).order_by(Category.name).all()
    return render_template(
        'recipe_form.html', categories=categories, recipe=None,
        ingredient_list=_canonical_ingredient_list(plan.id), seasons=SEASONS,
        selected_presets=set(), custom_start='', custom_end='',
        linkable_plans=[], linked_plan_ids=set(),
    )


@recipes_bp.route('/manage/recipe/edit/<int:id>')
def recipe_edit_view(id):
    """Zeigt das Formular zum Bearbeiten EINES bestehenden Rezepts -
    dasselbe Template wie recipe_create_view() oben, nur mit gesetztem
    recipe. Nur erreichbar, wenn das Rezept für den AUSGEWÄHLTEN Plan
    SICHTBAR ist (siehe services/auth.py: selected_plan_id - i.d.R. der
    Tab, von dem aus recipe_edit_list.html verlinkt hat, sonst der aktive
    Plan, siehe Eigentümer ODER per RecipePlanLink eingebunden,
    services/recipe_visibility.py) - alles andere ist wie "existiert
    nicht" zu behandeln, ein 404 statt eines 403 verrät dabei nicht
    einmal, ob die ID überhaupt zu einem echten Rezept gehört.

    Kategorien kommen bewusst aus dem EIGENTÜMER-Plan des Rezepts
    (recipe.owner_plan_id), nicht aus dem ausgewählten Plan: Recipe.
    category_id zeigt immer auf eine Kategorie des Eigentümers (siehe
    models.py: Recipe-Docstring) - bei einem nur eingebundenen Rezept
    ließe sich sonst gar keine passende Kategorie anzeigen/ändern.
    linkable_plans/linked_plan_ids füttern das "in weiteren Plan
    einbinden"-Steuerelement (siehe templates/recipe_form.html). plan_id
    wandert als verstecktes Feld ins Formular (siehe dort) und von da in
    edit_recipe()/link_recipe_to_plan()/unlink_recipe_from_plan() -
    dieselbe Sichtweise bleibt über den gesamten Bearbeiten-Vorgang
    erhalten, unabhängig vom sonst aktiven Plan (current_plan())."""
    user = current_user()
    plan_id = selected_plan_id(request.args, user)
    recipe = visible_recipes_query(plan_id).filter(Recipe.id == id).first()
    if recipe is None:
        abort(404)
    categories = Category.query.filter_by(plan_id=recipe.owner_plan_id).order_by(Category.name).all()

    # Siehe ehemals recipe_edit_list_view() weiter unten für denselben
    # Umrechnungs-/Aufbereitungs-Schritt, hier nur noch für GENAU EIN
    # Rezept statt für alle gleichzeitig. Alias-/Einheiten-Kontext ist
    # bewusst der des AUSGEWÄHLTEN Plans (nicht des Eigentümers) - wer ein
    # nur eingebundenes Rezept bearbeitet, soll seine EIGENEN
    # Gleichsetzungen/Anzeige-Einheiten sehen, siehe services/planning.py:
    # jsonify_recipe-Docstring für denselben Grundsatz auf der Plan-Seite.
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
    """Zeigt die reine Übersichtsliste aller für den ausgewählten Plan
    SICHTBAREN Rezepte (Suche/Filter, Badges, Bearbeiten-/Löschen-Link) -
    das eigentliche Bearbeiten-Formular liegt seit recipe_edit_view() oben
    auf einer eigenen Seite pro Rezept, diese Liste verlinkt nur noch
    dorthin (siehe templates/recipe_edit_list.html: "Bearbeiten
    ✏️"-Button).

    Hat ein Nutzer Zugriff auf mehr als einen Plan (eigener + freigegebene),
    zeigt die Seite einen Tab-Umschalter (siehe services/auth.py:
    selected_plan_id/user_plan_memberships, analog zu routes/categories.py)
    - own_plan_id ist dabei der gerade ausgewählte Plan (Tab), nicht
    zwingend der sonst aktive (current_plan()): bestimmt, welche Rezepte
    als "eigene" (löschbar) statt nur "verknüpft" (nur entfernbar)
    gelten."""
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
    """Legt ein neues Rezept samt seiner Zutaten und Saison-Zuordnung an,
    als Eigentum des aktuell aktiven Plans (Recipe.owner_plan_id).

    Ablauf: zuerst wird das Recipe-Objekt angelegt und per db.session.flush()
    (statt commit()) in die Datenbank geschrieben - flush() weist bereits
    eine ID zu, OHNE die Transaktion abzuschließen, damit diese ID direkt
    für die abhängigen RecipeSeason- und Ingredient-Zeilen verwendet werden
    kann. Erst der abschließende commit() macht alles zusammen dauerhaft
    (bei einem Fehler dazwischen würde alles zurückgerollt).

    Die Zutaten kommen als vier parallele Listen aus dem Formular
    (ing_name[], ing_amount[], ing_unit[], ing_category[] - ein
    HTML-Formular mit dynamisch per JavaScript hinzugefügten Zeilen, siehe
    recipe_form.html), werden über den gemeinsamen Index paarweise
    zusammengeführt und Zeilen mit leerem Namen übersprungen (z.B. eine
    ungenutzte letzte leere Zeile im Formular). ing_category[] ist dabei
    der einzige der vier optional: ein leerer String wird zu None (siehe
    services/shopping.py: UNCATEGORIZED - None landet in der Einkaufsliste
    in der Sonstiges-Sammelgruppe, ganz ohne extra Sonderfall hier).

    Nährwerte: werden standardmäßig aus den Zutaten berechnet (siehe
    services/nutrition.py: compute_recipe_nutrition(), anhand der
    Nährwert-Referenzen DES AKTIVEN PLANS) statt die Formularfelder
    ungeprüft zu übernehmen - nur bei gesetztem nutrition_override-
    Häkchen (im Formular per JS deaktivierte, aber weiterhin abgesendete
    Felder) gelten die eingetragenen protein/carbs/fat-Werte direkt.
    calories wird dabei NIE aus dem Formular übernommen, auch nicht im
    Override-Fall - es ergibt sich immer aus protein/carbs/fat
    (services/nutrition.py: compute_calories()), um keinen redundanten,
    potenziell widersprüchlichen Kalorienwert zu erlauben. Die
    Zutatenzeilen werden dafür VOR dem Anlegen des Recipe-Objekts
    normalisiert (Menge/Einheit), damit sowohl die Berechnung als auch
    die späteren Ingredient-Zeilen dieselben, bereits kanonischen Werte
    verwenden.
    """
    plan = current_plan()
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
        protein = float(request.form.get('protein') or 0)
        carbs = float(request.form.get('carbs') or 0)
        fat = float(request.form.get('fat') or 0)
        calories = compute_calories(protein, carbs, fat)
    else:
        computed = compute_recipe_nutrition(plan.id, normalized_ingredients, servings)
        calories, protein, carbs, fat = computed["calories"], computed["protein"], computed["carbs"], computed["fat"]

    new_recipe = Recipe(
        name=name, owner_plan_id=plan.id, category_id=category_id,
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
    Nur erlaubt, wenn das Rezept für den aktiven Plan sichtbar ist (siehe
    recipe_edit_view) - JEDES Mitglied eines Plans, dem das Rezept gehört
    ODER in den es eingebunden ist, darf es voll bearbeiten (kein
    Unterschied zwischen Eigentümer und nur verknüpft, siehe models.py:
    RecipePlanLink-Docstring).

    Die Zutaten werden dabei nicht einzeln abgeglichen (kein Diff aus
    "geändert/neu/gelöscht"), sondern komplett gelöscht und aus dem
    Formularinhalt neu angelegt - deutlich einfacher als ein Merge, und da
    das Formular ohnehin immer ALLE aktuellen Zutaten mitschickt (auch
    unveränderte), verliert dieser Ansatz keine Daten. Ebenso verfährt
    save_recipe_seasons() mit den Saison-Zeiträumen.

    Nährwerte: siehe add_recipe() - werden standardmäßig aus den (neuen)
    Zutaten neu berechnet (anhand der Referenzen DES AKTIVEN PLANS) statt
    die Formularfelder zu übernehmen, außer bei gesetztem
    nutrition_override-Häkchen.
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
    # Explizit statt über ein onupdate=... an der Spalte (siehe models.py:
    # Recipe.updated_at) - das würde nur greifen, wenn sich mindestens ein
    # Spaltenwert tatsächlich ändert, hier soll aber JEDES Speichern
    # zählen, auch ein inhaltlich unverändertes.
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
            # Siehe add_recipe() oben - dieselbe Normalisierung auf die
            # kanonische Form. Da die Formularfelder hier mit der bereits
            # in der Anzeige-Einheit umgerechneten Menge vorbefüllt wurden
            # (siehe recipe_edit_view: ingredient_display), liefert
            # ein Speichern ohne Änderung wieder exakt den ursprünglichen
            # kanonischen Wert zurück.
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
    # Zurück zur Bearbeitungsliste (im Gegensatz zu add_recipe, das zurück
    # zur Erstellen-Seite leitet) - hier gibt es kein "nächstes" Rezept,
    # zu dem man direkt weiterspringen würde. plan_id sorgt dafür, dass
    # der zuvor ausgewählte Tab (falls einer aktiv war) erhalten bleibt.
    return redirect(url_for('recipes.recipe_edit_list_view', plan_id=plan_id))


@recipes_bp.route('/delete-recipe/<int:id>', methods=['POST'])
def delete_recipe(id):
    """Löscht ein Rezept unwiderruflich - nur der EIGENTÜMER-Plan
    (Recipe.owner_plan_id) darf das; ein Plan, dem das Rezept nur per
    RecipePlanLink zusätzlich eingebunden ist, kann sich stattdessen über
    unlink_recipe_from_plan() unten wieder AUSKLINKEN, ohne das Rezept für
    alle anderen Pläne mitzulöschen. Zugehörige Ingredient-/RecipeSeason-/
    RecipePlanLink-Zeilen werden durch die cascade="all, delete-orphan"-
    Konfiguration in models.py automatisch mitgelöscht.

    Bewusst KEINE Prüfung, ob das Rezept noch im Wochenplan-Kalender
    referenziert wird: PlanDay.main_recipe_id und PlanDaySide.recipe_id sind
    beide nullable/ohne ON DELETE-Constraint, ein gelöschtes Rezept
    hinterlässt dort einfach eine "hängende" ID. Das ist ein bekanntes, in
    Kauf genommenes Verhalten (siehe IDEAS.md) - für die kleine,
    persönliche Nutzung dieser App bislang nicht relevant genug,
    um dafür extra eine Lösch-Sperre oder Kaskade einzubauen.

    Berechtigung: Mitgliedschaft im EIGENTÜMER-Plan (Recipe.owner_plan_id),
    nicht zwingend der gerade aktive Plan (current_plan()) - wer z.B. über
    einen Tab ein Rezept eines ANDEREN eigenen Plans betrachtet, kann es
    trotzdem löschen, ohne vorher extra dorthin umschalten zu müssen
    (analog zu routes/categories.py: delete_category())."""
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
    """"Gericht zu einem anderen Plan hinzufügen": bindet ein für den
    ausgewählten Plan (siehe recipe_edit_view()) sichtbares Rezept
    ZUSÄTZLICH an target_plan_id ein (siehe models.py: RecipePlanLink) -
    eine echte Verknüpfung, keine Kopie. Erfordert, dass der eingeloggte
    Nutzer tatsächlich Mitglied von target_plan_id ist (sonst könnte er
    fremde Pläne mit Rezepten "zuspammen", auf die er selbst gar keinen
    Zugriff hat)."""
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
    """Entfernt eine per link_recipe_to_plan() gesetzte Verknüpfung wieder
    - der EIGENTÜMER-Plan selbst lässt sich hierüber NICHT entfernen (dafür
    gibt es delete_recipe() oben), das Rezept bliebe sonst ohne jeden
    Plan, dem es gehört.

    Ist ausgerechnet der gerade ausgewählte Plan (plan_id) das Ziel des
    Entfernens (der Normalfall beim "Entfernen 🔗"-Button auf
    recipe_edit_list.html - siehe dort target_plan_id=own_plan_id), wird
    das Rezept für DIESE Sicht unsichtbar: ein Redirect zurück auf
    recipe_edit_view() würde dann sofort 404 liefern, da visible_recipes_
    query(plan_id) es nicht mehr findet - deshalb in diesem Fall zurück
    zur Liste statt zur (nicht mehr erreichbaren) Detailseite. Wird
    dagegen ein ANDERER Plan entfernt (die "✕"-Badges in
    templates/recipe_form.html für die übrigen Verknüpfungen), bleibt das
    Rezept über plan_id weiterhin sichtbar - dort zurück zur Detailseite."""
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
    """AJAX-Endpunkt hinter dem "Importieren"-Button auf der Erstellen-Seite
    (siehe recipe_form.html): lädt die übergebene chefkoch.de-URL und gibt
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
    display_units = get_display_units(current_plan().id)
    imported['ingredients'] = [
        {**ing, **dict(zip(('amount', 'unit'), convert_for_display(ing['amount'], ing['unit'], display_units)))}
        for ing in imported['ingredients']
    ]
    return imported
