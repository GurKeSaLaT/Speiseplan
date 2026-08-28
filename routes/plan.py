"""Der Wochenplan-Kalender: Anzeige, Erstellen und alle Live-Interaktionen
(würfeln, tauschen, Beilage hinzufügen/entfernen, Personenzahl ändern) mit
dem dauerhaft in PlanDay gespeicherten Plan.

Zwei Arten von Routen leben hier nebeneinander:

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
  hinweg funktionieren (siehe reroll_day).

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

from models import db, Category, Recipe, PlanDay, ExtraShoppingItem
from services.planning import (
    DAY_NAMES_DE, monday_of, week_dates_for, parse_iso_date, week_neighbor_exclude_ids,
    assign_balanced_categories, choose_recipe, jsonify_recipe
)

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
    plan (Hauptgerichte), side_plan (Beilagen), excluded_days (welche
    Tag-Indizes als "ausgenommen" markiert sind) und servings_list
    (Personenzahl je Tag, Default 2 für noch ungeplante Tage).

    has_any_data unterscheidet "diese Woche wurde noch NIE erstellt"
    (any(ordered) ist False, alle 7 Einträge sind None) von "diese Woche
    existiert, aber einzelne Tage sind z.B. ausgenommen oder leer" - nur im
    ersten Fall zeigt plan.html den großen "Neuen Wochenplan
    erstellen"-Button statt der Tageskarten.

    plan_data bündelt alle für die clientseitigen Live-Interaktionen
    nötigen Daten (siehe static/plan.js) in einem einzigen, über den
    Jinja-Filter `tojson` sicher als JSON eingebetteten Objekt
    (window.PLAN_DATA) - dieselben Recipe-Objekte werden dafür über
    jsonify_recipe() in einfache Dicts umgewandelt, exakt dieselbe
    Hilfsfunktion, die auch die /day/...-AJAX-Endpunkte weiter unten für
    ihre Antworten verwenden, damit das Datenformat konsistent bleibt.
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
    side_plan = [pd.side_recipe if pd else None for pd in ordered]
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

    plan_data = {
        'weekDates': [d.isoformat() for d in dates],
        'dayLabels': day_labels,
        'excludedDays': [i in excluded_days for i in range(7)],
        'servingsList': servings_list,
        'plan': [jsonify_recipe(r) if r else None for r in plan],
        'sidePlan': [jsonify_recipe(r) if r else None for r in side_plan],
        'extraItems': [
            {"id": it.id, "name": it.name, "amount": it.amount, "unit": it.unit, "category": it.category}
            for it in extra_items
        ],
    }

    return render_template(
        'plan.html',
        plan=plan, side_plan=side_plan, excluded_days=excluded_days, servings_list=servings_list,
        week_dates=dates, start_date=normalized, has_any_data=has_any_data, days=DAY_NAMES_DE,
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
       zugewiesen wurde (day_recipe_i). Die Beilagen-ID (day_side_recipe_i)
       wird IMMER gelesen, unabhängig vom Ausnahme-Status - ein
       ausgenommener Tag (kein Hauptgericht) darf trotzdem eine feste
       Beilage haben.

    2./2b. Die im Formular referenzierten Rezept-IDs werden in EINER
       Datenbankabfrage pro Liste (statt einer Abfrage pro Tag) nachgeladen
       und in final_plan/final_side_plan (je eine Liste mit 7 Einträgen,
       None = noch nichts zugewiesen) eingetragen. used_recipe_ids sammelt
       dabei alle bereits fest verwendeten HAUPTGERICHT-IDs, damit sie beim
       automatischen Auffüllen in Schritt 5 nicht doppelt vergeben werden.
       Beilagen werden bewusst NIE automatisch gewürfelt - nur eine fest
       zugewiesene Beilage landet im Plan; alles Weitere läuft über den
       🎲-Button auf der fertigen Plan-Seite (reroll_side_day unten).

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
       (get-or-create) und mit dem Ergebnis überschrieben. Das deckt sowohl
       das erstmalige Erstellen einer Woche ab als auch ein erneutes
       "Woche neu erstellen" über eine bereits vorhandene Woche (dann
       werden die vorhandenen Zeilen einfach überschrieben statt
       dupliziert).
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
    day_side_recipe_ids = {}  # Tag-Index -> Zusatzgericht-Rezept-ID (String)

    for i in range(7):
        if request.form.get(f'day_excluded_{i}') == '1':
            excluded_days.add(i)
        else:
            rid = (request.form.get(f'day_recipe_{i}') or '').strip()
            if rid:
                day_recipe_ids[i] = rid

        side_rid = (request.form.get(f'day_side_recipe_{i}') or '').strip()
        if side_rid:
            day_side_recipe_ids[i] = side_rid

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

    # 2b. Feste Zusatzgerichte (Beilagen) anhand ihrer ID nachladen.
    final_side_plan = [None] * 7

    if day_side_recipe_ids:
        unique_side_ids = list(set(day_side_recipe_ids.values()))
        side_recipes_by_id = {
            str(r.id): r for r in Recipe.query.filter(Recipe.id.in_(unique_side_ids)).all()
        }
        for day_index, rid in day_side_recipe_ids.items():
            recipe = side_recipes_by_id.get(rid)
            if recipe:
                final_side_plan[day_index] = recipe

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

    # 5. Restliche Tage mit passenden, noch nicht verwendeten Hauptgerichten auffüllen
    for day_index, needed_cat_id in category_by_day.items():
        chosen = choose_recipe(is_side_dish=False, exclude_ids=used_recipe_ids, category_id=needed_cat_id)
        if not chosen:
            chosen = choose_recipe(is_side_dish=False, exclude_ids=used_recipe_ids)

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
        plan_day.excluded = i in excluded_days
        plan_day.main_recipe_id = final_plan[i].id if final_plan[i] else None
        plan_day.side_recipe_id = final_side_plan[i].id if final_side_plan[i] else None

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
    """
    target_date = parse_iso_date(day_date)
    if target_date is None:
        return {"error": "Ungültiges Datum"}, 400

    plan_day = PlanDay.query.filter_by(date=target_date).first()
    if not plan_day or plan_day.excluded:
        return {"error": "Dieser Tag ist nicht Teil eines Plans oder von der Hauptgericht-Planung ausgenommen."}, 400

    exclude_ids = week_neighbor_exclude_ids(target_date, 'main_recipe_id')
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
        chosen = choose_recipe(is_side_dish=False, exclude_ids=exclude_ids, category_id=best_cat_id)
        if chosen:
            break
    if not chosen:
        chosen = choose_recipe(is_side_dish=False, exclude_ids=exclude_ids)

    if not chosen:
        return {"error": "Keine weiteren Rezepte in der Datenbank verfügbar!"}, 400

    plan_day.main_recipe_id = chosen.id
    db.session.commit()
    return jsonify_recipe(chosen)


