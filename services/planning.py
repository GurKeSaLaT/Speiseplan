"""Kern-Planungslogik der App: alles, was bestimmt, WELCHER Wochentag WELCHES
Datum hat und WELCHES Rezept an einem Tag landet.

Drei zusammenhängende Aufgabenbereiche in dieser Datei:

1. Wochen-/Datums-Helfer (monday_of, week_dates_for, parse_iso_date,
   week_neighbor_exclude_ids, week_side_recipe_ids): rechnen zwischen
   "Wochenstart-Datum" und den sieben zugehörigen Kalendertagen um, und
   ermitteln, welche Rezepte in derselben Kalenderwoche bereits verplant
   sind - für Hauptgerichte (ein Wert pro Tag) und Beilagen (beliebig viele
   pro Tag, siehe models.py: PlanDaySide) getrennt, da sich beide
   strukturell unterscheiden.

2. Kategorie-Balance (assign_balanced_categories): entscheidet beim
   automatischen Auffüllen einer Woche, welche KATEGORIE (nicht welches
   Rezept) an welchem Tag drankommt - möglichst gleichmäßig über alle
   Kategorien verteilt und nach Möglichkeit ohne Wiederholung an
   aufeinanderfolgenden Tagen.

3. Rezept-Auswahl (choose_recipe, weighted_recipe_choice, recent_usage_counts,
   jsonify_recipe, jsonify_side): wählt dann tatsächlich EIN konkretes
   Rezept aus einer Kategorie/einem Pool aus, unter Berücksichtigung von
   Favoriten-Gewichtung, Saison-Verfügbarkeit und einer weichen
   Wiederholungs-Gewichtung (je häufiger ein Rezept kürzlich im Plan
   vorkam, desto seltener wird es erneut gezogen - keine harte Sperre,
   siehe recent_usage_counts). jsonify_recipe/jsonify_side serialisieren
   das Ergebnis für die JSON-Antworten der AJAX-Endpunkte in routes/plan/.

Wird vom routes/plan/-Paket sowohl beim Neu-Erstellen einer ganzen Woche
(pages.py) als auch beim Einzel-Tag-Reroll über HTTP-Endpunkte
(day_actions.py) verwendet.
"""

import random
from collections import Counter
from datetime import date, timedelta

from models import db, Recipe, PlanDay, PlanDaySide
from services.seasons import recipe_available_now

# Deutsche Wochentagsnamen in ISO-Reihenfolge (Montag = Index 0), passend zu
# date.weekday(). Wird sowohl für die Berechnung des Wochenstarts als auch
# als Kontextvariable "days" an die Templates plan.html/create_week.html
# durchgereicht, damit der Name nicht doppelt gepflegt werden muss.
DAY_NAMES_DE = ['Montag', 'Dienstag', 'Mittwoch', 'Donnerstag', 'Freitag', 'Samstag', 'Sonntag']

# Wie viel wahrscheinlicher ein als Favorit markiertes Rezept bei der
# automatischen/Zufalls-Auswahl gezogen wird, verglichen mit einem nicht
# favorisierten Rezept (3 = dreimal so wahrscheinlich). Reines
# Geschmacks-/Stimmungsgewicht, kein harter Filter - Nicht-Favoriten bleiben
# immer im Auswahl-Pool.
FAVORITE_WEIGHT = 3

# Wie viele Wochen zurück recent_usage_counts() für die weiche
# Wiederholungs-Gewichtung schaut - Verwendungen, die länger her sind,
# fließen nicht mehr in die Zählung ein (das Rezept ist dann wieder "wie
# neu", volle Gewichtung). Bewusst als eigene Konstante, falls sich in der
# Praxis ein anderer Zeitraum als sinnvoller herausstellt.
REPETITION_LOOKBACK_WEEKS = 8


