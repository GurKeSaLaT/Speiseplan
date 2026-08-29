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
    "Backwaren",
    "Milchprodukte",
    "Gewürze",
    "Vorratsschrank",
    "Hygieneartikel",
    "Verbrauchsartikel",
    "Getränke",
    "Teigwaren",
    "Konserven",
    "Tiefkühlware",
]

# Auffangkategorie für Zutaten/Artikel ohne (oder mit einer inzwischen
# entfernten) Kategorie - sortiert in der Einkaufsliste immer ans Ende,
# siehe categorySortIndex() in static/plan.js.
UNCATEGORIZED = "Sonstiges"

# Zutaten dieser Kategorien hat man in aller Regel schon zuhause vorrätig
# (Gewürze, Vorratsschrank-Backzutaten/Nüsse/Saucen, Verbrauchsartikel wie
# Frischhaltefolie/Müllbeutel) - sie landen deshalb NICHT automatisch auf
# der wöchentlichen Einkaufsliste, sondern auf einer separaten "Vorrat
# prüfen"-Liste (siehe static/plan-shopping.js: rebuildShoppingList/
# rebuildPantryList), von der aus man einzelne Posten gezielt per Button
# doch noch auf die Einkaufsliste holen kann, falls z.B. das Salz gerade
# alle ist. Betrifft ausdrücklich nur aus Rezepten abgeleitete Posten - ein
# manuell hinzugefügter Artikel (auch einer, der gerade erst über besagten
# Button von der Vorratsliste geholt wurde) hat damit bereits seine "ich
# muss das wirklich kaufen"-Absicht erklärt und landet immer direkt auf der
# Einkaufsliste, unabhängig von seiner Kategorie (siehe isExtra-Prüfung in
# rebuildShoppingList()). Backwaren ist bewusst NICHT hier: Brot/Brötchen
# sind im Gegensatz dazu typischerweise ein frischer wöchentlicher Einkauf,
# keine Vorratsware.
PANTRY_CATEGORIES = {"Gewürze", "Vorratsschrank", "Verbrauchsartikel"}
