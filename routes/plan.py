"""Der Wochenplan-Kalender: Anzeige, Erstellen und alle Live-Interaktionen
(würfeln, manuell auswählen, tauschen, Beilagen hinzufügen/entfernen/
verschieben, Personenzahl ändern) mit dem dauerhaft in PlanDay/PlanDaySide
gespeicherten Plan.

Drei Arten von Routen leben hier nebeneinander:

- Seiten-Routen (/, /plan/<start_date>, /plan/<start_date>/create,
  /plan/<start_date>/generate): liefern ganze HTML-Seiten bzw. leiten
  weiter. Arbeiten mit "Wochenstart-Datum" (immer ein Montag) und einem
  Tag-Index 0-6 innerhalb dieser Woche.

- Tages-Aktionen (/day/<day_date>/...): AJAX-Endpunkte, die vom
  clientseitigen static/plan.js aufgerufen werden und JSON zurückgeben.
  Arbeiten direkt mit dem konkreten Kalendertag (day_date), nicht mit
  Wochenstart+Index - das macht sie unabhängig davon, in welcher
  Wochenansicht der Nutzer sie gerade auslöst, und lässt z.B. die
  Nachbarschafts-Kategorie-Regel beim Reroll sogar über Wochengrenzen
  hinweg funktionieren (siehe reroll_day). Die Beilagen-Aktionen darunter
  (/day/<day_date>/side/...) sind zusätzlich POSTEN-bezogen (ein Tag kann
  mehrere Beilagen haben, siehe models.py: PlanDaySide) - alle bis auf
  "add" adressieren daher eine konkrete PlanDaySide-Zeile per <int:side_id>.

- Einkaufslisten-Aktionen (/plan/<start_date>/shopping-item/add,
  /shopping-item/<id>/delete): AJAX-Endpunkte für manuell zur Einkaufsliste
  hinzugefügte Posten (ExtraShoppingItem), die zu keinem Rezept gehören.
  Anlegen ist wochenbezogen (start_date), Löschen dagegen postenbezogen
  (die id reicht, ohne Wochenbezug) - siehe add_shopping_item/
  delete_shopping_item ganz unten.
"""

from collections import Counter
from datetime import date, timedelta

from flask import Blueprint, render_template, request, redirect, url_for, abort

from models import db, Category, Recipe, PlanDay, PlanDaySide, ExtraShoppingItem
from services.planning import (
    DAY_NAMES_DE, monday_of, week_dates_for, parse_iso_date, week_neighbor_exclude_ids,
    week_side_recipe_ids, assign_balanced_categories, choose_recipe, jsonify_recipe
)


def jsonify_side(plan_day_side):
    """Wie jsonify_recipe(), aber für eine PlanDaySide-Zeile: hängt an das
    serialisierte Rezept-Dict zusätzlich side_id an - die ID der
    PlanDaySide-Zeile selbst, NICHT des Rezepts. static/plan.js braucht
    diese ID, um genau DIESEN Beilagen-Slot gezielt neu zu würfeln, manuell
    zu ersetzen, zu entfernen oder auf einen anderen Tag zu verschieben,
    unabhängig davon, ob dasselbe Rezept vielleicht noch als Beilage an
    einem anderen Tag steht."""
    data = jsonify_recipe(plan_day_side.recipe)
    data['side_id'] = plan_day_side.id
    return data

plan_bp = Blueprint('plan', __name__)


@plan_bp.route('/')
def index():
    """Die Startseite der App: leitet immer sofort auf die Wochenansicht
    der AKTUELLEN Kalenderwoche weiter (/plan/<Montag von heute>). Es gibt
    keine eigenständige "/"-Seite mehr - das war früher (vor Einführung des
    dauerhaften Kalenders) die Tageszuweisungs-Seite, die jetzt unter
    /plan/<start_date>/create liegt und nur noch über den
    "Neuen Wochenplan erstellen"-Button erreichbar ist."""
    start = monday_of(date.today())
    return redirect(url_for('plan.week_view', start_date=start.isoformat()))