def recent_usage_counts(recipe_ids, reference_date, is_side_dish):
    """Zählt für jede der übergebenen Rezept-IDs, wie oft sie in den
    letzten REPETITION_LOOKBACK_WEEKS Wochen VOR reference_date im
    Plan-Kalender verwendet wurde. Gibt ein Dict {Rezept-ID: Anzahl}
    zurück - Rezepte ohne jede Verwendung in diesem Zeitraum fehlen darin
    einfach (kein Eintrag mit 0).

    is_side_dish unterscheidet, WELCHE Tabelle abgefragt wird:
    Hauptgerichte stecken direkt in PlanDay.main_recipe_id (ein Wert pro
    Tag), Beilagen dagegen in der separaten PlanDaySide-Tabelle (beliebig
    viele pro Tag, siehe models.py) - beide Pools werden dabei getrennt
    gezählt, da sie bei der Auswahl ohnehin nie vermischt werden (siehe
    choose_recipe).

    reference_date ist bewusst NICHT date.today(), sondern der Tag, für den
    gerade geplant wird - die Wochenplanung erlaubt auch vergangene oder
    zukünftige Wochen, die Zählung soll sich immer auf den Zeitraum
    UNMITTELBAR VOR dem betrachteten Tag beziehen, unabhängig vom
    tatsächlichen heutigen Datum.

    Wird von choose_recipe() genutzt, um weighted_recipe_choice() eine
    weiche (nicht ausschließende) Wiederholungs-Gewichtung mitzugeben -
    siehe dort.
    """
    if not recipe_ids:
        return {}
    since = reference_date - timedelta(weeks=REPETITION_LOOKBACK_WEEKS)

    if is_side_dish:
        rows = (
            db.session.query(PlanDaySide.recipe_id)
            .join(PlanDay, PlanDaySide.plan_day_id == PlanDay.id)
            .filter(PlanDay.date >= since, PlanDay.date < reference_date, PlanDaySide.recipe_id.in_(recipe_ids))
            .all()
        )
        return Counter(rid for (rid,) in rows)

    rows = PlanDay.query.filter(
        PlanDay.date >= since, PlanDay.date < reference_date, PlanDay.main_recipe_id.in_(recipe_ids)
    ).all()
    return Counter(pd.main_recipe_id for pd in rows)


def weighted_recipe_choice(recipes, usage_counts=None):
    """Wählt zufällig ein Rezept aus einer Liste, funktional wie
    random.choice(), aber gewichtet nach zwei voneinander unabhängigen
    Kriterien, die multiplikativ kombiniert werden:

    1. Favoriten (is_favorite) bekommen FAVORITE_WEIGHT-fache
       Basis-Gewichtung gegenüber allen anderen (Basis-Gewicht 1).
    2. Weiche Wiederholungs-Gewichtung: usage_counts (siehe
       recent_usage_counts, optional - fehlt es, verhält sich diese
       Funktion wie vor Einführung dieser Gewichtung) gibt an, wie oft ein
       Rezept kürzlich im Plan vorkam. Der Faktor 1/(Anzahl+1) sorgt dafür,
       dass die Wahrscheinlichkeit mit jeder zusätzlichen kürzlichen
       Verwendung SINKT (nie verwendet: Faktor 1, einmal: 0.5, zweimal:
       0.33, ...), aber NIE auf 0 fällt - anders als eine harte Sperre
       bleibt jedes Rezept theoretisch immer wählbar, nur unwahrscheinlicher.

    Da choose_recipe() diese Funktion erst NACH der Saison-Filterung
    aufruft (siehe dort), wirkt sich das automatisch auch auf gerade
    saisonale Rezepte begünstigend aus, ganz ohne einen dritten Faktor hier:
    ist die Saison-Vorauswahl aktiv, sind schlicht nur noch saisonale
    Kandidaten überhaupt im Pool, unter denen dann wie gewohnt gewichtet wird.

    random.choices() (mit s!) übernimmt die eigentliche gewichtete Ziehung;
    k=1 liefert genau ein Element, das per [0] ausgepackt wird.
    """
    usage_counts = usage_counts or {}
    weights = [
        (FAVORITE_WEIGHT if r.is_favorite else 1) / (usage_counts.get(r.id, 0) + 1)
        for r in recipes
    ]
    return random.choices(recipes, weights=weights, k=1)[0]


