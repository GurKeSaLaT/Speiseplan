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

    plan_id bindet die Kategorie an EINEN Plan (siehe Plan/PlanMembership
    weiter unten) - jeder Plan pflegt seine eigene Kategorie-Liste, analog
    zu den übrigen "Einstellungen" (AppSettings/IngredientAlias/
    IngredientNutrition). name ist deshalb nur noch INNERHALB eines Plans
    eindeutig (siehe __table_args__), nicht mehr global.
    """
    id = db.Column(db.Integer, primary_key=True)
    plan_id = db.Column(db.Integer, db.ForeignKey('plan.id'), nullable=False, index=True)
    name = db.Column(db.String(50), nullable=False)

    __table_args__ = (db.UniqueConstraint('plan_id', 'name', name='uq_category_plan_id_name'),)


class Recipe(db.Model):
    """Ein Gericht: entweder ein Hauptgericht oder eine Beilage, mit
    Nährwertangaben, einer beliebigen Zutatenliste und optionalen
    Saison-Einschränkungen.

    is_side_dish unterscheidet zwei komplett getrennte Auswahl-Pools: bei
    der automatischen Wochenplanung werden Hauptgerichte (is_side_dish=False)
    und Beilagen (is_side_dish=True) nie miteinander vermischt (siehe
    services/planning.py: choose_recipe).

    owner_plan_id ist der Plan, unter dem das Rezept ursprünglich angelegt
    wurde ("an den eigenen Plan gebunden") - RecipePlanLink (siehe unten)
    ergänzt das um beliebig viele WEITERE Pläne, in denen dasselbe Rezept
    zusätzlich sichtbar/nutzbar ist (echte Verknüpfung, keine Kopie: eine
    Änderung an Name/Zutaten/Anleitung wirkt sich überall aus, wo das
    Rezept eingebunden ist). services/planning.py: visible_recipes_query()
    ist die einzige Stelle, die "für Plan X nutzbare Rezepte" tatsächlich
    auflöst (owner_plan_id == X ODER ein RecipePlanLink auf X) - alle
    Routen fragen darüber ab statt Recipe.query direkt, damit diese Regel
    nicht an mehreren Stellen dupliziert wird. category_id zeigt dabei
    IMMER auf eine Kategorie des EIGENTÜMER-Plans (owner_plan_id) - wird
    das Rezept in einen anderen Plan eingebunden, übernimmt es dessen
    Kategorie unverändert mit, unabhängig von der Kategorie-Liste des
    Ziel-Plans.
    """
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    owner_plan_id = db.Column(db.Integer, db.ForeignKey('plan.id'), nullable=False, index=True)
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
    # eingetragene, nie automatisch überschriebene Angabe für protein/
    # carbs/fat - z.B. wenn für ein Fertigprodukt nur der Nährwert auf der
    # Packung bekannt ist, nicht aber der einzelner Zutaten. calories
    # selbst wird dabei NIE direkt eingegeben, auch nicht im Override-Fall
    # - es ergibt sich immer aus protein/carbs/fat (services/nutrition.py:
    # compute_calories(), Atwater-Faustregel 4/4/9 kcal je g), um die
    # Angabe nicht redundant und potenziell widersprüchlich zu machen.
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

    # Für die "Zuletzt bearbeitet"-Liste auf der Verwaltungs-Übersichtsseite
    # (routes/manage.py) - default setzt den Zeitpunkt beim Anlegen
    # (routes/recipes.py: add_recipe()). BEWUSST kein onupdate=...: das
    # würde nur greifen, wenn sich mindestens ein SPALTENWERT tatsächlich
    # ändert (SQLAlchemy markiert eine Zuweisung auf denselben Wert nicht
    # als "dirty") - speichert ein Nutzer ein Rezept unverändert erneut
    # (z.B. nur die Zutatenliste angefasst, alle anderen Felder identisch
    # gelassen), würde der Zeitpunkt sonst NICHT aktualisiert. edit_recipe()
    # setzt dieses Feld deshalb explizit bei jedem Speichern.
    updated_at = db.Column(db.DateTime, default=db.func.now())

    category = db.relationship('Category', backref=db.backref('recipes', lazy=True))
    owner_plan = db.relationship('Plan', foreign_keys=[owner_plan_id])
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

    # cascade="all, delete-orphan": Verknüpfungen zu weiteren Plänen
    # verschwinden automatisch mit, sobald das Rezept selbst gelöscht wird.
    plan_links = db.relationship('RecipePlanLink', backref='recipe', cascade="all, delete-orphan")


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


class RecipePlanLink(db.Model):
    """Bindet ein Rezept ZUSÄTZLICH an einen weiteren Plan, über seinen
    eigentlichen Eigentümer-Plan (Recipe.owner_plan_id) hinaus - "Gericht
    zu einem anderen Plan hinzufügen" legt genau eine solche Zeile an.

    Das ist eine ECHTE Verknüpfung, keine Kopie: dieselbe Recipe-Zeile
    (inkl. all ihrer Ingredient-/RecipeSeason-Zeilen) wird für den
    verknüpften Plan sichtbar und voll bearbeitbar - eine Änderung wirkt
    sich für ALLE Pläne aus, in denen das Rezept eingebunden ist. Siehe
    services/planning.py: visible_recipes_query() für die einzige Stelle,
    die diese Sichtbarkeitsregel auswertet.

    Kein unique-Constraint gegen den EIGENTÜMER-Plan selbst (Recipe.
    owner_plan_id) auf Datenbankebene - wird stattdessen von der Route
    verhindert (siehe routes/recipes.py: link_recipe_to_plan), die dafür
    ohnehin bereits current_plan()/Mitgliedschaften nachschlagen muss.
    """
    id = db.Column(db.Integer, primary_key=True)
    recipe_id = db.Column(db.Integer, db.ForeignKey('recipe.id'), nullable=False, index=True)
    plan_id = db.Column(db.Integer, db.ForeignKey('plan.id'), nullable=False, index=True)

    __table_args__ = (db.UniqueConstraint('recipe_id', 'plan_id', name='uq_recipe_plan_link_recipe_id_plan_id'),)

    plan = db.relationship('Plan')


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
    # Zu welchem Plan (siehe Plan/PlanMembership unten) dieser Kalendertag
    # gehört - jeder Plan hat seinen eigenen, unabhängigen Kalender. Das
    # frühere unique=True direkt auf date (ein Tag konnte höchstens EINE
    # Zeile in der GESAMTEN App haben) ist deshalb einem zusammengesetzten
    # Unique (plan_id, date) gewichen (siehe __table_args__ unten): zwei
    # verschiedene Pläne dürfen für denselben Kalendertag jeweils eine
    # eigene Zeile haben.
    plan_id = db.Column(db.Integer, db.ForeignKey('plan.id'), nullable=False, index=True)
    # index=True (statt zusätzlich unique=True, das jetzt über
    # __table_args__ läuft): die Wochenansicht fragt regelmäßig nach
    # Datumsbereichen (date.in_(...)).
    date = db.Column(db.Date, nullable=False, index=True)
    excluded = db.Column(db.Boolean, default=False, nullable=False)
    servings = db.Column(db.Integer, nullable=False, default=2)
    main_recipe_id = db.Column(db.Integer, db.ForeignKey('recipe.id'), nullable=True)

    __table_args__ = (db.UniqueConstraint('plan_id', 'date', name='uq_plan_day_plan_id_date'),)

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

    plan_id ordnet den Posten (wie PlanDay.plan_id) einem bestimmten Plan
    zu - dieselbe Kalenderwoche kann in zwei verschiedenen Plänen jeweils
    eigene manuelle Posten haben.
    """
    id = db.Column(db.Integer, primary_key=True)
    plan_id = db.Column(db.Integer, db.ForeignKey('plan.id'), nullable=False, index=True)
    week_start = db.Column(db.Date, nullable=False, index=True)
    name = db.Column(db.String(100), nullable=False)
    amount = db.Column(db.Float, nullable=True)
    unit = db.Column(db.String(20), nullable=True)
    category = db.Column(db.String(50), nullable=True)