@plan_bp.route('/plan/<start_date>')
def week_view(start_date):
    """Zeigt den Wochenplan für die Kalenderwoche, die start_date enthält.

    start_date kommt als beliebiger ISO-Datumsstring aus der URL (z.B. von
    einem Link auf einen bestimmten Tag oder dem Datums-Sprung-Feld) und
    muss nicht zwingend ein Montag sein: normalized = monday_of(start)
    rechnet ihn auf den Wochenanfang um, und liegt das ursprüngliche Datum
    nicht bereits darauf, wird auf die normalisierte, "kanonische" URL
    weitergeleitet (z.B. /plan/2026-06-17 (Mittwoch) -> /plan/2026-06-15
    (Montag derselben Woche)) - so hat jede Woche immer genau eine gültige
    URL, egal über welches Datum man sie erreicht.

    Lädt dann für alle 7 Tage dieser Woche die zugehörigen PlanDay-Zeilen
    (falls vorhanden - ordered enthält an der jeweiligen Position None,
    wenn für diesen Tag noch nichts geplant wurde) und leitet daraus vier
    parallele, nach Tag-Index (0=Montag...6=Sonntag) sortierte Listen ab:
    plan (Hauptgerichte), side_plan (je Tag eine LISTE von Beilagen, siehe
    models.py: PlanDay.sides - ein Tag kann beliebig viele haben),
    excluded_days (welche Tag-Indizes als "ausgenommen" markiert sind) und
    servings_list (Personenzahl je Tag, Default 2 für noch ungeplante Tage).

    has_any_data unterscheidet "diese Woche wurde noch NIE erstellt"
    (any(ordered) ist False, alle 7 Einträge sind None) von "diese Woche
    existiert, aber einzelne Tage sind z.B. ausgenommen oder leer" - nur im
    ersten Fall zeigt plan.html den großen "Neuen Wochenplan
    erstellen"-Button statt der Tageskarten.

    plan_data bündelt alle für die clientseitigen Live-Interaktionen
    nötigen Daten (siehe static/plan.js) in einem einzigen, über den
    Jinja-Filter `tojson` sicher als JSON eingebetteten Objekt
    (window.PLAN_DATA) - dieselben Recipe-Objekte werden dafür über
    jsonify_recipe()/jsonify_side() in einfache Dicts umgewandelt, exakt
    dieselben Hilfsfunktionen, die auch die /day/...-AJAX-Endpunkte weiter
    unten für ihre Antworten verwenden, damit das Datenformat konsistent
    bleibt. allRecipes enthält zusätzlich ALLE Rezepte (unabhängig vom
    aktuellen Plan) in einer schlanken Form - Grundlage für die manuelle
    Rezeptauswahl (Such-/Auswahlbox, siehe static/plan.js:
    openMainManualSelect/openSideManualSelect).
    """
    start = parse_iso_date(start_date)
    if start is None:
        abort(404)
    normalized = monday_of(start)
    if normalized != start:
        return redirect(url_for('plan.week_view', start_date=normalized.isoformat()))

    dates = week_dates_for(normalized)
    plan_days_by_date = {pd.date: pd for pd in PlanDay.query.filter(PlanDay.date.in_(dates)).all()}
    ordered = [plan_days_by_date.get(d) for d in dates]
    has_any_data = any(ordered)

    plan = [pd.main_recipe if pd else None for pd in ordered]
    side_plan = [pd.sides if pd else [] for pd in ordered]
    excluded_days = {i for i, pd in enumerate(ordered) if pd and pd.excluded}
    servings_list = [pd.servings if pd else 2 for pd in ordered]

    today = date.today()
    # Fertig formatierte Wochentag+Datum-Labels ("Montag, 15.09. (Heute)"),
    # die static/plan.js beim Neu-Rendern einer Tageskarte nach einem
    # Tage-Tausch braucht, ohne selbst Wochentagsnamen kennen zu müssen.
    day_labels = [
        f"{DAY_NAMES_DE[i]}, {dates[i].strftime('%d.%m.')}" + (' (Heute)' if dates[i] == today else '')
        for i in range(7)
    ]
    # Manuell hinzugefügte Einkaufslisten-Posten dieser Woche (siehe
    # add_shopping_item unten) - lose über week_start an die Woche gebunden,
    # kein Fremdschlüssel auf PlanDay o.ä. nötig.
    extra_items = ExtraShoppingItem.query.filter_by(week_start=normalized).order_by(ExtraShoppingItem.id).all()

    all_recipes = Recipe.query.all()

    plan_data = {
        'weekDates': [d.isoformat() for d in dates],
        'dayLabels': day_labels,
        'excludedDays': [i in excluded_days for i in range(7)],
        'servingsList': servings_list,
        'plan': [jsonify_recipe(r) if r else None for r in plan],
        'sidePlan': [[jsonify_side(s) for s in sides] for sides in side_plan],
        'extraItems': [
            {"id": it.id, "name": it.name, "amount": it.amount, "unit": it.unit, "category": it.category}
            for it in extra_items
        ],
        'allRecipes': [
            {"id": r.id, "name": r.name, "category_name": r.category.name, "is_side_dish": r.is_side_dish}
            for r in all_recipes
        ],
    }

    # plan/side_plan/excluded_days/servings_list/days werden NICHT mehr an
    # das Template gereicht: die Tageskarten werden komplett clientseitig
    # aus plan_data aufgebaut (siehe templates/plan.html - der Kommentar
    # dort erklärt, warum). Das Template braucht für die Kartenhülle nur
    # noch week_dates/today (für data-date und die "Heute"-Markierung) und
    # has_any_data.
    return render_template(
        'plan.html',
        week_dates=dates, start_date=normalized, has_any_data=has_any_data,
        prev_start=(normalized - timedelta(days=7)).isoformat(),
        next_start=(normalized + timedelta(days=7)).isoformat(),
        today=today, plan_data=plan_data,
    )


@plan_bp.route('/plan/<start_date>/create')
def week_create_view(start_date):
    """Zeigt das Formular zum (Neu-)Erstellen einer ganzen Woche
    (templates/create_week.html): Live-Suche + Drag-and-Drop, um einzelne
    Tage fest mit einem Haupt-/Zusatzgericht zu belegen oder ganz
    auszunehmen, bevor der Rest automatisch aufgefüllt wird.

    Wird nur über den "Neuen Wochenplan erstellen"-Button (bzw. "Woche neu
    erstellen" bei einer bereits geplanten Woche) von der Wochenansicht aus
    erreicht - anders als früher ist das keine eigenständige Hauptseite
    mehr. start_date wird wie bei week_view() auf den Wochenmontag
    normalisiert, aber (anders als dort) ohne Redirect bei Abweichung -
    diese Seite wird immer über einen bereits korrekten Link erreicht,
    ein Redirect würde hier nur unnötig eine zusätzliche Anfrage kosten.
    """
    start = parse_iso_date(start_date)
    if start is None:
        abort(404)
    start = monday_of(start)

    recipes = Recipe.query.all()
    categories = Category.query.all()

    return render_template(
        'create_week.html', recipes=recipes, categories=categories,
        week_dates=week_dates_for(start), start_date=start, days=DAY_NAMES_DE
    )