# --- WOCHEN-KALENDER-HELFER ---
# Der Wochenplan arbeitet durchgehend mit echten Kalendertagen (date-Objekte),
# nicht mit einem abstrakten "Tag 0-6"-Konzept ohne Datumsbezug. Diese vier
# kleinen Funktionen sind die einzige Stelle, an der zwischen "irgendein
# Datum" und "Montag-Start einer Kalenderwoche" umgerechnet wird.

def monday_of(d):
    """Liefert den Montag der Kalenderwoche, in der das Datum d liegt.
    date.weekday() liefert 0 für Montag bis 6 für Sonntag, daher zieht man
    genau so viele Tage ab, wie d von seinem Wochenanfang entfernt ist."""
    return d - timedelta(days=d.weekday())


def week_dates_for(start):
    """Baut aus einem (als Montag angenommenen) Startdatum die Liste der 7
    Kalendertage dieser Woche, Montag zuerst. Es wird NICHT geprüft, ob
    start tatsächlich ein Montag ist - das übernimmt monday_of() vorher an
    den Aufrufstellen (siehe routes/plan/)."""
    return [start + timedelta(days=i) for i in range(7)]


def parse_iso_date(value):
    """Parst einen String im ISO-Format ("YYYY-MM-DD", z.B. aus einem
    URL-Pfadsegment oder einem <input type="date">) zu einem date-Objekt.
    Gibt bei ungültiger oder fehlender Eingabe None statt einer Exception
    zurück, damit Aufrufer (typischerweise Route-Handler) das einheitlich
    mit einem 404/400 statt einem 500-Fehler beantworten können."""
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def week_neighbor_exclude_ids(day_date):
    """Sammelt die Hauptgericht-Rezept-IDs aller ANDEREN Tage in derselben
    Kalenderwoche wie day_date - für die Dubletten-Vermeidung beim
    (Neu-)Würfeln eines Hauptgerichts (siehe week_side_recipe_ids weiter
    unten für das Beilagen-Pendant, das anders arbeitet, weil ein Tag dort
    mehrere Einträge gleichzeitig haben kann).

    day_date selbst wird bewusst AUSGESCHLOSSEN (siehe "if pd.date ==
    day_date: continue") - der Tag, der gerade neu gewürfelt wird, soll
    sein eigenes aktuelles Rezept nicht als "belegt" an sich selbst zählen
    lassen. Die Aufrufer in routes/plan/day_actions.py fügen das aktuelle Rezept des
    Zieltags bei Bedarf explizit wieder hinzu, um zu verhindern, dass ein
    Reroll dasselbe Rezept erneut auswürfelt.
    """
    start = monday_of(day_date)
    dates = week_dates_for(start)
    rows = PlanDay.query.filter(PlanDay.date.in_(dates)).all()
    ids = set()
    for pd in rows:
        if pd.date == day_date:
            continue
        if pd.main_recipe_id:
            ids.add(pd.main_recipe_id)
    return ids


