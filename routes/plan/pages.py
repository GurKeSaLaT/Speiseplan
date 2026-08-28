"""Seiten-Routen des Wochenplan-Kalenders: liefern ganze HTML-Seiten bzw.
leiten weiter. Arbeiten mit "Wochenstart-Datum" (immer ein Montag) und
einem Tag-Index 0-6 innerhalb dieser Woche - im Gegensatz zu den
Tages-Aktionen in day_actions.py, die direkt mit konkreten Kalendertagen
arbeiten.
"""

from collections import Counter
from datetime import date, timedelta

from flask import render_template, request, redirect, url_for, abort

from models import db, Category, Recipe, PlanDay, PlanDaySide, ExtraShoppingItem
from services.planning import (
    DAY_NAMES_DE, monday_of, week_dates_for, parse_iso_date,
    assign_balanced_categories, choose_recipe, jsonify_recipe, jsonify_side
)
from routes.plan import plan_bp


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
    nötigen Daten (siehe static/plan.js und die plan-*.js-Begleitdateien)
    in einem einzigen, über den Jinja-Filter `tojson` sicher als JSON
    eingebetteten Objekt (window.PLAN_DATA) - dieselben Recipe-Objekte
    werden dafür über jsonify_recipe()/jsonify_side() in einfache Dicts
    umgewandelt, exakt dieselben Hilfsfunktionen, die auch die
    /day/...-AJAX-Endpunkte in day_actions.py für ihre Antworten
    verwenden, damit das Datenformat konsistent bleibt. allRecipes enthält
    zusätzlich ALLE Rezepte (unabhängig vom aktuellen Plan) in einer
    schlanken Form - Grundlage für die manuelle Rezeptauswahl
    (Such-/Auswahlbox, siehe static/plan-manual-select.js sowie deren
    Verwendung in static/plan.js und static/plan-sides.js).
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
    # shopping.py: add_shopping_item) - lose über week_start an die Woche
    # gebunden, kein Fremdschlüssel auf PlanDay o.ä. nötig.
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
       🎲/✏️-Buttons auf der fertigen Plan-Seite (siehe day_actions.py:
       add_side/reroll_one_side/set_one_side).

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