@plan_bp.route('/plan/<start_date>/generate', methods=['POST'])
def week_generate(start_date):
    """Verarbeitet das Formular von week_create_view(): übernimmt die vom
    Nutzer fest zugewiesenen Tage unverändert, würfelt die restlichen
    Hauptgerichte balanciert dazu und schreibt das Ergebnis dauerhaft als
    PlanDay-Zeilen in die Datenbank.

    Ablauf in sechs Schritten (im Code nummeriert):

    1. Formular auslesen: für jeden der 7 Tage (Index 0=Montag...6=Sonntag,
       NICHT dasselbe wie ein Kalenderdatum - das Formular kennt nur die
       Position innerhalb der Woche) wird geprüft, ob er als "ausgenommen"
       markiert ist (day_excluded_i), sonst ob ihm eine Rezept-ID fest
       zugewiesen wurde (day_recipe_i). Die Beilagen-IDs
       (day_side_recipes_i[], eine LISTE - ein Tag kann beliebig viele
       Beilagen bekommen) werden IMMER gelesen, unabhängig vom
       Ausnahme-Status - ein ausgenommener Tag (kein Hauptgericht) darf
       trotzdem feste Beilagen haben.

    2./2b. Die im Formular referenzierten Rezept-IDs werden in EINER
       Datenbankabfrage pro Liste (statt einer Abfrage pro Tag) nachgeladen
       und in final_plan (eine Liste mit 7 Einträgen, None = noch nichts
       zugewiesen) bzw. final_side_plan (eine Liste mit 7 LISTEN von
       Rezepten) eingetragen. used_recipe_ids sammelt dabei alle bereits
       fest verwendeten HAUPTGERICHT-IDs, damit sie beim automatischen
       Auffüllen in Schritt 5 nicht doppelt vergeben werden. Beilagen werden
       bewusst NIE automatisch gewürfelt - nur fest zugewiesene Beilagen
       landen beim Erstellen im Plan; alles Weitere läuft über die
       🎲/✏️-Buttons auf der fertigen Plan-Seite (siehe add_side/
       reroll_one_side/set_one_side weiter unten).

    3. days_to_fill: die Tag-Indizes, die weder ausgenommen noch bereits
       fest belegt sind - genau die, die die folgenden zwei Schritte noch
       befüllen müssen.

    4. Für jeden dieser Tage wird per assign_balanced_categories() eine
       KATEGORIE bestimmt (noch kein Rezept) - siehe services/planning.py
       für die Balance-/Nachbarschaftslogik. Bereits fest zugewiesene Tage
       fließen dabei als "Vorbelastung" (preexisting_counts) mit ein, damit
       die Kategorie-Verteilung über die GESAMTE Woche ausgeglichen bleibt,
       nicht nur über die neu aufzufüllenden Tage.

    5. Für jeden Tag wird dann ein konkretes Rezept aus der zugewiesenen
       Kategorie gewürfelt (choose_recipe); hat diese Kategorie keine
       passenden Kandidaten mehr übrig, wird kategorie-unabhängig
       nachgewürfelt, damit lieber IRGENDEIN Rezept als gar keines im Plan
       landet.

    6. Erst jetzt wird persistiert: für jeden der 7 Kalendertage dieser
       Woche wird die passende PlanDay-Zeile geholt oder neu angelegt
       (get-or-create) und mit dem Ergebnis überschrieben. Für die Beilagen
       werden dabei zuerst ALLE bestehenden PlanDaySide-Zeilen dieses Tages
       gelöscht und dann aus final_side_plan[i] neu angelegt - deutlich
       einfacher als ein Diff aus "geändert/neu/gelöscht", analog zum
       Zutaten-Ersetzen bei edit_recipe() in routes/recipes.py. Das deckt
       sowohl das erstmalige Erstellen einer Woche ab als auch ein erneutes
       "Woche neu erstellen" über eine bereits vorhandene Woche.
    """
    start = parse_iso_date(start_date)
    if start is None:
        abort(404)
    start = monday_of(start)
    dates = week_dates_for(start)

    all_categories = Category.query.all()

    # 1. Formulardaten pro Tag auslesen: feste Zuweisung + Ausnahme-Status
    excluded_days = set()
    day_recipe_ids = {}  # Tag-Index -> Hauptgericht-Rezept-ID (String)
    day_side_recipe_ids = {}  # Tag-Index -> Liste von Zusatzgericht-Rezept-IDs (Strings)

    for i in range(7):
        if request.form.get(f'day_excluded_{i}') == '1':
            excluded_days.add(i)
        else:
            rid = (request.form.get(f'day_recipe_{i}') or '').strip()
            if rid:
                day_recipe_ids[i] = rid

        # dict.fromkeys() statt set(): entfernt Duplikate (z.B. durch
        # doppeltes Klicken im Formular), erhält dabei aber die
        # Reihenfolge, in der die Beilagen zugewiesen wurden.
        side_rids = [rid.strip() for rid in request.form.getlist(f'day_side_recipes_{i}[]') if rid.strip()]
        if side_rids:
            day_side_recipe_ids[i] = list(dict.fromkeys(side_rids))

    # 2. Feste Hauptgerichte anhand ihrer ID nachladen
    final_plan = [None] * 7
    used_recipe_ids = set()

    if day_recipe_ids:
        unique_ids = list(set(day_recipe_ids.values()))
        recipes_by_id = {str(r.id): r for r in Recipe.query.filter(Recipe.id.in_(unique_ids)).all()}
        for day_index, rid in day_recipe_ids.items():
            recipe = recipes_by_id.get(rid)
            if recipe:
                final_plan[day_index] = recipe
                used_recipe_ids.add(recipe.id)

    # 2b. Feste Zusatzgerichte (Beilagen) anhand ihrer IDs nachladen - je
    # Tag jetzt eine LISTE von Rezepten statt höchstens einem einzelnen.
    final_side_plan = [[] for _ in range(7)]

    if day_side_recipe_ids:
        unique_side_ids = list({rid for rids in day_side_recipe_ids.values() for rid in rids})
        side_recipes_by_id = {
            str(r.id): r for r in Recipe.query.filter(Recipe.id.in_(unique_side_ids)).all()
        }
        for day_index, rids in day_side_recipe_ids.items():
            for rid in rids:
                recipe = side_recipes_by_id.get(rid)
                if recipe:
                    final_side_plan[day_index].append(recipe)

    # 3. Welche Tage müssen noch automatisch aufgefüllt werden?
    days_to_fill = [i for i in range(7) if i not in excluded_days and final_plan[i] is None]

    # 4. Kategorie je aufzufüllendem Tag bestimmen (siehe Docstring oben)
    preexisting_counts = Counter(
        final_plan[day_index].category_id
        for day_index in day_recipe_ids
        if final_plan[day_index] is not None
    )
    category_by_day = assign_balanced_categories(
        all_categories, days_to_fill, final_plan, preexisting_counts=preexisting_counts
    )

    # 5. Restliche Tage mit passenden, noch nicht verwendeten Hauptgerichten
    # auffüllen. reference_date=dates[day_index] aktiviert die weiche
    # Wiederholungs-Gewichtung in choose_recipe() (siehe services/planning.py) -
    # Rezepte, die in den letzten Wochen VOR genau diesem Kalendertag bereits
    # oft dran waren, werden dadurch seltener (aber nie unmöglich) gezogen.
    for day_index, needed_cat_id in category_by_day.items():
        chosen = choose_recipe(
            is_side_dish=False, exclude_ids=used_recipe_ids, category_id=needed_cat_id,
            reference_date=dates[day_index]
        )
        if not chosen:
            chosen = choose_recipe(is_side_dish=False, exclude_ids=used_recipe_ids, reference_date=dates[day_index])

        if chosen:
            final_plan[day_index] = chosen
            used_recipe_ids.add(chosen.id)

    # 6. Dauerhaft speichern: ein PlanDay pro echtem Kalendertag dieser Woche
    for i in range(7):
        day_date = dates[i]
        plan_day = PlanDay.query.filter_by(date=day_date).first()
        if not plan_day:
            plan_day = PlanDay(date=day_date, servings=2)
            db.session.add(plan_day)
            db.session.flush()  # weist plan_day.id zu, für die PlanDaySide-Zeilen unten
        plan_day.excluded = i in excluded_days
        plan_day.main_recipe_id = final_plan[i].id if final_plan[i] else None

        PlanDaySide.query.filter_by(plan_day_id=plan_day.id).delete()
        for side_recipe in final_side_plan[i]:
            db.session.add(PlanDaySide(plan_day_id=plan_day.id, recipe_id=side_recipe.id))

    db.session.commit()
    return redirect(url_for('plan.week_view', start_date=start.isoformat()))