@plan_bp.route('/day/<day_date>/reroll-side', methods=['POST'])
def reroll_side_day(day_date):
    """AJAX-Endpunkt hinter dem 🎲-Button einer Beilage: würfelt für diesen
    Kalendertag eine neue Beilage und persistiert sie sofort. Wird sowohl
    zum erstmaligen Hinzufügen einer Beilage verwendet (der Button zeigt
    dann "🥗 Beilage würfeln" statt eines Emoji-Icons, siehe plan.html) als
    auch zum Ersetzen einer bereits vorhandenen.

    Anders als reroll_day() (Hauptgericht) gibt es hier KEINE
    Kategorie-Balance und keine Nachbarschaftsregel - Beilagen werden rein
    nach "noch nicht diese Woche verwendet" ausgewählt. Auch die
    Ausnahme-Prüfung entfällt bewusst: eine Beilage lässt sich auch an
    einem Tag würfeln, der von der Hauptgericht-Planung ausgenommen ist
    (siehe models.py: PlanDay).

    Existiert für diesen Tag noch gar keine PlanDay-Zeile (z.B. weil direkt
    über die URL ein Datum außerhalb einer erstellten Woche angesprochen
    wird), wird sie hier neu angelegt statt einen Fehler zu werfen - der
    reguläre Weg dorthin führt zwar immer über eine bereits per
    week_generate() erstellte Woche, aber diese Route soll auch robust
    gegen den (in der aktuellen UI nicht vorgesehenen) Sonderfall sein.
    """
    target_date = parse_iso_date(day_date)
    if target_date is None:
        return {"error": "Ungültiges Datum"}, 400

    plan_day = PlanDay.query.filter_by(date=target_date).first()
    if not plan_day:
        plan_day = PlanDay(date=target_date, servings=2)
        db.session.add(plan_day)

    exclude_ids = week_neighbor_exclude_ids(target_date, 'side_recipe_id')
    if plan_day.side_recipe_id:
        exclude_ids.add(plan_day.side_recipe_id)

    chosen = choose_recipe(is_side_dish=True, exclude_ids=exclude_ids)
    if not chosen:
        return {"error": "Keine weiteren Beilagen in der Datenbank verfügbar!"}, 400

    plan_day.side_recipe_id = chosen.id
    db.session.commit()
    return jsonify_recipe(chosen)


@plan_bp.route('/day/<day_date>/remove-side', methods=['POST'])
def remove_side_day(day_date):
    """AJAX-Endpunkt hinter dem ❌-Button einer Beilage: entfernt sie
    wieder, ohne den Rest des Tages (Hauptgericht, Ausnahme-Status,
    Personenzahl) anzutasten. Existiert für diesen Tag noch gar keine
    PlanDay-Zeile, gibt es nichts zu tun - wird still mit {"ok": True}
    quittiert statt eines Fehlers, da das Endergebnis ("keine Beilage an
    diesem Tag") in beiden Fällen identisch ist."""
    target_date = parse_iso_date(day_date)
    if target_date is None:
        return {"error": "Ungültiges Datum"}, 400

    plan_day = PlanDay.query.filter_by(date=target_date).first()
    if plan_day:
        plan_day.side_recipe_id = None
        db.session.commit()
    return {"ok": True}


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
    """AJAX-Endpunkt hinter dem Drag-and-Drop-Tausch zweier Tageskarten auf
    der Plan-Seite: vertauscht Hauptgericht, Beilage UND Ausnahme-Status
    zweier Kalendertage komplett miteinander.

    Fehlt für einen der beiden Tage noch eine PlanDay-Zeile, wird sie mit
    leeren Werten neu angelegt, bevor getauscht wird - so funktioniert der
    Tausch auch dann, wenn z.B. ein Tag zwar zur bereits erstellten Woche
    gehört, aber (weil ausgenommen und ohne Beilage) noch nie eine eigene
    Zeile bekommen hat.

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

    plan_day_a.main_recipe_id, plan_day_b.main_recipe_id = plan_day_b.main_recipe_id, plan_day_a.main_recipe_id
    plan_day_a.side_recipe_id, plan_day_b.side_recipe_id = plan_day_b.side_recipe_id, plan_day_a.side_recipe_id
    plan_day_a.excluded, plan_day_b.excluded = plan_day_b.excluded, plan_day_a.excluded

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