def week_side_recipe_ids(day_date):
    """Sammelt die Rezept-IDs ALLER Beilagen, die bereits irgendwo in der
    Kalenderwoche verwendet werden, die day_date enthält - über alle 7 Tage
    hinweg, OHNE einen Tag oder eine einzelne Beilage auszunehmen.

    Anders als week_neighbor_exclude_ids() (die den betrachteten Tag selbst
    bewusst ausschließt, damit ein Reroll sein eigenes aktuelles Rezept
    nicht als "belegt an sich selbst" zählt) braucht es hier keine solche
    Ausnahme: da ein Tag mehrere Beilagen gleichzeitig haben kann, würde ein
    Reroll EINER Beilage sonst versehentlich eine andere, an DEMSELBEN Tag
    bereits vorhandene Beilage duplizieren können - die Beilagen desselben
    Tages müssen also mit ausgeschlossen bleiben. Die gerade neu zu
    würfelnde Beilage selbst ist ohnehin bereits Teil dieser Menge (sie ist
    ja schon zugewiesen) - genau das verhindert automatisch, dass ein
    Reroll dasselbe Rezept erneut liefert, ganz ohne eigenen Sonderfall.
    """
    start = monday_of(day_date)
    dates = week_dates_for(start)
    rows = (
        db.session.query(PlanDaySide.recipe_id)
        .join(PlanDay, PlanDaySide.plan_day_id == PlanDay.id)
        .filter(PlanDay.date.in_(dates))
        .all()
    )
    return {rid for (rid,) in rows}


# --- KATEGORIE-BALANCE & REZEPT-AUSWAHL ---

def assign_balanced_categories(all_categories, days_to_fill, final_plan, preexisting_counts=None):
    """Weist jedem noch aufzufüllenden Tag (days_to_fill, eine Liste von
    Tag-Indizes 0-6 innerhalb EINER Woche) eine Kategorie zu - noch KEIN
    konkretes Rezept, nur die Kategorie, aus der später eines gewürfelt
    wird (siehe choose_recipe).

    Zwei Ziele werden gleichzeitig verfolgt, mit klarer Priorität:
    1. (höhere Priorität) Nach Möglichkeit nie dieselbe Kategorie wie der
       direkte Vorgänger- oder Nachfolgetag - damit z.B. nicht Montag UND
       Dienstag beide "Pasta" sind. Bereits fest zugewiesene Tage (die
       schon ein Rezept haben, in final_plan sichtbar) zählen dabei als
       bekannter Nachbar, auch wenn sie selbst nicht mehr neu zugewiesen
       werden.
    2. (niedrigere Priorität) Über alle 7 Tage der Woche hinweg möglichst
       gleichmäßige Verteilung der Kategorien (siehe counts/preexisting_counts).

    Ist Ziel 1 nicht erreichbar (z.B. weil insgesamt nur eine einzige
    Kategorie existiert), wird die Nachbarschaftsregel stillschweigend
    zugunsten von Ziel 2 aufgeweicht - es ist wichtiger, dass jeder Tag
    überhaupt eine Kategorie bekommt, als die Nachbarschaftsregel um jeden
    Preis durchzusetzen.

    Die Priorisierung wird über sort_key() umgesetzt: ein Tupel
    (ist_Nachbar_Kategorie, aktuelle_Anzahl). Da False < True in Python gilt,
    sortieren Nicht-Nachbar-Kategorien immer vor Nachbar-Kategorien, und
    innerhalb dieser beiden Gruppen gewinnt die bisher am seltensten
    verwendete Kategorie. min() über alle sort_key()-Werte findet dann den
    besten erreichbaren Kompromiss, random.choice() sorgt für Abwechslung
    bei mehreren gleich guten Kandidaten.

    Gibt ein Dict {Tag-Index: Kategorie-ID} zurück, eines pro Eintrag in
    days_to_fill.
    """
    cat_ids = [c.id for c in all_categories]
    if not cat_ids:
        return {}

    # Startbelegung der Zähler: bereits fest zugewiesene Tage fließen über
    # preexisting_counts in die Balance ein, damit sich die automatische
    # Auswahl NICHT nur an den eigenen 7 (oder weniger) neu vergebenen
    # Slots orientiert, sondern an der gesamten Woche.
    counts = Counter(preexisting_counts or {})
    for cid in cat_ids:
        counts.setdefault(cid, 0)

    # Bekannte Nachbarn zu Beginn: alle Tage, die schon ein fest zugewiesenes
    # Rezept haben (final_plan[i] ist bereits gesetzt). Wird im Lauf der
    # Schleife um jeden frisch zugewiesenen Tag erweitert, damit z.B. bei
    # zwei aufeinanderfolgenden freien Tagen auch der erste als Nachbar des
    # zweiten erkannt wird.
    known_category_by_day = {
        i: final_plan[i].category_id for i in range(7) if final_plan[i] is not None
    }

    assigned = {}
    for day_index in days_to_fill:
        # Kategorien der direkten Nachbartage (Vortag/Folgetag), soweit
        # bereits bekannt. Tage außerhalb 0-6 (gäbe es nicht) werden über
        # die Bereichsprüfung ignoriert.
        neighbor_cats = {
            known_category_by_day[n] for n in (day_index - 1, day_index + 1)
            if 0 <= n <= 6 and n in known_category_by_day
        }

        def sort_key(cid):
            return (cid in neighbor_cats, counts[cid])

        best_key = min(sort_key(cid) for cid in cat_ids)
        candidates = [cid for cid in cat_ids if sort_key(cid) == best_key]
        choice = random.choice(candidates)

        assigned[day_index] = choice
        counts[choice] += 1
        # Direkt merken, damit der NÄCHSTE Tag in dieser Schleife diesen
        # hier bereits als bekannten Nachbarn berücksichtigt.
        known_category_by_day[day_index] = choice

    return assigned


