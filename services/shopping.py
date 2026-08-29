"""Feste Kategorie-Liste für die Einkaufsliste (Supermarkt-Bereiche).

Anders als Category (Rezept-Kategorien wie "Fleisch"/"Vegetarisch", die der
Nutzer frei über die Kategorie-Verwaltung anlegt/löscht) ist das hier eine
kleine, bewusst FESTE Aufzählung mit einer festen Reihenfolge - deshalb eine
einfache Python-Liste statt einer eigenen Datenbanktabelle. Wird über den
Kontext-Prozessor inject_shopping_categories() (app.py) an ALLE Templates
durchgereicht und zusätzlich per window.SHOPPING_CATEGORIES (base.html) für
die clientseitige Sortierung/Gruppierung der Einkaufsliste (static/plan.js:
rebuildShoppingList) verfügbar gemacht - beide Seiten verwenden also genau
dieselbe Reihenfolge.
"""

SHOPPING_CATEGORIES = [
    "Obst/Gemüse",
    "Milchprodukte",
    "Gewürze",
    "Hygieneartikel",
    "Getränke",
    "Teigwaren",
    "Konserven",
    "Tiefkühlware",
]

# Auffangkategorie für Zutaten/Artikel ohne (oder mit einer inzwischen
# entfernten) Kategorie - sortiert in der Einkaufsliste immer ans Ende,
# siehe categorySortIndex() in static/plan.js.
UNCATEGORIZED = "Sonstiges"