class AppSettings(db.Model):
    """Anzeige-Einstellungen EINES Plans - aktuell nur die bevorzugten
    Einheiten für Masse (g/kg) und Volumen (ml/l), in denen Zutatenmengen
    dargestellt werden sollen (siehe services/units.py: convert_for_display,
    routes/settings.py). Eine Zeile PRO Plan (plan_id unique) statt einer
    einzelnen globalen Singleton-Zeile wie früher - services/settings.py:
    get_settings(plan_id) legt sie bei Bedarf lazy mit diesen Defaults an,
    kein eigener Migrationsschritt für NEUE Pläne nötig (nur für bereits
    bestehende Bestandsdaten, siehe app.py: init_db()). Ändert NICHT die
    kanonisch in Ingredient.amount/.unit gespeicherten Werte (immer Gramm/
    Milliliter), sondern nur, wie sie beim Anzeigen umgerechnet werden."""
    id = db.Column(db.Integer, primary_key=True)
    plan_id = db.Column(db.Integer, db.ForeignKey('plan.id'), unique=True, nullable=False, index=True)
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
    Leerraum spielen beim Zuordnen daher keine Rolle. plan_id bindet die
    Zuordnung an EINEN Plan (jeder Plan pflegt seine eigene Gleichsetzung),
    raw_name ist deshalb nur noch INNERHALB eines Plans eindeutig.
    """
    id = db.Column(db.Integer, primary_key=True)
    plan_id = db.Column(db.Integer, db.ForeignKey('plan.id'), nullable=False, index=True)
    raw_name = db.Column(db.String(100), nullable=False, index=True)
    canonical_name = db.Column(db.String(100), nullable=False)

    __table_args__ = (db.UniqueConstraint('plan_id', 'raw_name', name='uq_ingredient_alias_plan_id_raw_name'),)


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
    unvollständige Angabe, die sich jederzeit nachtragen lässt.

    Bewusst KEINE eigene calories-Spalte: Kalorien lassen sich aus
    Eiweiß/Kohlenhydraten/Fett errechnen (4 kcal/g je Eiweiß und
    Kohlenhydrate, 9 kcal/g Fett - die Atwater-Faustregel) und wären als
    zusätzlich gepflegter Wert nur eine redundante, potenziell
    widersprüchliche Angabe. Siehe services/nutrition.py: compute_calories().

    plan_id bindet den Eintrag an EINEN Plan (jeder Plan pflegt seine
    eigenen Nährwert-Referenzen), canonical_name ist deshalb nur noch
    INNERHALB eines Plans eindeutig."""
    id = db.Column(db.Integer, primary_key=True)
    plan_id = db.Column(db.Integer, db.ForeignKey('plan.id'), nullable=False, index=True)
    canonical_name = db.Column(db.String(100), nullable=False, index=True)
    reference_amount = db.Column(db.Float, nullable=False, default=100)
    reference_unit = db.Column(db.String(20), nullable=False, default='g')
    protein = db.Column(db.Float, default=0.0)
    carbs = db.Column(db.Float, default=0.0)
    fat = db.Column(db.Float, default=0.0)

    __table_args__ = (db.UniqueConstraint('plan_id', 'canonical_name', name='uq_ingredient_nutrition_plan_id_canonical_name'),)