@plan_bp.route('/day/<day_date>/reroll-main', methods=['POST'])
def reroll_day(day_date):
    """AJAX-Endpunkt hinter dem 🎲-Button eines Hauptgerichts auf der
    fertigen Plan-Seite: würfelt für GENAU DIESEN Kalendertag ein neues,
    anderes Hauptgericht und persistiert es sofort.

    Ein Reroll ist nur für Tage möglich, die bereits Teil eines erstellten
    Plans sind UND nicht als "ausgenommen" markiert wurden (ein
    ausgenommener Tag hat bewusst kein Hauptgericht - dort gibt es nichts
    neu zu würfeln).

    Die Auswahllogik entspricht im Kern der aus week_generate() (Schritt 4+5
    dort), aber für einen einzelnen Tag statt eine ganze Woche auf einmal:

    - exclude_ids startet mit den Hauptgerichten aller ANDEREN Tage
      derselben Woche (week_neighbor_exclude_ids) und wird um das
      AKTUELLE Rezept dieses Tages erweitert - so kann ein Reroll niemals
      dasselbe Rezept erneut liefern, das gerade schon da steht, und auch
      kein Rezept, das diese Woche schon woanders verwendet wird.

    - Die Kategorien-Zählung (other_cat_counts) wird aus genau diesen
      ausgeschlossenen Rezepten abgeleitet, um dieselbe
      Balance-Vorstellung wie beim Erstellen zu erhalten.

    - Die direkten Nachbartage (Vortag/Folgetag, über echte
      timedelta(days=1)-Arithmetik ermittelt) werden bei der
      Kategorie-Sortierung nachrangig behandelt, damit ein Reroll nicht
      zwei aufeinanderfolgende Tage in dieselbe Kategorie bringt. Weil
      hier mit echten Kalendertagen statt einem Wochen-internen Index
      gearbeitet wird, funktioniert das sogar über Wochengrenzen hinweg
      (z.B. wird beim Reroll eines Sonntags auch der Montag der
      FOLGENDEN, bereits existierenden Woche als Nachbar berücksichtigt).

    Wird zuerst versucht, eine der (nach Nachbarschaft/Balance sortierten)
    Kategorien zu treffen; schlägt das komplett fehl, kommt als letzter
    Fallback ein kategorie-unabhängiger Versuch. Liefert am Ende gar keiner
    ein Ergebnis (z.B. weil buchstäblich kein Hauptgericht mehr übrig ist),
    wird ein Fehler zurückgegeben statt den Tag stillschweigend leer zu
    lassen.

    reference_date=target_date wird an choose_recipe() durchgereicht und
    aktiviert dort die weiche Wiederholungs-Gewichtung (siehe
    services/planning.py: recent_usage_counts/weighted_recipe_choice) -
    unter den nach obiger Logik verbliebenen Kandidaten werden zuletzt/
    häufig verwendete Rezepte seltener (aber nie unmöglich) gewürfelt.
    """
    target_date = parse_iso_date(day_date)
    if target_date is None:
        return {"error": "Ungültiges Datum"}, 400

    plan_day = PlanDay.query.filter_by(date=target_date).first()
    if not plan_day or plan_day.excluded:
        return {"error": "Dieser Tag ist nicht Teil eines Plans oder von der Hauptgericht-Planung ausgenommen."}, 400

    exclude_ids = week_neighbor_exclude_ids(target_date)
    if plan_day.main_recipe_id:
        exclude_ids.add(plan_day.main_recipe_id)

    all_categories = Category.query.all()
    all_cat_ids = [c.id for c in all_categories]

    other_recipes = Recipe.query.filter(Recipe.id.in_(exclude_ids)).all()
    other_cat_counts = {cid: 0 for cid in all_cat_ids}
    for r in other_recipes:
        other_cat_counts[r.category_id] = other_cat_counts.get(r.category_id, 0) + 1

    neighbor_ids = []
    for neighbor_date in (target_date - timedelta(days=1), target_date + timedelta(days=1)):
        neighbor_day = PlanDay.query.filter_by(date=neighbor_date).first()
        if neighbor_day and neighbor_day.main_recipe_id:
            neighbor_ids.append(neighbor_day.main_recipe_id)
    neighbor_categories = {r.category_id for r in Recipe.query.filter(Recipe.id.in_(neighbor_ids)).all()}

    # Sortierschlüssel wie in assign_balanced_categories(): erst
    # Nicht-Nachbar-Kategorien (False < True), dann die bislang seltenste.
    sorted_target_categories = sorted(
        all_cat_ids, key=lambda cid: (cid in neighbor_categories, other_cat_counts[cid])
    )

    chosen = None
    for best_cat_id in sorted_target_categories:
        chosen = choose_recipe(
            is_side_dish=False, exclude_ids=exclude_ids, category_id=best_cat_id, reference_date=target_date
        )
        if chosen:
            break
    if not chosen:
        chosen = choose_recipe(is_side_dish=False, exclude_ids=exclude_ids, reference_date=target_date)

    if not chosen:
        return {"error": "Keine weiteren Rezepte in der Datenbank verfügbar!"}, 400

    plan_day.main_recipe_id = chosen.id
    db.session.commit()
    return jsonify_recipe(chosen)


