"""SQLAlchemy-Datenmodelle der Speiseplan-App.

Fünf Tabellen mit folgenden Beziehungen:

    Category 1---n Recipe 1---n Ingredient
                      |  1
                      |  n
                RecipeSeason

    Recipe 1---n PlanDay (einmal als main_recipe, einmal als side_recipe)

Rezepte (Recipe) sind die zentrale Entität: sie gehören zu genau einer
Kategorie, tragen ihre eigenen Zutaten sowie optional mehrere
Verfügbarkeitszeiträume (RecipeSeason). Der Wochenplan-Kalender (PlanDay)
verweist pro Kalendertag auf höchstens ein Haupt- und ein Zusatzgericht.
"""

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class Category(db.Model):
    """Eine Rezept-Kategorie (z.B. "Fleisch", "Vegetarisch", "Pasta").

    Kategorien werden bei der automatischen Wochenplan-Erstellung genutzt,
    um die Auswahl über die Woche hinweg möglichst gleichmäßig zu verteilen
    (siehe services/planning.py: assign_balanced_categories). Eine Kategorie
    lässt sich erst löschen, wenn ihr keine Rezepte mehr zugeordnet sind
    (siehe routes/categories.py: delete_category).
    """
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)


class Recipe(db.Model):
    """Ein Gericht: entweder ein Hauptgericht oder eine Beilage, mit
    Nährwertangaben, einer beliebigen Zutatenliste und optionalen
    Saison-Einschränkungen.

    is_side_dish unterscheidet zwei komplett getrennte Auswahl-Pools: bei
    der automatischen Wochenplanung werden Hauptgerichte (is_side_dish=False)
    und Beilagen (is_side_dish=True) nie miteinander vermischt (siehe
    services/planning.py: choose_recipe).
    """
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey('category.id'), nullable=False)
    is_side_dish = db.Column(db.Boolean, default=False, nullable=False)

    # Favoriten werden bei der automatischen Auswahl höher gewichtet
    # (FAVORITE_WEIGHT in services/planning.py), blockieren aber nichts -
    # nur ein weicher Bonus, kein Ausschlusskriterium für andere Rezepte.
    is_favorite = db.Column(db.Boolean, default=False, nullable=False)

    # Für wie viele Personen die unten gepflegten Zutatenmengen ausgelegt
    # sind. Die Nährwerte (calories/protein/carbs/fat) bleiben davon
    # unberührt, da sie immer PRO PORTION gelten - nur die Zutatenmengen für
    # die Einkaufsliste werden im Frontend anhand des Verhältnisses aus
    # gewünschter Personenzahl zu diesem Wert hoch- oder runtergerechnet
    # (siehe static/plan.js: rebuildShoppingList).
    servings = db.Column(db.Integer, nullable=False, default=2)

    # Nährwerte, jeweils pro Portion (nicht für das gesamte Rezept/alle
    # servings zusammen). Alle vier Felder sind optional und defaulten auf 0.
    calories = db.Column(db.Integer, default=0)
    protein = db.Column(db.Float, default=0.0)
    carbs = db.Column(db.Float, default=0.0)
    fat = db.Column(db.Float, default=0.0)

    category = db.relationship('Category', backref=db.backref('recipes', lazy=True))
    # cascade="all, delete-orphan": Zutaten werden automatisch mitgelöscht,
    # sobald das Rezept gelöscht wird - es gibt keine "verwaisten" Zutaten.
    ingredients = db.relationship('Ingredient', backref='recipe', cascade="all, delete-orphan")

    # Keine Einträge = ganzjährig verfügbar (Standardfall für die meisten
    # Rezepte). Mit einem oder mehreren Einträgen ist das Rezept nur dann
    # "verfügbar" (siehe services/seasons.py: recipe_available_now), wenn
    # das heutige Datum (Monat/Tag, jahresunabhängig) in mindestens einen
    # der hinterlegten Zeiträume fällt. Das schränkt nur die AUTOMATISCHE
    # Auswahl ein, nie die manuelle Auswahl über die Suche.
    seasons = db.relationship('RecipeSeason', backref='recipe', cascade="all, delete-orphan")