def choose_recipe(is_side_dish, exclude_ids, category_id=None, prefer_season=True, reference_date=None):
    """Die zentrale Rezept-Auswahlfunktion: wählt EIN passendes, noch nicht
    verwendetes Rezept aus der Datenbank aus. Wird sowohl beim Erstellen
    einer kompletten Woche als auch bei jedem Einzel-Reroll aufgerufen.

    Filterreihenfolge:
    1. is_side_dish trennt strikt zwischen Hauptgericht- und Beilagen-Pool -
       diese beiden werden nie vermischt.
    2. exclude_ids schließt Rezepte aus, die (je nach Aufrufer) bereits in
       derselben Woche verwendet werden oder das aktuell an diesem Tag
       stehende Rezept sind (verhindert Dubletten bzw. ein "Reroll" auf
       dasselbe Ergebnis). Das ist die einzige HARTE Ausschluss-Regel hier -
       alles Weitere unten ist weiche Gewichtung, kein weiterer Ausschluss.
    3. category_id (optional) schränkt zusätzlich auf eine bestimmte
       Kategorie ein - wird beim automatischen Auffüllen genutzt, um die
       von assign_balanced_categories() bestimmte Kategorie auch wirklich
       zu treffen. Bleibt sie leer (None), kommt jede Kategorie infrage
       (Fallback, wenn die gewünschte Kategorie keine Kandidaten mehr hat).

    Gibt es nach diesen drei Filtern keinen einzigen Kandidaten, wird sofort
    None zurückgegeben (kein weiterer Fallback hier - das übernehmen die
    Aufrufer, z.B. durch einen zweiten choose_recipe()-Aufruf ohne
    category_id).

    Danach kommt die Saison-Bevorzugung (prefer_season, Standard: an): aus
    den verbleibenden Kandidaten wird zuerst versucht, nur unter den GERADE
    jahreszeitlich verfügbaren (recipe_available_now()) zu würfeln. Gibt es
    davon mindestens einen, wird NUR aus dieser Teilmenge gewählt; gibt es
    keinen einzigen (z.B. weil in dieser Kategorie ausschließlich
    Winter-Rezepte existieren und gerade Sommer ist), wird stillschweigend
    auf ALLE Kandidaten ausgewichen - eine Saison-Zuordnung darf die
    automatische Auswahl also nie komplett blockieren.

    reference_date (der Tag, für den gerade gewürfelt wird) steuert die
    weiche Wiederholungs-Gewichtung: recent_usage_counts() zählt, wie oft
    jeder verbliebene Kandidat in den letzten REPETITION_LOOKBACK_WEEKS
    Wochen VOR diesem Tag bereits verwendet wurde, und weighted_recipe_choice()
    reduziert deren Ziehungswahrscheinlichkeit entsprechend (nie auf 0 - siehe
    dort). Bleibt reference_date leer (None), findet keine Wiederholungs-
    Gewichtung statt (nur Favoriten zählen dann wie zuvor) - kommt in der
    aktuellen App nicht vor, alle Aufrufer übergeben den Tag, ist aber ein
    harmloser Fallback für z.B. zukünftige Aufrufe außerhalb eines
    Kalendertag-Kontexts.

    In beiden Fällen entscheidet letztlich weighted_recipe_choice() (nicht
    ein einfaches random.choice()), sodass Favoriten und selten verwendete
    Rezepte unter den verbliebenen Kandidaten bevorzugt gezogen werden.
    """
    base_query = Recipe.query.filter(
        Recipe.is_side_dish.is_(is_side_dish),
        ~Recipe.id.in_(exclude_ids)
    )
    if category_id is not None:
        base_query = base_query.filter(Recipe.category_id == category_id)

    candidates = base_query.all()
    if not candidates:
        return None

    usage_counts = {}
    if reference_date is not None:
        usage_counts = recent_usage_counts([r.id for r in candidates], reference_date, is_side_dish)

    if prefer_season:
        seasonal_candidates = [r for r in candidates if recipe_available_now(r)]
        if seasonal_candidates:
            return weighted_recipe_choice(seasonal_candidates, usage_counts)

    return weighted_recipe_choice(candidates, usage_counts)


