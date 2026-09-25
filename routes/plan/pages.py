"""Full-page plan routes: the cross-plan home summary, the week view and
week creation. Weeks are addressed by their start date (always a Friday)."""

from datetime import date, timedelta

from flask import render_template, request, redirect, url_for, abort, session
from flask_babel import gettext as _

from models import db, Category, Plan, PlanDay, PlanDaySide, ExtraShoppingItem
from services.auth import current_plan, current_user, selected_plan_id, user_has_plan_access, user_plan_memberships
from services.planning import DAY_NAMES, friday_of, week_dates_for, parse_iso_date, jsonify_recipe, jsonify_side
from services.plan_summary import build_week_summary
from services.recipe_visibility import visible_recipes_query
from services.settings import get_display_units
from services.units import convert_for_display
from services.week_generation import generate_week
from routes.plan import plan_bp


@plan_bp.route('/')
def index():
    """Read-only summary of the current week across all of the user's
    plans. Users without any plan get week_view()'s "create a plan" page."""
    if current_plan() is None:
        return week_view(date.today().isoformat())

    start = friday_of(date.today())
    summary = build_week_summary(current_user(), start)
    return render_template(
        'plan_summary.html', summary=summary, week_dates=week_dates_for(start), today=date.today(), days=DAY_NAMES
    )


@plan_bp.route('/plan/summary/open', methods=['POST'])
def summary_open_recipe():
    """Opens a dish clicked on the summary: switches to its plan, then shows
    that week with the day's detail window open (?open_day, read by plan.js)."""
    user = current_user()
    plan_id = request.form.get('plan_id', type=int)
    day = parse_iso_date(request.form.get('date'))
    if plan_id is None or day is None or not user_has_plan_access(user, plan_id):
        abort(400)

    session['active_plan_id'] = plan_id
    start = friday_of(day)
    return redirect(url_for(
        'plan.week_view', start_date=start.isoformat(), plan_id=plan_id, open_day=day.isoformat()
    ))


def _resolve_and_activate_plan(user, request_args):
    """The plan a page is for (?plan_id= if the user is a member, else the
    session's). Also makes it the session's active plan, because the page's
    AJAX actions use current_plan() rather than a URL parameter."""
    plan_id = selected_plan_id(request_args, user)
    if plan_id is None:
        return None
    session['active_plan_id'] = plan_id
    return db.session.get(Plan, plan_id)


@plan_bp.route('/plan/<start_date>')
def week_view(start_date):
    """Week containing start_date; any other date redirects to the week's
    Friday so each week has exactly one URL. All links carry ?plan_id= so a
    URL always identifies one plan's week.

    The day cards are rendered client-side from plan_data (window.PLAN_DATA).
    """
    start = parse_iso_date(start_date)
    if start is None:
        abort(404)
    normalized = friday_of(start)
    if normalized != start:
        return redirect(url_for(
            'plan.week_view', start_date=normalized.isoformat(), plan_id=request.args.get('plan_id')
        ))

    active_plan = _resolve_and_activate_plan(current_user(), request.args)
    # Having no plan at all is a normal state (e.g. after deleting the last one).
    if active_plan is None:
        return render_template('plan.html', no_plan=True)

    dates = week_dates_for(normalized)
    plan_days_by_date = {
        pd.date: pd for pd in PlanDay.query.filter(PlanDay.plan_id == active_plan.id, PlanDay.date.in_(dates)).all()
    }
    ordered = [plan_days_by_date.get(d) for d in dates]
    # False = this week was never created (shows the "create week" button).
    has_any_data = any(ordered)

    plan = [pd.main_recipe if pd else None for pd in ordered]
    side_plan = [pd.sides if pd else [] for pd in ordered]
    excluded_days = {i for i, pd in enumerate(ordered) if pd and pd.excluded}
    servings_list = [pd.servings if pd else 2 for pd in ordered]
    cooked_main = [pd.cooked if pd else False for pd in ordered]

    today = date.today()
    day_labels = [
        f"{DAY_NAMES[i]}, {dates[i].strftime('%d.%m.')}" + (' ' + _('(Today)') if dates[i] == today else '')
        for i in range(7)
    ]
    extra_items = (
        ExtraShoppingItem.query.filter_by(plan_id=active_plan.id, week_start=normalized)
        .order_by(ExtraShoppingItem.id).all()
    )

    all_recipes = visible_recipes_query(active_plan.id).all()

    # Read-only main dishes of the user's other plans on the same days
    # (only memberships with show_in_week_overview set).
    other_memberships = [
        m for m in user_plan_memberships(current_user())
        if m.plan_id != active_plan.id and m.show_in_week_overview
    ]
    other_plan_days_by_key = {}
    if other_memberships:
        other_plan_days = PlanDay.query.filter(
            PlanDay.plan_id.in_([m.plan_id for m in other_memberships]),
            PlanDay.date.in_(dates),
        ).all()
        other_plan_days_by_key = {(pd.plan_id, pd.date): pd for pd in other_plan_days}
    other_plan_meals = []
    for d in dates:
        meals_this_day = []
        for m in other_memberships:
            pd = other_plan_days_by_key.get((m.plan_id, d))
            if pd and pd.main_recipe:
                meals_this_day.append({
                    "planId": m.plan_id, "planName": m.plan.name,
                    "recipeId": pd.main_recipe.id, "recipeName": pd.main_recipe.name,
                })
        other_plan_meals.append(meals_this_day)

    plan_data = {
        'planId': active_plan.id,
        'weekDates': [d.isoformat() for d in dates],
        'dayLabels': day_labels,
        'excludedDays': [i in excluded_days for i in range(7)],
        'servingsList': servings_list,
        'cookedMain': cooked_main,
        'plan': [jsonify_recipe(r, active_plan.id) if r else None for r in plan],
        'sidePlan': [[jsonify_side(s, active_plan.id) for s in sides] for sides in side_plan],
        'extraItems': [
            {
                "id": it.id, "name": it.name,
                **dict(zip(
                    ("amount", "unit"),
                    convert_for_display(it.amount, it.unit, get_display_units(active_plan.id)) if it.amount is not None else (None, it.unit)
                )),
                "category": it.category,
            }
            for it in extra_items
        ],
        'allRecipes': [
            {"id": r.id, "name": r.name, "category_name": r.category.name, "is_side_dish": r.is_side_dish}
            for r in all_recipes
        ],
        'otherPlanMeals': other_plan_meals,
    }

    return render_template(
        'plan.html',
        week_dates=dates, start_date=normalized, has_any_data=has_any_data,
        prev_start=(normalized - timedelta(days=7)).isoformat(),
        next_start=(normalized + timedelta(days=7)).isoformat(),
        today=today, plan_data=plan_data, plan_id=active_plan.id,
    )


