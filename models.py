"""SQLAlchemy-Datenmodelle der Speiseplan-App.

Sieben Tabellen mit folgenden Beziehungen:

    Category 1---n Recipe 1---n Ingredient
                      |  1
                      |  n
                RecipeSeason

    Recipe 1---n PlanDay (als main_recipe)
    Recipe 1---n PlanDaySide n---1 PlanDay

    ExtraShoppingItem (eigenständig, nur über week_start lose an eine
                        Kalenderwoche gebunden - kein Fremdschlüssel)

Rezepte (Recipe) sind die zentrale Entität: sie gehören zu genau einer
Kategorie, tragen ihre eigenen Zutaten sowie optional mehrere
Verfügbarkeitszeiträume (RecipeSeason). Der Wochenplan-Kalender (PlanDay)
verweist pro Kalendertag auf höchstens ein Hauptgericht, aber über
PlanDaySide auf BELIEBIG VIELE Zusatzgerichte (Beilagen) - anders als das
Hauptgericht (eine einzelne Fremdschlüssel-Spalte main_recipe_id direkt auf
PlanDay) ist das deshalb eine eigene 1:n-Tabelle statt einer einzelnen
Spalte. ExtraShoppingItem ergänzt die aus den Rezept-Zutaten abgeleitete
Einkaufsliste um manuell hinzugefügte Posten (z.B. Hygieneartikel), die zu
keinem Rezept gehören.
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
    #
    # Werden standardmäßig NICHT mehr von Hand gepflegt, sondern beim
    # Speichern automatisch aus den Zutaten berechnet (siehe
    # services/nutrition.py: compute_recipe_nutrition(), aufgerufen aus
    # routes/recipes.py: add_recipe()/edit_recipe()) - die Summe der
    # Zutaten-Nährwerte (services/nutrition.py: IngredientNutrition) wird
    # dabei durch servings geteilt, da Ingredient.amount für die GANZE
    # Portionsanzahl gilt, diese Felder hier aber PRO Portion. Bleiben
    # trotzdem direkt beschreibbare Spalten (nicht rein berechnet/nicht
    # gespeichert): nutrition_override=True erlaubt weiterhin eine manuell
    # eingetragene, nie automatisch überschriebene Angabe - z.B. wenn für
    # ein Fertigprodukt nur der Nährwert auf der Packung bekannt ist, nicht
    # aber der einzelner Zutaten.
    calories = db.Column(db.Integer, default=0)
    protein = db.Column(db.Float, default=0.0)
    carbs = db.Column(db.Float, default=0.0)
    fat = db.Column(db.Float, default=0.0)
    nutrition_override = db.Column(db.Boolean, default=False, nullable=False)

    # Herkunfts-Link (z.B. die chefkoch.de-Seite, von der importiert wurde,
    # oder ein von Hand eingetragener Link zu einem Rezept anderswo) und die
    # Zubereitungsanleitung als freier Text. Beide optional und unabhängig
    # vom Import nutzbar - auch ein komplett manuell angelegtes Rezept darf
    # einen Link/eine Anleitung haben. Siehe services/recipe_import.py für
    # den automatischen Import von chefkoch.de, der beide Felder befüllt.
    source_url = db.Column(db.String(500), nullable=True)
    instructions = db.Column(db.Text, nullable=True)

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

    category ist optional und einer der festen Werte aus
    services/shopping.py: SHOPPING_CATEGORIES (kein eigener Fremdschlüssel,
    da die Liste bewusst klein/fest ist) - bestimmt, in welchem
    Supermarkt-Bereich diese Zutat in der Einkaufsliste einsortiert wird.
    None (z.B. bei Zutaten aus der Zeit vor Einführung dieses Felds) landet
    dort in der Sonstiges-Sammelgruppe.
    """
    id = db.Column(db.Integer, primary_key=True)
    recipe_id = db.Column(db.Integer, db.ForeignKey('recipe.id'), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    unit = db.Column(db.String(20), nullable=False)
    category = db.Column(db.String(50), nullable=True)


class PlanDay(db.Model):
    """Der dauerhafte Wochenplan-Kalender: ein Datensatz pro echtem
    Kalendertag, für den jemals ein Plan erstellt oder bearbeitet wurde.

    Anders als in früheren Versionen der App wird der Wochenplan nicht mehr
    nur einmalig serverseitig gerendert und anschließend nur im Browser
    gehalten (ein Neuladen der Seite hätte alles verworfen) - jede Änderung
    (Würfeln, Tauschen, Beilage hinzufügen, Personenzahl ändern) schreibt
    sofort in diese Tabelle (siehe routes/plan/).

    Ein Tag ohne PlanDay-Zeile bedeutet "für diese Woche wurde noch nie ein
    Plan erstellt" - die Wochenansicht zeigt in dem Fall den
    "Neuen Wochenplan erstellen"-Button statt Tageskarten (has_any_data in
    routes/plan/pages.py: week_view). Sobald eine Woche einmal erstellt wurde,
    bekommen alle 7 Tage eine Zeile, auch wenn main_recipe_id leer bleibt
    und keine einzige PlanDaySide existiert (z.B. bei einem ausgenommenen
    Tag ohne Beilagen).

    main_recipe_id ist ein optionaler Fremdschlüssel für GENAU EIN
    Hauptgericht; die (beliebig vielen) Beilagen hängen dagegen über die
    separate PlanDaySide-Tabelle an dieser Zeile (siehe unten). Ein Tag kann
    also nur ein Hauptgericht haben, aber null bis N Beilagen, unabhängig
    davon - excluded schließt nur das Hauptgericht von der automatischen
    Planung aus, niemals die Beilagen.
    """
    id = db.Column(db.Integer, primary_key=True)
    # unique+index: pro Kalendertag darf es höchstens eine Zeile geben, und
    # die Wochenansicht fragt regelmäßig nach Datumsbereichen (date.in_(...)).
    date = db.Column(db.Date, unique=True, nullable=False, index=True)
    excluded = db.Column(db.Boolean, default=False, nullable=False)
    servings = db.Column(db.Integer, nullable=False, default=2)
    main_recipe_id = db.Column(db.Integer, db.ForeignKey('recipe.id'), nullable=True)

    # Ob das Hauptgericht DIESES Tages bereits gekocht wurde (Checkbox im
    # Rezept-Detail-Fenster, siehe static/plan.js: openRecipeDetail/
    # toggleCooked) - steuert das "Ausgrauen" der Tageskarte im Wochenplan.
    # Bezieht sich bewusst auf die AKTUELLE Zuweisung, nicht das Rezept an
    # sich: wird das Hauptgericht neu gewürfelt/manuell ersetzt, setzen
    # routes/plan/day_actions.py: reroll_day()/set_main_day() dieses Feld
    # automatisch zurück auf False, da es sich dann um ein anderes,
    # noch nicht gekochtes Gericht handelt. Bei swap_days() wandert der
    # Wert dagegen MIT dem Hauptgericht auf den jeweils anderen Tag.
    cooked = db.Column(db.Boolean, default=False, nullable=False)

    main_recipe = db.relationship('Recipe', foreign_keys=[main_recipe_id])
    # cascade="all, delete-orphan": wird ein PlanDay gelöscht (kommt in der
    # aktuellen App nicht vor, aber zur Sicherheit), verschwinden auch seine
    # Beilagen-Zeilen mit, statt als Datenleichen zurückzubleiben.
    # order_by sorgt für eine stabile, chronologische Reihenfolge beim
    # Anzeigen (zuletzt hinzugefügte Beilage erscheint zuletzt).
    sides = db.relationship('PlanDaySide', cascade="all, delete-orphan", order_by='PlanDaySide.id')


class PlanDaySide(db.Model):
    """Eine einzelne Beilage, die einem Kalendertag zugeordnet ist. Ein
    PlanDay kann beliebig viele davon haben (siehe PlanDay.sides) - anders
    als das Hauptgericht (eine einzelne Spalte direkt auf PlanDay) ist das
    hier bewusst eine eigene 1:n-Tabelle, damit die Anzahl der Beilagen pro
    Tag nicht auf einen festen Wert begrenzt ist.

    Kein unique-Constraint auf (plan_day_id, recipe_id): serverseitig wird
    zwar durchgängig verhindert, dieselbe Beilage zweimal in derselben
    Woche zu vergeben (siehe services/planning.py:
    week_side_recipe_ids/choose_recipe), das ist aber eine weiche,
    anwendungsseitige Regel und keine Datenbank-Integritätsbedingung.
    """
    id = db.Column(db.Integer, primary_key=True)
    plan_day_id = db.Column(db.Integer, db.ForeignKey('plan_day.id'), nullable=False)
    recipe_id = db.Column(db.Integer, db.ForeignKey('recipe.id'), nullable=False)

    # Wie PlanDay.cooked oben, nur für diese eine Beilage statt das
    # Hauptgericht des Tages - routes/plan/day_actions.py: reroll_one_side()/
    # set_one_side() setzen es beim Ersetzen der Beilage zurück auf False,
    # move_one_side() (nur ein Verschieben auf einen anderen Tag, dieselbe
    # Zeile bleibt bestehen) lässt es dagegen unangetastet.
    cooked = db.Column(db.Boolean, default=False, nullable=False)

    recipe = db.relationship('Recipe')


class ExtraShoppingItem(db.Model):
    """Ein manuell zur Einkaufsliste einer Woche hinzugefügter Posten, der zu
    keinem Rezept gehört (z.B. Hygieneartikel oder Getränke, die nicht als
    Zutat irgendeines Gerichts eingetragen sind).

    week_start ist bewusst NUR ein Datum (der Montag der betreffenden
    Kalenderwoche, wie start_date überall sonst im Projekt) statt eines
    Fremdschlüssels auf PlanDay/eine eigene "Week"-Tabelle - es gibt kein
    eigenes Wochen-Modell, Wochen existieren nur implizit über die 7
    zusammengehörigen PlanDay-Zeilen. amount/unit sind wie bei Ingredient
    optional und frei, werden aber (anders als Zutaten aus Rezepten) NICHT
    mit der Personenzahl eines Wochentags skaliert, da sie an keinen
    bestimmten Tag oder ein bestimmtes Rezept gebunden sind.
    """
    id = db.Column(db.Integer, primary_key=True)
    week_start = db.Column(db.Date, nullable=False, index=True)
    name = db.Column(db.String(100), nullable=False)
    amount = db.Column(db.Float, nullable=True)
    unit = db.Column(db.String(20), nullable=True)
    category = db.Column(db.String(50), nullable=True)


class AppSettings(db.Model):
    """Globale Anzeige-Einstellungen der App - aktuell nur die bevorzugten
    Einheiten für Masse (g/kg) und Volumen (ml/l), in denen Zutatenmengen
    dargestellt werden sollen (siehe services/units.py: convert_for_display,
    routes/settings.py). Eine einzelne Singleton-Zeile (immer id=1) statt
    einer generischen Key-Value-Tabelle, da es bislang nur diese zwei
    Einstellungen gibt - services/settings.py: get_settings() legt sie bei
    Bedarf lazy mit diesen Defaults an, kein eigener Migrationsschritt in
    app.py nötig. Ändert NICHT die kanonisch in Ingredient.amount/.unit
    gespeicherten Werte (immer Gramm/Milliliter), sondern nur, wie sie
    beim Anzeigen umgerechnet werden."""
    id = db.Column(db.Integer, primary_key=True)
    mass_unit = db.Column(db.String(10), nullable=False, default='g')
    volume_unit = db.Column(db.String(10), nullable=False, default='ml')


class IngredientAlias(db.Model):
    """Ordnet einen konkreten Zutatennamen (z.B. "Spaghetti", "Olivenöl")
    einem übergeordneten, gemeinsamen Namen zu (z.B. "Nudeln", "Öl") - für
    die Einkaufsliste, die sonst "Spaghetti" und "Fusilli" als zwei
    getrennte Posten führen würde, obwohl man dafür meist einfach
    "Nudeln" einkauft. Siehe services/ingredient_aliases.py:
    normalize_ingredient_name() und routes/settings.py: die Verwaltungs-
    Seite, auf der Nutzer diese Zuordnung selbst pflegen können.

    ÄNDERT NICHT den in Ingredient.name gespeicherten/im Rezept
    angezeigten Namen - ein Rezept zeigt weiterhin "Spaghetti" in seiner
    eigenen Zutatenliste. Nur beim Aufbau der Einkaufsliste (siehe
    services/planning.py: jsonify_recipe) wird raw_name durch
    canonical_name ersetzt, damit sich Posten über mehrere Rezepte hinweg
    sinnvoll zusammenfassen lassen. Ein Zutatenname ohne Eintrag hier
    bleibt einfach er selbst (kein Alias = keine Gruppierung nötig).

    raw_name ist bereits in der Form gespeichert, in der jsonify_recipe()
    nachschlägt (.strip().title(), siehe dort) - Groß-/Kleinschreibung und
    Leerraum spielen beim Zuordnen daher keine Rolle.
    """
    id = db.Column(db.Integer, primary_key=True)
    raw_name = db.Column(db.String(100), unique=True, nullable=False, index=True)
    canonical_name = db.Column(db.String(100), nullable=False)


class IngredientNutrition(db.Model):
    """Nährwert-Referenz für eine kanonische Zutat (denselben Namen, den
    auch IngredientAlias/normalize_ingredient_name() liefert - für eine
    alias-gruppierte Zutat wie "Nudeln" also EIN gemeinsamer Eintrag statt
    einem pro Schreibweise wie "Spaghetti"/"Fusilli"). Siehe
    services/nutrition.py: compute_recipe_nutrition() nutzt das, um die
    Rezept-Nährwerte (Recipe.calories/.protein/.carbs/.fat) automatisch
    aus den eingetragenen Zutaten zu berechnen, statt sie von Hand pflegen
    zu müssen (siehe Recipe.nutrition_override für den Opt-out).

    Werte gelten je reference_amount/reference_unit (z.B. 100/"g" oder
    1/"Stk") - beides bewusst frei statt fest auf "je 100g", da nicht
    jede Zutat sinnvoll in Gramm/Milliliter bemessen wird (z.B. Eier
    typischerweise in "Stk"). Ein Zutatenname ohne Eintrag hier ODER mit
    abweichender Einheit zur tatsächlichen Ingredient-Zeile eines Rezepts
    (z.B. Referenz in "g" hinterlegt, aber in diesem Rezept in "Stk"
    verwendet) trägt beim Berechnen einfach 0 bei - kein Fehler, nur eine
    unvollständige Angabe, die sich jederzeit nachtragen lässt."""
    id = db.Column(db.Integer, primary_key=True)
    canonical_name = db.Column(db.String(100), unique=True, nullable=False, index=True)
    reference_amount = db.Column(db.Float, nullable=False, default=100)
    reference_unit = db.Column(db.String(20), nullable=False, default='g')
    calories = db.Column(db.Integer, default=0)
    protein = db.Column(db.Float, default=0.0)
    carbs = db.Column(db.Float, default=0.0)
    fat = db.Column(db.Float, default=0.0)