@plan_bp.route('/day/<day_date>/set-main', methods=['POST'])
def set_main_day(day_date):
    """AJAX-Endpunkt hinter dem ✏️-Button eines Hauptgerichts: setzt für
    GENAU DIESEN Kalendertag ein vom Nutzer explizit ausgewähltes
    Hauptgericht (statt eines zufällig gewürfelten, siehe reroll_day oben).

    Bewusst OHNE jede der in reroll_day() beschriebenen Automatik-Regeln
    (Kategorie-Balance, Nachbarschaft, Wiederholungs-Gewichtung, Wochen-
    Dubletten-Ausschluss) - eine manuelle Auswahl ist ein expliziter
    Nutzerwunsch und soll nie durch eine automatische Regel blockiert
    werden, genau wie die manuelle Zuweisung auf der Erstellen-Seite
    (week_generate) auch keiner dieser Regeln unterliegt.

    Setzt außerdem excluded auf False: ein Tag, dem gerade explizit ein
    Hauptgericht zugewiesen wird, kann per Definition nicht mehr
    "von der Hauptgericht-Planung ausgenommen" sein (siehe models.py:
    PlanDay) - so lässt sich ein ausgenommener Tag über den ✏️-Button auch
    wieder in die Planung zurückholen, ohne einen Umweg über die
    Erstellen-Seite.
    """
    target_date = parse_iso_date(day_date)
    if target_date is None:
        return {"error": "Ungültiges Datum"}, 400

    data = request.get_json() or {}
    try:
        recipe_id = int(data.get('recipe_id'))
    except (TypeError, ValueError):
        return {"error": "Ungültiges Rezept"}, 400

    recipe = Recipe.query.filter_by(id=recipe_id, is_side_dish=False).first()
    if not recipe:
        return {"error": "Rezept nicht gefunden."}, 400

    plan_day = PlanDay.query.filter_by(date=target_date).first()
    if not plan_day:
        plan_day = PlanDay(date=target_date, servings=2)
        db.session.add(plan_day)

    plan_day.excluded = False
    plan_day.main_recipe_id = recipe.id
    db.session.commit()
    return jsonify_recipe(recipe)


