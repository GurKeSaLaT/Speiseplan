"""Automatische Nährwert-Berechnung aus den Zutaten eines Rezepts.

Recipe.calories/.protein/.carbs/.fat (siehe models.py) werden standardmäßig
NICHT mehr von Hand gepflegt, sondern beim Speichern eines Rezepts aus den
hinterlegten Nährwert-Referenzen seiner Zutaten berechnet (siehe
compute_recipe_nutrition(), aufgerufen aus routes/recipes.py: add_recipe()/
edit_recipe()) - Recipe.nutrition_override=True schaltet das für ein
einzelnes Rezept ab und lässt die von Hand eingetragenen Werte stehen (z.B.
für ein Fertigprodukt, bei dem nur der Nährwert auf der Packung bekannt ist).

Die Nährwert-Referenzen selbst (IngredientNutrition, siehe models.py) sind
je KANONISCHER Zutat hinterlegt (services/ingredient_aliases.py:
normalize_ingredient_name()) - für eine alias-gruppierte Zutat wie "Nudeln"
also EIN gemeinsamer Eintrag statt einem pro Schreibweise wie "Spaghetti"/
"Fusilli". Die Verwaltungsseite (/manage/ingredient-nutrition, siehe
routes/settings.py) zeigt dabei bewusst NUR die tatsächlichen Alias-
Zielnamen (list_alias_canonical_names()) - unaliasierte Einzelzutaten
bekommen ihren Nährwert stattdessen direkt beim Zutat-Eintragen über den
Inline-Hinweis nachgetragen (siehe static/ingredient_alias_hint.js).

Referenzbasis IMMER 100 g / 100 ml / 1 Stk (REFERENCE_BASES unten) - frei
wählbare Referenzmengen (z.B. "1 Becher", "1 Dose", "1 Prise") wurden
bewusst verworfen: sie sind weder untereinander vergleichbar noch lässt
sich ihre Größe auf der Verwaltungsseite kompakt genug darstellen (siehe
set_nutrition()). Für die eigentliche Berechnung (compute_recipe_nutrition)
zählen zusätzlich stückbasierte Einheiten-Schreibweisen wie "Stück",
"Stange" oder "Scheibe" als gleichwertig zu "Stk" (siehe _normalize_unit) -
das ist bewusst NUR eine Lockerung für den Nährwert-Abgleich, NICHT für
services/units.py: normalize_amount_unit(), da unterschiedliche
Schreibweisen auf der Einkaufsliste weiterhin als eigene Posten geführt
werden sollen.
"""

from collections import Counter

from models import Ingredient, IngredientAlias, IngredientNutrition, db
from services.ingredient_aliases import normalize_ingredient_name
from services.units import normalize_amount_unit

# Referenzbasis je Einheit - siehe Moduldocstring. set_nutrition() erzwingt
# reference_unit aus diesen drei Schlüsseln und leitet reference_amount
# IMMER daraus ab (nie frei eingebbar).
REFERENCE_BASES = {"g": 100, "ml": 100, "Stk": 1}

# Einheiten-Schreibweisen, die beim Nährwert-ABGLEICH (nicht beim Speichern
# der Zutatenzeile selbst!) als "1 Stk" zählen - deckt die auf chefkoch.de
# gebräuchlichen Stückzahl-Angaben ab (siehe services/units.py:
# NON_CONVERTIBLE_UNITS für die vollständige, dort maßgebliche Liste).
_PIECE_LIKE_UNITS = {
    '', 'stk', 'stück', 'stange', 'stangen', 'zehe', 'zehen',
    'scheibe', 'scheiben', 'stk.',
}


def _normalize_unit(unit):
    """Für den Einheiten-Vergleich beim Berechnen (siehe
    compute_recipe_nutrition) - Groß-/Kleinschreibung und Leerraum sollen
    keine Rolle spielen ("g" soll z.B. auch "G" oder " g " treffen), und
    stückbasierte Schreibweisen sollen alle gegen eine "Stk"-Referenz
    matchen (siehe Moduldocstring)."""
    key = (unit or '').strip().lower()
    return 'stk' if key in _PIECE_LIKE_UNITS else key


def get_nutrition_entry(name):
    """Liefert den Nährwert-Eintrag für eine Zutat (beliebige Schreibweise
    - wird intern über normalize_ingredient_name() auf ihre kanonische
    Form aufgelöst) oder None, falls noch keiner hinterlegt ist."""
    canonical = normalize_ingredient_name(name)
    return IngredientNutrition.query.filter_by(canonical_name=canonical).first()


def get_all_nutrition_entries():
    """Alle gepflegten Nährwert-Referenzen als Dict {kanonischer Name:
    {reference_amount, reference_unit, calories, protein, carbs, fat}} -
    Grundlage für window.INGREDIENT_NUTRITION (siehe
    static/ingredient_alias_hint.js), damit der Inline-Hinweis beim
    Zutat-Eintragen ohne Extra-Request weiß, wofür schon ein Nährwert
    hinterlegt ist."""
    return {
        e.canonical_name: {
            "reference_amount": e.reference_amount, "reference_unit": e.reference_unit,
            "calories": e.calories, "protein": e.protein, "carbs": e.carbs, "fat": e.fat,
        }
        for e in IngredientNutrition.query.all()
    }