@plan_bp.route('/plan/<start_date>/create')
def week_create_view(start_date):
    """Form for (re)creating a week: pin or exclude days before the rest is
    filled automatically."""
    start = parse_iso_date(start_date)
    if start is None:
        abort(404)
    start = friday_of(start)
    plan = _resolve_and_activate_plan(current_user(), request.args)
    if plan is None:
        abort(404)

    recipes = visible_recipes_query(plan.id).all()
    categories = Category.query.filter_by(plan_id=plan.id).order_by(Category.name).all()

    return render_template(
        'create_week.html', recipes=recipes, categories=categories,
        week_dates=week_dates_for(start), start_date=start, days=DAY_NAMES, plan_id=plan.id
    )


@plan_bp.route('/plan/<start_date>/generate', methods=['POST'])
def week_generate(start_date):
    """Saves a week from the create form: pinned days stay, the remaining
    main dishes are generated (services/week_generation.py). Side dishes are
    never generated, only pinned ones are saved. Existing days are
    overwritten, so this also handles "recreate week"."""
    start = parse_iso_date(start_date)
    if start is None:
        abort(404)
    start = friday_of(start)
    dates = week_dates_for(start)
    # plan_id comes in the form action's query string, even though this is a POST.
    plan = _resolve_and_activate_plan(current_user(), request.args)
    if plan is None:
        abort(404)

    excluded_days = set()
    day_recipe_ids = {}  # day index -> main dish recipe ID (string)
    day_side_recipe_ids = {}  # day index -> list of side dish recipe IDs (strings)

    for i in range(7):
        if request.form.get(f'day_excluded_{i}') == '1':
            excluded_days.add(i)
        else:
            rid = (request.form.get(f'day_recipe_{i}') or '').strip()
            if rid:
                day_recipe_ids[i] = rid

        # Excluded days can still have pinned sides. dict.fromkeys dedupes, keeping order.
        side_rids = [rid.strip() for rid in request.form.getlist(f'day_side_recipes_{i}[]') if rid.strip()]
        if side_rids:
            day_side_recipe_ids[i] = list(dict.fromkeys(side_rids))

    final_plan, final_side_plan = generate_week(plan, dates, excluded_days, day_recipe_ids, day_side_recipe_ids)

    for i in range(7):
        day_date = dates[i]
        plan_day = PlanDay.query.filter_by(plan_id=plan.id, date=day_date).first()
        if not plan_day:
            plan_day = PlanDay(plan_id=plan.id, date=day_date, servings=2)
            db.session.add(plan_day)
            db.session.flush()  # assigns plan_day.id, for the PlanDaySide rows below
        plan_day.excluded = i in excluded_days
        plan_day.main_recipe_id = final_plan[i].id if final_plan[i] else None

        PlanDaySide.query.filter_by(plan_day_id=plan_day.id).delete()
        for side_recipe in final_side_plan[i]:
            db.session.add(PlanDaySide(plan_day_id=plan_day.id, recipe_id=side_recipe.id))

    db.session.commit()
    return redirect(url_for('plan.week_view', start_date=start.isoformat(), plan_id=plan.id))