def _get_or_create_plan_day(target_date):
    """Get-or-create-Hilfsfunktion, die in mehreren der Beilagen-Endpunkte
    unten identisch gebraucht wird (add_side/reroll_one_side/set_one_side/
    move_one_side legen alle bei Bedarf eine neue, leere PlanDay-Zeile an,
    falls für target_date noch keine existiert - z.B. wenn eine Beilage auf
    einen Tag verschoben wird, der bislang noch gar nicht Teil der Woche
    war). db.session.flush() stellt sicher, dass eine neu angelegte Zeile
    sofort eine echte id hat, bevor der Aufrufer eine PlanDaySide darauf
    verweisen lässt."""
    plan_day = PlanDay.query.filter_by(date=target_date).first()
    if not plan_day:
        plan_day = PlanDay(date=target_date, servings=2)
        db.session.add(plan_day)
        db.session.flush()
    return plan_day


@plan_bp.route('/day/<day_date>/side/add', methods=['POST'])
def add_side(day_date):
    """AJAX-Endpunkt hinter den Beilagen-"Hinzufügen"-Buttons am Ende der
    Beilagen-Liste einer Tageskarte: legt eine NEUE Beilage für diesen Tag
    an, zusätzlich zu bereits vorhandenen (ein Tag kann beliebig viele
    haben, siehe models.py: PlanDaySide).

    Erwartet einen JSON-Body {"recipe_id": <id> oder null}:
    - Ist recipe_id gesetzt (🥗-Auswahl-Button in static/plan.js:
      openSideManualSelect), wird GENAU dieses vom Nutzer gewählte Rezept
      übernommen - ohne jede Zufalls-/Ausschluss-Logik, analog zu
      set_main_day() oben.
    - Ist recipe_id leer/null (🎲-Button), wird stattdessen zufällig
      gewürfelt: choose_recipe() mit week_side_recipe_ids() als
      Ausschluss-Menge (verhindert Dubletten sowohl mit anderen Tagen als
      auch mit bereits an DIESEM Tag vorhandenen Beilagen) und der weichen
      Wiederholungs-Gewichtung (reference_date).
    """
    target_date = parse_iso_date(day_date)
    if target_date is None:
        return {"error": "Ungültiges Datum"}, 400

    data = request.get_json() or {}
    raw_recipe_id = data.get('recipe_id')

    plan_day = _get_or_create_plan_day(target_date)

    if raw_recipe_id:
        try:
            recipe_id = int(raw_recipe_id)
        except (TypeError, ValueError):
            return {"error": "Ungültiges Rezept"}, 400
        chosen = Recipe.query.filter_by(id=recipe_id, is_side_dish=True).first()
        if not chosen:
            return {"error": "Rezept nicht gefunden."}, 400
    else:
        exclude_ids = week_side_recipe_ids(target_date)
        chosen = choose_recipe(is_side_dish=True, exclude_ids=exclude_ids, reference_date=target_date)
        if not chosen:
            return {"error": "Keine weiteren Beilagen in der Datenbank verfügbar!"}, 400

    plan_day_side = PlanDaySide(plan_day_id=plan_day.id, recipe_id=chosen.id)
    db.session.add(plan_day_side)
    db.session.commit()
    return jsonify_side(plan_day_side)


@plan_bp.route('/day/<day_date>/side/<int:side_id>/reroll', methods=['POST'])
def reroll_one_side(day_date, side_id):
    """AJAX-Endpunkt hinter dem 🎲-Button EINER bestimmten Beilage: ersetzt
    genau diesen Beilagen-Slot durch ein neu gewürfeltes, anderes Rezept
    (im Gegensatz zu add_side oben, das einen ZUSÄTZLICHEN Slot anlegt).

    Die PlanDaySide-Zeile wird dabei nicht gelöscht und neu angelegt,
    sondern ihre recipe_id direkt überschrieben - so bleibt ihre id (und
    damit z.B. eine gerade offene Referenz im Frontend) über den Reroll
    hinweg stabil.
    """
    target_date = parse_iso_date(day_date)
    if target_date is None:
        return {"error": "Ungültiges Datum"}, 400

    plan_day_side = PlanDaySide.query.join(PlanDay).filter(
        PlanDaySide.id == side_id, PlanDay.date == target_date
    ).first()
    if not plan_day_side:
        return {"error": "Diese Beilage gehört nicht zu diesem Tag."}, 404

    exclude_ids = week_side_recipe_ids(target_date)
    chosen = choose_recipe(is_side_dish=True, exclude_ids=exclude_ids, reference_date=target_date)
    if not chosen:
        return {"error": "Keine weiteren Beilagen in der Datenbank verfügbar!"}, 400

    plan_day_side.recipe_id = chosen.id
    db.session.commit()
    return jsonify_side(plan_day_side)