class User(db.Model):
    """Ein Nutzer-Konto - siehe services/auth.py für Login/Session-Handling.

    password_hash speichert NIE das Klartext-Passwort, sondern einen über
    werkzeug.security.generate_password_hash() erzeugten Hash (PBKDF2 mit
    Salt) - services/auth.py: check_password() vergleicht damit beim
    Login über werkzeug.security.check_password_hash(), ohne das
    Passwort selbst je wieder rekonstruieren zu können.

    Login erfolgt über email (immer klein geschrieben gespeichert, siehe
    routes/auth.py: login()/register()) - name ist reiner Anzeigename OHNE
    Eindeutigkeit, zwei Nutzer dürfen also gleich heißen. Registrierung
    läuft über routes/auth.py: register() (Button auf der Login-Seite);
    beim App-Start in app.py: init_db() werden zusätzlich weiterhin zwei
    generische Demo-Konten ("Nutzer1"/"Nutzer2") gesät (Platzhalter-
    E-Mails nach dem Schema <name>@example.com, siehe dort).

    language is the ISO 639-1 code Flask-Babel uses to pick this user's
    translation catalog (see app.py: get_locale()) - defaults to 'en'
    (English is the app's default language). Changeable on /manage/account
    (see services/accounts.py: update_profile())."""
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    language = db.Column(db.String(5), nullable=False, default='en')
    created_at = db.Column(db.DateTime, default=db.func.now())


class Plan(db.Model):
    """Ein eigenständiger Wochenplan-"Haushalt": eine unabhängige Sammlung
    von PlanDay-Zeilen (siehe dort: PlanDay.plan_id) samt Einkaufsliste
    (ExtraShoppingItem.plan_id) UND eigenem Kochbuch/eigenen Einstellungen
    (Recipe.owner_plan_id, Category.plan_id, AppSettings.plan_id,
    IngredientAlias.plan_id, IngredientNutrition.plan_id) - jeder Plan
    verwaltet seine Rezepte, Kategorien, Zutaten-Gleichsetzungen, Nährwert-
    Referenzen und Anzeige-Einheiten komplett unabhängig von anderen
    Plänen. Ein Rezept lässt sich zusätzlich per RecipePlanLink in einen
    ANDEREN Plan einbinden (siehe dort) - eine echte Verknüpfung, kein
    eigenes Kochbuch pro Plan im Sinne getrennter Kopien.

    Jeder Nutzer bekommt beim Anlegen automatisch genau einen eigenen Plan
    (owner_user_id, siehe app.py: init_db()); über PlanMembership (unten)
    lassen sich weitere Nutzer mit vollem Zugriff zu einem Plan hinzufügen
    (siehe routes/sharing.py: invite_member).

    owner_user_id ist rein informativ (zeigt z.B. auf der Freigabeseite,
    wer den Plan ursprünglich angelegt hat) - für die eigentliche
    Zugriffskontrolle zählt ausschließlich, ob eine PlanMembership-Zeile
    für den jeweiligen Nutzer existiert (auch der Eigentümer selbst bekommt
    beim Anlegen eine ganz normale, nur zusätzlich gesternte Mitgliedschaft,
    siehe unten) - kein Nutzer hat also über owner_user_id allein weitere
    Rechte, die ein eingeladenes Mitglied nicht auch hätte.
    """
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    owner_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=db.func.now())

    owner = db.relationship('User', foreign_keys=[owner_user_id])


