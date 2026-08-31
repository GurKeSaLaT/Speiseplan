"""Page routes of the weekly plan calendar: deliver whole HTML pages or
redirect. Work with a "week-start date" (always a Monday) and a day
index 0-6 within that week - unlike the day actions in day_actions.py,
which work directly with concrete calendar days.
"""

from datetime import date, timedelta

from flask import render_template, request, redirect, url_for, abort
from flask_babel import gettext as _

from models import db, Category, PlanDay, PlanDaySide, ExtraShoppingItem
from services.auth import current_plan, current_user, user_plan_memberships
from services.planning import DAY_NAMES, monday_of, week_dates_for, parse_iso_date, jsonify_recipe, jsonify_side
from services.recipe_visibility import visible_recipes_query
from services.settings import get_display_units
from services.units import convert_for_display
from services.week_generation import generate_week
from routes.plan import plan_bp


@plan_bp.route('/')
def index():
    """The app's home page: always immediately redirects to the week
    view of the CURRENT calendar week (/plan/<Monday of today>), IN THE
    ACTIVE PLAN of the logged-in user (services/auth.py: current_plan() -
    which plan that is gets decided at login/via the plan switcher in the
    sidebar, not here). There is no longer a standalone "/" page - that
    used to be (before the permanent calendar was introduced) the day
    assignment page, which now lives at /plan/<start_date>/create and is
    only reachable via the "Create new weekly plan" button."""
    start = monday_of(date.today())
    return redirect(url_for('plan.week_view', start_date=start.isoformat()))


@plan_bp.route('/plan/<start_date>')
def week_view(start_date):
    """Shows the weekly plan for the calendar week containing start_date.

    start_date arrives as an arbitrary ISO date string from the URL
    (e.g. from a link to a specific day or the date-jump field) and
    doesn't necessarily have to be a Monday: normalized = monday_of(start)
    converts it to the start of the week, and if the original date
    doesn't already fall on it, a redirect is made to the normalized,
    "canonical" URL (e.g. /plan/2026-06-17 (Wednesday) -> /plan/2026-06-15
    (Monday of the same week)) - so every week always has exactly one
    valid URL, no matter which date it's reached through.

    Then loads the associated PlanDay rows for all 7 days of this week
    (if present - ordered contains None at the respective position if
    nothing has been planned for this day yet) and derives from that four
    parallel lists sorted by day index (0=Monday...6=Sunday): plan (main
    dishes), side_plan (a LIST of side dishes per day, see models/calendar.py:
    PlanDay.sides - a day can have any number of them), excluded_days
    (which day indices are marked "excluded") and servings_list (number
    of servings per day, default 2 for still-unplanned days).

    has_any_data distinguishes "this week has never been created" (any(ordered)
    is False, all 7 entries are None) from "this week exists, but
    individual days are e.g. excluded or empty" - only in the first case
    does plan.html show the big "Create new weekly plan" button instead
    of the day cards.

    plan_data bundles all the data needed for the client-side live
    interactions (see static/plan.js and the plan-*.js companion files)
    into a single object safely embedded as JSON via the Jinja filter
    `tojson` (window.PLAN_DATA) - the same Recipe objects are converted
    into plain dicts for this via jsonify_recipe()/jsonify_side(),
    exactly the same helper functions that the /day/...-AJAX endpoints in
    day_actions.py also use for their responses, so the data format stays
    consistent. allRecipes additionally contains ALL recipes (regardless
    of the current plan) in a slim form - the basis for manual recipe
    selection (search/select box, see static/plan-manual-select.js and
    its use in static/plan.js and static/plan-sides.js). otherPlanMeals
    contains, per weekday, the main dishes of the user's OTHER own plans
    (read-only, see static/plan.js: renderOtherPlanMeals).
    """
    start = parse_iso_date(start_date)
    if start is None:
        abort(404)
    normalized = monday_of(start)
    if normalized != start:
        return redirect(url_for('plan.week_view', start_date=normalized.isoformat()))

    active_plan = current_plan()
    # Since plans were decoupled from accounts (services/plans.py), "no
    # plan at all" is a normal, reachable state - e.g. right after
    # deleting one's last remaining plan (routes/plans.py: delete()).
    # Instead of the usual calendar data, plan.html then just shows a
    # notice along with a form to create the first plan (templates/plan.html:
    # {% if no_plan %}) - all remaining variables below would run into a
    # dead end anyway (active_plan.id would crash immediately, for example).
    if active_plan is None:
        return render_template('plan.html', no_plan=True)

    dates = week_dates_for(normalized)
    plan_days_by_date = {
        pd.date: pd for pd in PlanDay.query.filter(PlanDay.plan_id == active_plan.id, PlanDay.date.in_(dates)).all()
    }
    ordered = [plan_days_by_date.get(d) for d in dates]
    has_any_data = any(ordered)

    plan = [pd.main_recipe if pd else None for pd in ordered]
    side_plan = [pd.sides if pd else [] for pd in ordered]
    excluded_days = {i for i, pd in enumerate(ordered) if pd and pd.excluded}
    servings_list = [pd.servings if pd else 2 for pd in ordered]
    # Whether this day's main dish has already been marked as cooked
    # (see models/calendar.py: PlanDay.cooked) - controls the "graying out" of the
    # day card (static/plan.js: renderMainDisplay). Side dishes carry
    # their own cooked field directly in the jsonify_side() dict, so they
    # don't need their own parallel list here.
    cooked_main = [pd.cooked if pd else False for pd in ordered]

    today = date.today()
    # Fully formatted weekday+date labels ("Monday, 15.09. (Today)"),
    # which static/plan.js needs when re-rendering a day card after a day
    # swap, without needing to know weekday names itself.
    day_labels = [
        f"{DAY_NAMES[i]}, {dates[i].strftime('%d.%m.')}" + (' ' + _('(Today)') if dates[i] == today else '')
        for i in range(7)
    ]
    # Manually added shopping-list items for this week (see shopping.py:
    # add_shopping_item) - loosely tied to the week via week_start, no
    # foreign key to PlanDay or similar needed.
    extra_items = (
        ExtraShoppingItem.query.filter_by(plan_id=active_plan.id, week_start=normalized)
        .order_by(ExtraShoppingItem.id).all()
    )

    all_recipes = visible_recipes_query(active_plan.id).all()

    # Main dishes of the user's OTHER own plans for the same 7 calendar
    # days - purely informational, not interactive (see static/plan.js:
    # renderOtherPlanMeals). Only plans whose membership has
    # show_in_week_overview set (models/plan.py: PlanMembership - individually
    # toggleable per user, see routes/sharing.py: toggle_overview()), and
    # never the active plan itself (that's already shown in the tile
    # above). Side dishes are deliberately left out (only ONE dish per
    # plan and day, as described by the user).
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

    # plan/side_plan/excluded_days/servings_list/days are NO LONGER passed
    # to the template: the day cards are built entirely client-side from
    # plan_data (see templates/plan.html - the comment there explains
    # why). The template only needs week_dates/today (for data-date and
    # the "today" marker) and has_any_data for the card shell.
    return render_template(
        'plan.html',
        week_dates=dates, start_date=normalized, has_any_data=has_any_data,
        prev_start=(normalized - timedelta(days=7)).isoformat(),
        next_start=(normalized + timedelta(days=7)).isoformat(),
        today=today, plan_data=plan_data,
    )