@plan_bp.route('/day/<day_date>/side/<int:side_id>/set', methods=['POST'])
def set_one_side(day_date, side_id):
    """AJAX-Endpunkt hinter dem ✏️-Button EINER bestimmten Beilage: ersetzt
    genau diesen Slot durch ein vom Nutzer explizit gewähltes Rezept (das
    manuelle Pendant zu reroll_one_side oben - ohne Zufall/Ausschluss-Logik,
    analog zu set_main_day)."""
    target_date = parse_iso_date(day_date)
    if target_date is None:
        return {"error": "Ungültiges Datum"}, 400

    plan_day_side = PlanDaySide.query.join(PlanDay).filter(
        PlanDaySide.id == side_id, PlanDay.date == target_date
    ).first()
    if not plan_day_side:
        return {"error": "Diese Beilage gehört nicht zu diesem Tag."}, 404

    data = request.get_json() or {}
    try:
        recipe_id = int(data.get('recipe_id'))
    except (TypeError, ValueError):
        return {"error": "Ungültiges Rezept"}, 400

    recipe = Recipe.query.filter_by(id=recipe_id, is_side_dish=True).first()
    if not recipe:
        return {"error": "Rezept nicht gefunden."}, 400

    plan_day_side.recipe_id = recipe.id
    db.session.commit()
    return jsonify_side(plan_day_side)


@plan_bp.route('/day/<day_date>/side/<int:side_id>/remove', methods=['POST'])
def remove_one_side(day_date, side_id):
    """AJAX-Endpunkt hinter dem ❌-Button EINER bestimmten Beilage: entfernt
    genau diesen Slot, ohne den Rest des Tages (Hauptgericht, andere
    Beilagen, Ausnahme-Status, Personenzahl) anzutasten. Gehört side_id
    nicht (mehr) zu diesem Tag, wird das still mit {"ok": True} quittiert
    statt eines Fehlers - das Endergebnis ("diese Beilage ist an diesem Tag
    nicht mehr vorhanden") ist in beiden Fällen identisch."""
    target_date = parse_iso_date(day_date)
    if target_date is None:
        return {"error": "Ungültiges Datum"}, 400

    plan_day_side = PlanDaySide.query.join(PlanDay).filter(
        PlanDaySide.id == side_id, PlanDay.date == target_date
    ).first()
    if plan_day_side:
        db.session.delete(plan_day_side)
        db.session.commit()
    return {"ok": True}


@plan_bp.route('/day/<day_date>/side/<int:side_id>/move/<target_date_str>', methods=['POST'])
def move_one_side(day_date, side_id, target_date_str):
    """AJAX-Endpunkt hinter dem Drag-and-Drop-Verschieben EINER einzelnen
    Beilage auf eine andere Tageskarte (siehe static/plan.js:
    moveSideDish): hängt die PlanDaySide-Zeile einfach an eine ANDERE
    PlanDay-Zeile um (plan_day_id ändern) - ein einseitiges Verschieben,
    kein Tausch. Im Gegensatz zum kompletten Tages-Tausch (swap_days unten,
    ausgelöst durch Ziehen der ganzen Tageskarte inkl. Hauptgericht) bleibt
    dabei alles andere an Quell- UND Zieltag komplett unangetastet.

    Existiert für den Zieltag noch keine PlanDay-Zeile (z.B. weil dort noch
    nie etwas geplant wurde), wird sie hier neu angelegt statt einen Fehler
    zu werfen - analog zu add_side/reroll_one_side.
    """
    source_date = parse_iso_date(day_date)
    target_date = parse_iso_date(target_date_str)
    if source_date is None or target_date is None:
        return {"error": "Ungültiges Datum"}, 400

    plan_day_side = PlanDaySide.query.join(PlanDay).filter(
        PlanDaySide.id == side_id, PlanDay.date == source_date
    ).first()
    if not plan_day_side:
        return {"error": "Diese Beilage gehört nicht zu diesem Tag."}, 404

    target_plan_day = _get_or_create_plan_day(target_date)
    plan_day_side.plan_day_id = target_plan_day.id
    db.session.commit()
    return jsonify_side(plan_day_side)


@plan_bp.route('/day/<day_date>/servings', methods=['POST'])
def set_day_servings(day_date):
    """AJAX-Endpunkt für das 👥-Personen-Eingabefeld einer Tageskarte:
    speichert die für diesen Kalendertag gewünschte Personenzahl dauerhaft.

    Wird vom Frontend "optimistisch" aufgerufen (die Einkaufsliste wird
    dort bereits vor der Serverantwort neu berechnet, siehe
    static/plan.js: updateDayServings) - dieser Endpunkt muss daher nur
    noch zuverlässig speichern, nicht mehr aktiv etwas zurückmelden, das
    die Oberfläche sofort bräuchte.

    Erwartet einen JSON-Body {"servings": <Zahl>}. Ungültige oder fehlende
    Werte fallen auf 2 zurück (statt einen Fehler zu liefern), negative
    oder Null-Werte werden auf mindestens 1 angehoben - eine Personenzahl
    von 0 oder weniger würde die Mengenskalierung der Einkaufsliste
    (Division durch die Zielpersonenzahl) unsinnig machen.
    """
    target_date = parse_iso_date(day_date)
    if target_date is None:
        return {"error": "Ungültiges Datum"}, 400

    data = request.get_json() or {}
    try:
        servings = max(1, int(data.get('servings', 2)))
    except (TypeError, ValueError):
        servings = 2

    plan_day = PlanDay.query.filter_by(date=target_date).first()
    if not plan_day:
        plan_day = PlanDay(date=target_date)
        db.session.add(plan_day)
    plan_day.servings = servings
    db.session.commit()
    return {"ok": True, "servings": servings}