class RecipeSeason(db.Model):
    """Ein einzelner Verfügbarkeitszeitraum eines Rezepts, als Monat/Tag
    ohne Jahresbezug (z.B. "1.6. bis 31.8." für Sommer).

    Ein Rezept kann mehrere davon gleichzeitig haben: sowohl mehrere
    angehakte Standard-Saisons (Frühling/Sommer/Herbst/Winter, deren feste
    Monat/Tag-Grenzen in services/seasons.py als SEASON_PRESETS hinterlegt
    sind) als auch einen selbst definierten Zeitraum. Ein Zeitraum, dessen
    Ende vor seinem Start liegt (z.B. Winter: 1.12. bis 28.2.), läuft über
    den Jahreswechsel - das Auswerten dieser Zeiträume übernimmt
    services/seasons.py: date_in_range.
    """
    id = db.Column(db.Integer, primary_key=True)
    recipe_id = db.Column(db.Integer, db.ForeignKey('recipe.id'), nullable=False)
    start_month = db.Column(db.Integer, nullable=False)
    start_day = db.Column(db.Integer, nullable=False)
    end_month = db.Column(db.Integer, nullable=False)
    end_day = db.Column(db.Integer, nullable=False)


class Ingredient(db.Model):
    """Eine einzelne Zutat eines Rezepts mit Menge und Einheit.

    amount/unit sind bewusst freie Werte (kein kontrolliertes Vokabular):
    unit ist Freitext (z.B. "g", "Stk", "EL"), amount gilt für die auf
    Recipe.servings festgelegte Personenzahl. Beim Zusammenstellen der
    Einkaufsliste wird amount clientseitig mit der pro Wochentag
    eingestellten Personenzahl skaliert (siehe static/plan.js).
    """
    id = db.Column(db.Integer, primary_key=True)
    recipe_id = db.Column(db.Integer, db.ForeignKey('recipe.id'), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    unit = db.Column(db.String(20), nullable=False)


class PlanDay(db.Model):
    """Der dauerhafte Wochenplan-Kalender: ein Datensatz pro echtem
    Kalendertag, für den jemals ein Plan erstellt oder bearbeitet wurde.

    Anders als in früheren Versionen der App wird der Wochenplan nicht mehr
    nur einmalig serverseitig gerendert und anschließend nur im Browser
    gehalten (ein Neuladen der Seite hätte alles verworfen) - jede Änderung
    (Würfeln, Tauschen, Beilage hinzufügen, Personenzahl ändern) schreibt
    sofort in diese Tabelle (siehe routes/plan.py).

    Ein Tag ohne PlanDay-Zeile bedeutet "für diese Woche wurde noch nie ein
    Plan erstellt" - die Wochenansicht zeigt in dem Fall den
    "Neuen Wochenplan erstellen"-Button statt Tageskarten (has_any_data in
    routes/plan.py: week_view). Sobald eine Woche einmal erstellt wurde,
    bekommen alle 7 Tage eine Zeile, auch wenn main_recipe_id/side_recipe_id
    dabei leer bleiben (z.B. bei einem ausgenommenen Tag).

    main_recipe_id und side_recipe_id sind bewusst getrennte, jeweils
    optionale Fremdschlüssel: ein Tag kann nur ein Hauptgericht haben, nur
    eine Beilage, beides, oder (falls "excluded") auch nur eine Beilage
    ohne Hauptgericht - excluded schließt nur das Hauptgericht von der
    automatischen Planung aus, niemals die Beilage.
    """
    id = db.Column(db.Integer, primary_key=True)
    # unique+index: pro Kalendertag darf es höchstens eine Zeile geben, und
    # die Wochenansicht fragt regelmäßig nach Datumsbereichen (date.in_(...)).
    date = db.Column(db.Date, unique=True, nullable=False, index=True)
    excluded = db.Column(db.Boolean, default=False, nullable=False)
    servings = db.Column(db.Integer, nullable=False, default=2)
    main_recipe_id = db.Column(db.Integer, db.ForeignKey('recipe.id'), nullable=True)
    side_recipe_id = db.Column(db.Integer, db.ForeignKey('recipe.id'), nullable=True)

    # Zwei separate Relationships auf dieselbe Recipe-Tabelle - foreign_keys
    # muss hier jeweils explizit angegeben werden, da SQLAlchemy sonst nicht
    # eindeutig zuordnen kann, welche der beiden FK-Spalten gemeint ist.
    main_recipe = db.relationship('Recipe', foreign_keys=[main_recipe_id])
    side_recipe = db.relationship('Recipe', foreign_keys=[side_recipe_id])