def jsonify_recipe(recipe):
    """Serialisiert ein Recipe-ORM-Objekt in ein einfaches Dict, das sich
    sowohl direkt als Flask-JSON-Response zurückgeben lässt (Flask
    konvertiert ein zurückgegebenes Dict automatisch zu einer
    JSON-Response) als auch über den Jinja-Filter `tojson` in
    templates/plan.html in das window.PLAN_DATA-JavaScript-Objekt
    eingebettet werden kann.

    Zutatennamen werden dabei mit .strip().title() normalisiert (führende/
    nachgestellte Leerzeichen entfernt, erster Buchstabe jedes Worts groß),
    damit z.B. "  nudeln" und "Nudeln" in der clientseitig konsolidierten
    Einkaufsliste (siehe static/plan-shopping.js: rebuildShoppingList) als derselbe
    Eintrag erkannt werden, auch wenn sie bei verschiedenen Rezepten leicht
    unterschiedlich eingetragen wurden. Die Einkaufslisten-Kategorie jeder
    Zutat (siehe services/shopping.py) wird unverändert mitgegeben - sie
    bestimmt dort, in welcher Gruppe/Reihenfolge die Zutat einsortiert wird.
    """
    return {
        "id": recipe.id,
        "name": recipe.name,
        "category_name": recipe.category.name,
        "category_id": recipe.category_id,
        "servings": recipe.servings,
        "calories": recipe.calories,
        "protein": recipe.protein,
        "carbs": recipe.carbs,
        "fat": recipe.fat,
        "ingredients": [
            {"name": ing.name.strip().title(), "amount": ing.amount, "unit": ing.unit, "category": ing.category}
            for ing in recipe.ingredients
        ]
    }


def jsonify_side(plan_day_side):
    """Wie jsonify_recipe(), aber für eine PlanDaySide-Zeile: hängt an das
    serialisierte Rezept-Dict zusätzlich side_id an - die ID der
    PlanDaySide-Zeile selbst, NICHT des Rezepts. static/plan-sides.js
    braucht diese ID, um genau DIESEN Beilagen-Slot gezielt neu zu
    würfeln, manuell zu ersetzen, zu entfernen oder auf einen anderen Tag
    zu verschieben, unabhängig davon, ob dasselbe Rezept vielleicht noch
    als Beilage an einem anderen Tag steht."""
    data = jsonify_recipe(plan_day_side.recipe)
    data['side_id'] = plan_day_side.id
    return data