@plan_bp.route('/day/<date_a>/swap/<date_b>', methods=['POST'])
def swap_days(date_a, date_b):
    """AJAX-Endpunkt hinter dem Drag-and-Drop-Tausch zweier ganzer
    Tageskarten auf der Plan-Seite (Ziehen der KARTE selbst, nicht einer
    einzelnen Beilage - für Letzteres siehe move_one_side oben): vertauscht
    Hauptgericht, ALLE Beilagen UND Ausnahme-Status zweier Kalendertage
    komplett miteinander. "Wird das Hauptgericht verschoben, kommen die
    Beilagen mit" - deshalb hängen hier an einem Tages-Tausch immer alle
    zugehörigen PlanDaySide-Zeilen mit dran, nicht nur main_recipe_id.

    Fehlt für einen der beiden Tage noch eine PlanDay-Zeile, wird sie mit
    leeren Werten neu angelegt, bevor getauscht wird - so funktioniert der
    Tausch auch dann, wenn z.B. ein Tag zwar zur bereits erstellten Woche
    gehört, aber (weil ausgenommen und ohne Beilagen) noch nie eine eigene
    Zeile bekommen hat. db.session.flush() stellt sicher, dass neu
    angelegte Zeilen sofort eine echte id haben, bevor die Beilagen-Zeilen
    unten darauf umgehängt werden.

    Die Beilagen werden dabei NICHT einzeln kopiert, sondern per
    plan_day_id einfach komplett auf die jeweils andere Seite umgehängt -
    effizienter als ein Item-für-Item-Tausch und mit identischem Ergebnis.

    Die Personenzahl (servings) wird bewusst NICHT mitgetauscht: sie gilt
    konzeptionell dem WOCHENTAG selbst ("am Freitag sind wir zu viert"),
    nicht dem Gericht, das gerade dort steht - ein Tausch der Gerichte soll
    diese Vorgabe daher unverändert lassen.
    """
    parsed_a = parse_iso_date(date_a)
    parsed_b = parse_iso_date(date_b)
    if parsed_a is None or parsed_b is None:
        return {"error": "Ungültiges Datum"}, 400

    plan_day_a = PlanDay.query.filter_by(date=parsed_a).first()
    plan_day_b = PlanDay.query.filter_by(date=parsed_b).first()
    if not plan_day_a:
        plan_day_a = PlanDay(date=parsed_a, servings=2)
        db.session.add(plan_day_a)
    if not plan_day_b:
        plan_day_b = PlanDay(date=parsed_b, servings=2)
        db.session.add(plan_day_b)
    db.session.flush()

    plan_day_a.main_recipe_id, plan_day_b.main_recipe_id = plan_day_b.main_recipe_id, plan_day_a.main_recipe_id
    plan_day_a.excluded, plan_day_b.excluded = plan_day_b.excluded, plan_day_a.excluded

    sides_a = PlanDaySide.query.filter_by(plan_day_id=plan_day_a.id).all()
    sides_b = PlanDaySide.query.filter_by(plan_day_id=plan_day_b.id).all()
    for side in sides_a:
        side.plan_day_id = plan_day_b.id
    for side in sides_b:
        side.plan_day_id = plan_day_a.id

    db.session.commit()
    return {"ok": True}


@plan_bp.route('/plan/<start_date>/shopping-item/add', methods=['POST'])
def add_shopping_item(start_date):
    """AJAX-Endpunkt hinter dem "Artikel hinzufügen"-Mini-Formular auf der
    Plan-Seite (siehe static/plan.js: addExtraShoppingItem): legt einen
    manuellen Einkaufslisten-Posten an, der zu keinem Rezept gehört (z.B.
    Hygieneartikel). start_date wird wie überall sonst auf den Wochenmontag
    normalisiert, damit ein Artikel unabhängig davon, über welches Datum
    innerhalb der Woche die Seite gerade aufgerufen wurde, konsistent DER
    EINEN Woche zugeordnet wird.

    Erwartet einen JSON-Body {"name": str, "amount": Zahl oder null,
    "unit": str, "category": str}. name ist die einzige Pflichtangabe -
    ohne ihn ergibt der Eintrag keinen Sinn; amount/unit/category dürfen
    leer bleiben (z.B. "Klopapier" ganz ohne Mengenangabe).
    """
    start = parse_iso_date(start_date)
    if start is None:
        return {"error": "Ungültiges Datum"}, 400
    start = monday_of(start)

    data = request.get_json() or {}
    name = (data.get('name') or '').strip()
    if not name:
        return {"error": "Name darf nicht leer sein."}, 400

    try:
        raw_amount = data.get('amount')
        amount = float(raw_amount) if raw_amount not in (None, '') else None
    except (TypeError, ValueError):
        amount = None

    unit = (data.get('unit') or '').strip() or None
    category = (data.get('category') or '').strip() or None

    item = ExtraShoppingItem(week_start=start, name=name, amount=amount, unit=unit, category=category)
    db.session.add(item)
    db.session.commit()
    return {"id": item.id, "name": item.name, "amount": item.amount, "unit": item.unit, "category": item.category}


@plan_bp.route('/shopping-item/<int:item_id>/delete', methods=['POST'])
def delete_shopping_item(item_id):
    """AJAX-Endpunkt hinter dem ❌-Button eines manuell hinzugefügten
    Einkaufslisten-Postens: löscht ihn endgültig (im Gegensatz zur
    Ankreuzen-Funktion der übrigen Einkaufsliste, die rein clientseitig und
    nicht dauerhaft ist)."""
    item = ExtraShoppingItem.query.get_or_404(item_id)
    db.session.delete(item)
    db.session.commit()
    return {"ok": True}
