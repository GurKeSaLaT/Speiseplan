"""Verwaltungs-Startseite: eine Dashboard-Übersicht mit Kennzahlen und
einer Seitenleisten-Navigation zu den Rezept-/Kategorie-/Einheiten-/
Zutaten-/Nährwert-Verwaltungsseiten (die jeweils in eigenen Blueprints
liegen - routes/recipes.py, routes/categories.py, routes/settings.py).
Bewusst als eigenes, minimales Blueprint gehalten statt in eine der
anderen Dateien gepackt zu werden, da sie zu keiner der Zuständigkeiten
eindeutig gehört."""

from datetime import datetime, timezone

from flask import Blueprint, render_template

from models import Category, IngredientNutrition, Recipe
from services.nutrition import list_alias_canonical_names

manage_bp = Blueprint('manage', __name__)

# Wie viele kürzlich bearbeitete Rezepte die "Zuletzt bearbeitet"-Liste
# zeigt (siehe manage() unten) - kein Konfigurationswert, da es nur diese
# eine Stelle betrifft.
RECENT_RECIPES_LIMIT = 6


def _format_relative_day(dt):
    """Formatiert einen Zeitpunkt als groben, deutschen Tagesabstand zu
    HEUTE ("Heute"/"Gestern"/"vor N Tagen") für die "Zuletzt bearbeitet"-
    Liste - bewusst grob (kein Uhrzeit-/Stunden-Feingranulat), da diese
    Liste nur einen schnellen Überblick geben soll, keine exakte Historie."""
    days = (datetime.now(timezone.utc).replace(tzinfo=None).date() - dt.date()).days
    if days <= 0:
        return "Heute"
    if days == 1:
        return "Gestern"
    return f"vor {days} Tagen"


@manage_bp.route('/manage')
def manage():
    """Zeigt die Verwaltungs-Übersichtsseite (siehe templates/manage.html):
    eine feste Seitenleiste mit gruppierter Navigation (Rezepte/Daten) plus
    Darstellung-Umschalter, und im Hauptbereich eine kleine Kennzahlen-Zeile
    sowie die zuletzt bearbeiteten Rezepte (Recipe.updated_at, siehe
    models.py - wird bei jedem Speichern in routes/recipes.py: edit_recipe()
    aktualisiert).

    "Zutaten gleichgesetzt" zählt die tatsächlichen Alias-ZIELnamen
    (list_alias_canonical_names(), z.B. "Nudeln") - nicht die Anzahl der
    einzelnen zusammengefassten Schreibweisen. "Nährwerte gepflegt" zählt
    die Anzahl vorhandener IngredientNutrition-Referenzeinträge.
    """
    recent_recipes = (
        Recipe.query.filter(Recipe.updated_at.isnot(None))
        .order_by(Recipe.updated_at.desc())
        .limit(RECENT_RECIPES_LIMIT)
        .all()
    )
    stats = {
        "recipe_count": Recipe.query.count(),
        "category_count": Category.query.count(),
        "aliased_ingredient_count": len(list_alias_canonical_names()),
        "nutrition_entry_count": IngredientNutrition.query.count(),
    }
    recent = [
        {"recipe": r, "when": _format_relative_day(r.updated_at)}
        for r in recent_recipes
    ]
    return render_template('manage.html', stats=stats, recent=recent)
