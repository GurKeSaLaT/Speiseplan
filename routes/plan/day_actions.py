"""AJAX-Endpunkte, die vom clientseitigen static/plan.js (und den
plan-*.js-Begleitdateien) aufgerufen werden und JSON zurückgeben - für
einzelne Kalendertage (day_date), nicht für ganze Wochen. Arbeiten direkt
mit dem konkreten Kalendertag, nicht mit Wochenstart+Index - das macht sie
unabhängig davon, in welcher Wochenansicht der Nutzer sie gerade auslöst,
und lässt z.B. die Nachbarschafts-Kategorie-Regel beim Reroll sogar über
Wochengrenzen hinweg funktionieren (siehe reroll_day).

Die Beilagen-Aktionen (/day/<day_date>/side/...) sind zusätzlich POSTEN-
bezogen (ein Tag kann mehrere Beilagen haben, siehe models.py:
PlanDaySide) - alle bis auf "add" adressieren daher eine konkrete
PlanDaySide-Zeile per <int:side_id>.
"""

from datetime import timedelta

from flask import request

from models import db, Category, Recipe, PlanDay, PlanDaySide
from services.planning import (
    parse_iso_date, week_neighbor_exclude_ids, week_side_recipe_ids,
    choose_recipe, jsonify_recipe, jsonify_side
)
from routes.plan import plan_bp


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
    # Neu gewürfeltes Gericht wurde noch nicht gekocht (siehe models.py:
    # PlanDay.cooked) - unabhängig davon, ob der vorherige Stand hier
    # bereits als gekocht markiert war.
    plan_day.cooked = False
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
    # Siehe reroll_day() oben - ein manuell zugewiesenes Gericht ist per
    # Definition noch nicht gekocht.
    plan_day.cooked = False
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
    - Ist recipe_id gesetzt (🥗-Auswahl-Button in static/plan-sides.js:
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
    # Siehe reroll_day() oben - eine neu gewürfelte Beilage ist noch nicht gekocht.
    plan_day_side.cooked = False
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
    # Siehe reroll_day() oben - eine manuell gewählte Beilage ist noch nicht gekocht.
    plan_day_side.cooked = False
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
    Beilage auf eine andere Tageskarte (siehe static/plan-sides.js:
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
    Hauptgericht, ALLE Beilagen, Ausnahme-Status UND Gekocht-Status zweier
    Kalendertage komplett miteinander. "Wird das Hauptgericht verschoben, kommen die
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
    # cooked gehört zum Hauptgericht, nicht zum Wochentag (anders als
    # servings, siehe Docstring oben) - wandert beim Tausch also MIT.
    plan_day_a.cooked, plan_day_b.cooked = plan_day_b.cooked, plan_day_a.cooked

    sides_a = PlanDaySide.query.filter_by(plan_day_id=plan_day_a.id).all()
    sides_b = PlanDaySide.query.filter_by(plan_day_id=plan_day_b.id).all()
    for side in sides_a:
        side.plan_day_id = plan_day_b.id
    for side in sides_b:
        side.plan_day_id = plan_day_a.id

    db.session.commit()
    return {"ok": True}


@plan_bp.route('/day/<day_date>/cooked', methods=['POST'])
def set_day_cooked(day_date):
    """AJAX-Endpunkt hinter der "Gekocht"-Checkbox im Rezept-Detail-Fenster
    (siehe static/plan.js: openRecipeDetail/toggleCooked) für das
    HAUPTGERICHT eines Tages - für eine Beilage siehe set_side_cooked
    unten.

    Setzt bewusst nur, wenn für diesen Tag bereits ein Hauptgericht
    zugewiesen ist (kein get-or-create wie z.B. bei set_day_servings): ein
    Tag ohne main_recipe_id hat auch kein Gericht, das man als "gekocht"
    markieren könnte - das Detail-Fenster ist ohnehin nur über einen Klick
    auf ein bereits zugewiesenes Gericht erreichbar.

    Erwartet einen JSON-Body {"cooked": bool}."""
    target_date = parse_iso_date(day_date)
    if target_date is None:
        return {"error": "Ungültiges Datum"}, 400

    plan_day = PlanDay.query.filter_by(date=target_date).first()
    if not plan_day or not plan_day.main_recipe_id:
        return {"error": "Für diesen Tag ist kein Hauptgericht zugewiesen."}, 400

    data = request.get_json() or {}
    plan_day.cooked = bool(data.get('cooked'))
    db.session.commit()
    return {"ok": True, "cooked": plan_day.cooked}


@plan_bp.route('/day/<day_date>/side/<int:side_id>/cooked', methods=['POST'])
def set_side_cooked(day_date, side_id):
    """Wie set_day_cooked() oben, aber für EINE bestimmte Beilage (das
    Detail-Fenster einer Beilage öffnet sich mit derselben Checkbox,
    siehe static/plan-sides.js: renderSidesSection).

    Erwartet einen JSON-Body {"cooked": bool}."""
    target_date = parse_iso_date(day_date)
    if target_date is None:
        return {"error": "Ungültiges Datum"}, 400

    plan_day_side = PlanDaySide.query.join(PlanDay).filter(
        PlanDaySide.id == side_id, PlanDay.date == target_date
    ).first()
    if not plan_day_side:
        return {"error": "Diese Beilage gehört nicht zu diesem Tag."}, 404

    data = request.get_json() or {}
    plan_day_side.cooked = bool(data.get('cooked'))
    db.session.commit()
    return {"ok": True, "cooked": plan_day_side.cooked}
