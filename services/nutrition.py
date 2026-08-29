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
"""

from collections import Counter

from models import Ingredient, IngredientAlias, IngredientNutrition, db
from services.ingredient_aliases import normalize_ingredient_name


def _normalize_unit(unit):
    """Für den Einheiten-Vergleich beim Berechnen (siehe
    compute_recipe_nutrition) - Groß-/Kleinschreibung und Leerraum sollen
    keine Rolle spielen ("g" soll z.B. auch "G" oder " g " treffen)."""
    return (unit or '').strip().lower()


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


def set_nutrition(name, reference_amount, reference_unit, calories, protein, carbs, fat):
    """Legt einen Nährwert-Eintrag an oder aktualisiert ihn - name wird wie
    beim Nachschlagen auf seine kanonische Form normalisiert, damit
    "Spaghetti" und "Fusilli" (beide -> "Nudeln", falls alias-gruppiert)
    denselben Eintrag treffen."""
    canonical = normalize_ingredient_name(name)
    entry = IngredientNutrition.query.filter_by(canonical_name=canonical).first()
    if not entry:
        entry = IngredientNutrition(canonical_name=canonical)
        db.session.add(entry)
    entry.reference_amount = reference_amount
    entry.reference_unit = (reference_unit or 'g').strip()
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
    """Rät eine sinnvolle Standard-Einheit für einen NEUEN Nährwert-
    Eintrag: die unter dieser kanonischen Zutat am häufigsten tatsächlich
    verwendete Einheit (z.B. "g" für "Mehl", "Stk" für "Ei") - fällt auf
    "g" zurück, wenn dazu noch gar keine Zutat-Zeile existiert."""
    units = [
        ing.unit for ing in Ingredient.query.all()
        if ing.unit and normalize_ingredient_name(ing.name) == canonical_name
    ]
    if not units:
        return 'g'
    return Counter(units).most_common(1)[0][0]


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
