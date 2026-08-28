from collections import Counter
from datetime import date, timedelta

from flask import Blueprint, render_template, request, redirect, url_for, abort

from models import db, Category, Recipe, PlanDay
from services.planning import (
    DAY_NAMES_DE, monday_of, week_dates_for, parse_iso_date, week_neighbor_exclude_ids,
    assign_balanced_categories, choose_recipe, jsonify_recipe
)

plan_bp = Blueprint('plan', __name__)


# 1. HAUPTSEITE: leitet auf die aktuelle Kalenderwoche im dauerhaften Plan-Kalender um
@plan_bp.route('/')
def index():
    start = monday_of(date.today())
    return redirect(url_for('plan.week_view', start_date=start.isoformat()))


@plan_bp.route('/plan/<start_date>')
def week_view(start_date):
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
    day_labels = [
        f"{DAY_NAMES_DE[i]}, {dates[i].strftime('%d.%m.')}" + (' (Heute)' if dates[i] == today else '')
        for i in range(7)
    ]
    # Alle Daten, die die Plan-Seite clientseitig für Live-Interaktionen
    # (würfeln, tauschen, Beilage, Personenzahl, Einkaufsliste) braucht -
    # siehe static/plan.js
    plan_data = {
        'weekDates': [d.isoformat() for d in dates],
        'dayLabels': day_labels,
        'excludedDays': [i in excluded_days for i in range(7)],
        'servingsList': servings_list,
        'plan': [jsonify_recipe(r) if r else None for r in plan],
        'sidePlan': [jsonify_recipe(r) if r else None for r in side_plan],
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

        # Beilagen werden unabhängig vom Ausnahme-Status eines Tages gelesen:
        # auch ein von der Hauptgericht-Planung ausgenommener Tag darf eine
        # fest zugewiesene Beilage haben.
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
    #     Beilagen werden NIE automatisch gewürfelt - nur was der Nutzer hier
    #     fest zugewiesen hat, landet im Plan (Nachträgliches Würfeln erfolgt
    #     erst auf der Plan-Seite über den 🎲-Button).
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

    # 3. Bestimme, welche Tage noch automatisch aufgefüllt werden müssen
    #    (weder ausgenommen, noch bereits fest belegt)
    days_to_fill = [i for i in range(7) if i not in excluded_days and final_plan[i] is None]

    # 4. Kategorie je aufzufüllendem Tag bestimmen: möglichst gleichmäßig über die
    #    Woche balanciert und nach Möglichkeit nicht dieselbe Kategorie wie der
    #    direkte Vorgänger-/Nachfolgetag. Bereits fest zugewiesene Tage fließen als
    #    Vorbelastung in die Balance und als bekannte Nachbarn mit ein.
    preexisting_counts = Counter(
        final_plan[day_index].category_id
        for day_index in day_recipe_ids
        if final_plan[day_index] is not None
    )
    category_by_day = assign_balanced_categories(
        all_categories, days_to_fill, final_plan, preexisting_counts=preexisting_counts
    )

    # 5. Restliche Tage mit passenden, noch nicht verwendeten Hauptgerichten auffüllen
    #    (Zusatzgerichte/Beilagen sind hiervon ausgeschlossen). Bevorzugt Rezepte der
    #    aktuellen Saison, weicht aber auf jede Kategorie/Saison aus statt einen Tag
    #    leer zu lassen.
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
    target_date = parse_iso_date(day_date)
    if target_date is None:
        return {"error": "Ungültiges Datum"}, 400

    plan_day = PlanDay.query.filter_by(date=target_date).first()
    if not plan_day or plan_day.excluded:
        return {"error": "Dieser Tag ist nicht Teil eines Plans oder von der Hauptgericht-Planung ausgenommen."}, 400

    # Andere Hauptgerichte derselben Woche (inkl. des eigenen aktuellen) meiden,
    # damit kein Rezept doppelt in einer Woche landet bzw. sich wiederholt.
    exclude_ids = week_neighbor_exclude_ids(target_date, 'main_recipe_id')
    if plan_day.main_recipe_id:
        exclude_ids.add(plan_day.main_recipe_id)

    all_categories = Category.query.all()
    all_cat_ids = [c.id for c in all_categories]

    other_recipes = Recipe.query.filter(Recipe.id.in_(exclude_ids)).all()
    other_cat_counts = {cid: 0 for cid in all_cat_ids}
    for r in other_recipes:
        other_cat_counts[r.category_id] = other_cat_counts.get(r.category_id, 0) + 1

    # Kategorien der direkten Nachbartage meiden (nach Möglichkeit - siehe unten),
    # damit ein Reroll nicht zwei aufeinanderfolgende Tage in dieselbe Kategorie legt.
    # Echte Kalendertage: funktioniert auch über Wochengrenzen hinweg (z.B. So->Mo).
    neighbor_ids = []
    for neighbor_date in (target_date - timedelta(days=1), target_date + timedelta(days=1)):
        neighbor_day = PlanDay.query.filter_by(date=neighbor_date).first()
        if neighbor_day and neighbor_day.main_recipe_id:
            neighbor_ids.append(neighbor_day.main_recipe_id)
    neighbor_categories = {r.category_id for r in Recipe.query.filter(Recipe.id.in_(neighbor_ids)).all()}

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

    # Hauptgericht, Beilage und Ausnahme-Status tauschen. Die Personenzahl bleibt
    # bewusst am Kalendertag haengen, nicht am Gericht - wird NICHT mitgetauscht.
    plan_day_a.main_recipe_id, plan_day_b.main_recipe_id = plan_day_b.main_recipe_id, plan_day_a.main_recipe_id
    plan_day_a.side_recipe_id, plan_day_b.side_recipe_id = plan_day_b.side_recipe_id, plan_day_a.side_recipe_id
    plan_day_a.excluded, plan_day_b.excluded = plan_day_b.excluded, plan_day_a.excluded

    db.session.commit()
    return {"ok": True}