@plan_bp.route('/plan/<start_date>/create')
def week_create_view(start_date):
    """Shows the form for (re-)creating a whole week
    (templates/create_week.html): live search + drag-and-drop, to fix
    individual days to a specific main/side dish or exclude them
    entirely, before the rest is filled in automatically.

    Only reached via the "Create new weekly plan" button (or "Recreate
    week" for an already planned week) from the week view - unlike
    before, this is no longer a standalone main page. start_date is
    normalized to the week's Monday just like in week_view(), but
    (unlike there) without a redirect on mismatch - this page is always
    reached via an already-correct link, a redirect here would only cost
    an unnecessary additional request.
    """
    start = parse_iso_date(start_date)
    if start is None:
        abort(404)
    start = monday_of(start)
    plan = current_plan()

    recipes = visible_recipes_query(plan.id).all()
    categories = Category.query.filter_by(plan_id=plan.id).order_by(Category.name).all()

    return render_template(
        'create_week.html', recipes=recipes, categories=categories,
        week_dates=week_dates_for(start), start_date=start, days=DAY_NAMES
    )


@plan_bp.route('/plan/<start_date>/generate', methods=['POST'])
def week_generate(start_date):
    """Processes the form from week_create_view(): takes over the days
    fixed by the user unchanged, rolls the remaining main dishes in a
    balanced way to fill the rest, and writes the result permanently to
    the database as PlanDay rows.

    Flow in three steps (numbered in the code):

    1. Read the form: for each of the 7 days (index 0=Monday...6=Sunday,
       NOT the same as a calendar date - the form only knows the position
       within the week), it is checked whether it's marked "excluded"
       (day_excluded_i), otherwise whether a recipe ID has been fixed for
       it (day_recipe_i). The side-dish IDs (day_side_recipes_i[], a
       LIST - a day can get any number of side dishes) are ALWAYS read,
       regardless of exclusion status - an excluded day (no main dish)
       can still have fixed side dishes.

    2. The actual balanced-category-assignment + recipe-selection
       orchestration (looking up the fixed dishes, determining which
       days still need automatic filling, assigning a category to each,
       then rolling a concrete recipe per day) lives in
       services/week_generation.py: generate_week() - see there for the
       detailed step-by-step docstring. Side dishes are deliberately
       NEVER rolled automatically - only fixed side dishes end up in the
       plan at creation time; everything else runs via the dice/pencil
       buttons on the finished plan page (see
       routes/plan/day_actions_sides.py: add_side/reroll_one_side/
       set_one_side).

    3. Only now is anything persisted: for each of the 7 calendar days of
       this week, the matching PlanDay row is fetched or newly created
       (get-or-create) and overwritten with the result. For the side
       dishes, ALL existing PlanDaySide rows of this day are deleted
       first and then newly created from final_side_plan[i] - much
       simpler than a diff of "changed/new/deleted", analogous to
       ingredient replacement in edit_recipe() in routes/recipes/crud.py. This
       covers both creating a week for the first time and recreating an
       already existing week ("recreate week").
    """
    start = parse_iso_date(start_date)
    if start is None:
        abort(404)
    start = monday_of(start)
    dates = week_dates_for(start)
    plan = current_plan()

    # 1. Read form data per day: fixed assignment + exclusion status
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

        # dict.fromkeys() instead of set(): removes duplicates (e.g. from
        # double-clicking in the form), while preserving the order in
        # which the side dishes were assigned.
        side_rids = [rid.strip() for rid in request.form.getlist(f'day_side_recipes_{i}[]') if rid.strip()]
        if side_rids:
            day_side_recipe_ids[i] = list(dict.fromkeys(side_rids))

    # 2. Balanced category assignment + recipe selection (see
    # services/week_generation.py: generate_week()).
    final_plan, final_side_plan = generate_week(plan, dates, excluded_days, day_recipe_ids, day_side_recipe_ids)

    # 3. Save permanently: one PlanDay per real calendar day of this week
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
    return redirect(url_for('plan.week_view', start_date=start.isoformat()))
