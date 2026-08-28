"""Verwaltungs-Startseite: eine einzelne Übersichtsseite mit Links zu den
Rezept- und Kategorie-Verwaltungsseiten (die in routes/recipes.py bzw.
routes/categories.py liegen). Bewusst als eigenes, minimales Blueprint
gehalten statt in eine der beiden anderen Dateien gepackt zu werden, da sie
zu keiner der beiden Zuständigkeiten eindeutig gehört."""

from flask import Blueprint, render_template

manage_bp = Blueprint('manage', __name__)


@manage_bp.route('/manage')
def manage():
    """Zeigt die drei Kacheln "Rezepte erstellen", "Rezepte bearbeiten" und
    "Kategorien verwalten" (siehe templates/manage.html). Reine, statische
    Übersichtsseite ohne eigene Datenbank-Abfrage."""
    return render_template('manage.html')