class PlanMembership(db.Model):
    """Verknüpft einen Nutzer mit einem Plan, auf den er Zugriff hat (voller
    Lese-/Schreibzugriff für alle Mitglieder, kein Unterschied zwischen
    Eigentümer und eingeladenem Mitglied - siehe Plan.owner_user_id oben).

    is_starred markiert PRO NUTZER (nicht global) den einen Plan, der nach
    dem Login automatisch geöffnet wird und oben in der Navigation steht
    (siehe services/auth.py: current_plan()). Dass wirklich immer nur EINE
    Mitgliedschaft desselben Nutzers gleichzeitig gesternt ist, wird nicht
    über ein Datenbank-Constraint erzwungen (SQLite kennt keinen "at most
    one true per user_id"-Constraint ohne Umwege), sondern auf
    Anwendungsebene: routes/sharing.py: star_plan() entsternt in
    DERSELBEN Transaktion zuerst alle anderen Mitgliedschaften desselben
    Nutzers, bevor die neue gesetzt wird.

    show_in_week_overview steuert, analog PRO NUTZER (nicht global), ob
    dieser Plan in DEN WOCHENPLAN-TAGESKACHELN ANDERER Pläne desselben
    Nutzers als zusätzlicher, nur lesbarer Eintrag auftaucht (siehe
    routes/plan/pages.py: week_view() - "otherPlanMeals"). Betrifft NICHT
    die Ansicht des Plans selbst (der bleibt, wenn er der aktive Plan ist,
    immer normal sichtbar) - nur, ob er bei einem GETEILTEN Plan für DIESEN
    einen Nutzer zusätzlich in die Kacheln der übrigen eigenen Pläne
    einfließt. Default True (neue Mitgliedschaften fließen automatisch mit
    ein), abschaltbar über die Checkbox auf /manage/sharing.
    """
    id = db.Column(db.Integer, primary_key=True)
    plan_id = db.Column(db.Integer, db.ForeignKey('plan.id'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    is_starred = db.Column(db.Boolean, default=False, nullable=False)
    show_in_week_overview = db.Column(db.Boolean, default=True, nullable=False)

    __table_args__ = (db.UniqueConstraint('plan_id', 'user_id', name='uq_plan_membership_plan_id_user_id'),)

    plan = db.relationship('Plan')
    user = db.relationship('User')


class PendingPlanInvite(db.Model):
    """Eine per E-Mail ausgesprochene Plan-Einladung an eine NOCH NICHT
    registrierte Adresse (siehe routes/sharing.py: invite_member() - für
    eine bereits existierende E-Mail entsteht stattdessen sofort eine
    echte PlanMembership, keine Zeile hier).

    Registriert sich später jemand mit genau dieser E-Mail (klein
    geschrieben, siehe routes/auth.py: register()), wird die Einladung
    automatisch in eine echte PlanMembership umgewandelt und diese Zeile
    dabei gelöscht (services/plans.py: accept_pending_invites()) - bis
    dahin bleibt sie hier als sichtbarer "ausstehend"-Eintrag auf
    /manage/sharing stehen (samt erneut abrufbarem Einladungs-Link, da noch
    kein echter Mail-Versand angebunden ist, siehe services/mail.py)."""
    id = db.Column(db.Integer, primary_key=True)
    plan_id = db.Column(db.Integer, db.ForeignKey('plan.id'), nullable=False, index=True)
    email = db.Column(db.String(255), nullable=False, index=True)
    invited_at = db.Column(db.DateTime, default=db.func.now())

    __table_args__ = (db.UniqueConstraint('plan_id', 'email', name='uq_pending_plan_invite_plan_id_email'),)

    plan = db.relationship('Plan')