def set_nutrition(name, reference_unit, calories, protein, carbs, fat):
    """Legt einen Nährwert-Eintrag an oder aktualisiert ihn - name wird wie
    beim Nachschlagen auf seine kanonische Form normalisiert, damit
    "Spaghetti" und "Fusilli" (beide -> "Nudeln", falls alias-gruppiert)
    denselben Eintrag treffen.

    reference_amount gibt es hier bewusst NICHT als Parameter - sie ergibt
    sich immer zwingend aus reference_unit (siehe REFERENCE_BASES/
    Moduldocstring). Ein unbekannter/leerer reference_unit-Wert fällt auf
    "g" zurück, statt einen Fehler zu werfen (z.B. bei manipulierten
    Formulardaten)."""
    canonical = normalize_ingredient_name(name)
    reference_unit = (reference_unit or 'g').strip()
    if reference_unit not in REFERENCE_BASES:
        reference_unit = 'g'

    entry = IngredientNutrition.query.filter_by(canonical_name=canonical).first()
    if not entry:
        entry = IngredientNutrition(canonical_name=canonical)
        db.session.add(entry)
    entry.reference_amount = REFERENCE_BASES[reference_unit]
    entry.reference_unit = reference_unit
    entry.calories = calories
    entry.protein = protein
    entry.carbs = carbs
    entry.fat = fat
    db.session.commit()
    return entry


def list_alias_canonical_names():
    """Alle kanonischen Namen, auf die MINDESTENS eine Zutat per
    IngredientAlias verweist (die eigentlichen Alias-Zielnamen wie
    "Nudeln"/"Öl", NICHT jede einzelne unaliasierte Einzelzutat) -
    genau die Menge, die die Nährwertverwaltungsseite auflisten soll."""
    rows = db.session.query(IngredientAlias.canonical_name).distinct().all()
    return sorted({r[0] for r in rows})


def infer_reference_unit(canonical_name):
    """Rät eine sinnvolle Standard-Referenzeinheit (g/ml/Stk, siehe
    REFERENCE_BASES) für einen NEUEN Nährwert-Eintrag: welche der drei
    Familien unter dieser kanonischen Zutat am häufigsten tatsächlich
    verwendet wird. Jede Zutatenzeile wird dafür über
    services/units.py: normalize_amount_unit() auf ihre Masse-/Volumen-
    Familie geprüft (deckt z.B. "kg" oder "EL" korrekt als Masse/Volumen
    ab, nicht nur die bereits kanonischen "g"/"ml") - alles andere
    (Stk, Bund, Dose, Prise, eine leere Einheit, ...) zählt als "Stk",
    da es sich für eine 100g/100ml-Referenz ohnehin nicht eignet.
    Fällt auf "g" zurück, wenn dazu noch gar keine Zutat-Zeile existiert."""
    families = []
    for ing in Ingredient.query.all():
        if normalize_ingredient_name(ing.name) != canonical_name:
            continue
        _, unit = normalize_amount_unit(1, ing.unit)
        families.append(unit if unit in ('g', 'ml') else 'Stk')
    if not families:
        return 'g'
    return Counter(families).most_common(1)[0][0]


def compute_recipe_nutrition(ingredient_rows, servings):
    """Berechnet die Nährwerte PRO PORTION aus einer Liste von Zutaten-
    Zeilen (Dicts/Objekte mit .name/.amount/.unit, z.B. die gerade im
    Formular abgeschickten oder recipe.ingredients eines bestehenden
    Rezepts).

    Ingredient.amount gilt laut Modell-Dokumentation für die GANZE
    Portionsanzahl (servings), Recipe.calories/.protein/.carbs/.fat
    dagegen PRO Portion - die aufsummierten Zutaten-Beiträge werden daher
    am Ende durch servings geteilt.

    Eine Zutat ohne Nährwert-Eintrag ODER mit abweichender Einheit zur
    hinterlegten Referenz (z.B. Referenz in "g", diese Zeile aber in
    "Stk") trägt 0 bei statt einen Fehler zu werfen - der Aufrufer sieht
    dadurch immer ein vollständiges (wenn auch ggf. unvollständiges)
    Ergebnis, nie einen Absturz wegen fehlender Daten.
    """
    totals = {"calories": 0.0, "protein": 0.0, "carbs": 0.0, "fat": 0.0}
    for ing in ingredient_rows:
        name = ing["name"] if isinstance(ing, dict) else ing.name
        amount = ing["amount"] if isinstance(ing, dict) else ing.amount
        unit = ing["unit"] if isinstance(ing, dict) else ing.unit

        entry = get_nutrition_entry(name)
        if not entry or not entry.reference_amount:
            continue
        if _normalize_unit(unit) != _normalize_unit(entry.reference_unit):
            continue

        factor = (amount or 0) / entry.reference_amount
        totals["calories"] += factor * (entry.calories or 0)
        totals["protein"] += factor * (entry.protein or 0)
        totals["carbs"] += factor * (entry.carbs or 0)
        totals["fat"] += factor * (entry.fat or 0)

    servings = servings or 1
    return {
        "calories": round(totals["calories"] / servings),
        "protein": round(totals["protein"] / servings, 1),
        "carbs": round(totals["carbs"] / servings, 1),
        "fat": round(totals["fat"] / servings, 1),
    }
