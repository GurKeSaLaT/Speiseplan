"""Cross-plan weekly summary (routes/plan/pages.py: index(), the "/"
landing page / templates/plan_summary.html) - a read-only overview of
every main dish planned in ANY of the user's plans for one calendar
week, with an aggregated nutrition total. Distinct from the fully
interactive single-plan calendar at routes/plan/pages.py: week_view()
(reached instead by picking a specific plan in the sidebar's "My Plans"
list, see routes/auth.py: switch_plan()) - this page has no dice/edit/
create controls at all, by design.
"""

from models import PlanDay
from services.auth import user_plan_memberships
from services.planning import week_dates_for


def build_week_summary(user, start):
    """Builds the data for one week (start = the Monday of that week,
    see services/planning.py: week_dates_for()), across EVERY plan the
    user has access to - deliberately ALL of them, unlike the
    show_in_week_overview-gated "other plans" row on the single-plan page
    (models/plan.py: PlanMembership.show_in_week_overview), since a
    cross-plan summary that silently omitted some of the user's own plans
    would defeat its own purpose.

    Only main dishes are considered (side dishes are left out here too,
    matching the existing "other plans" row's precedent, see
    routes/plan/pages.py: week_view()) - keeps the summary to one line
    per dish instead of a nested per-day list.

    Returns {"days": [7 lists of {plan_id, plan_name, recipe_id,
    recipe_name, date} dicts, one list per weekday, Monday first],
    "nutrition": None if nothing at all is planned this week, otherwise
    {"week": {...totals}, "daily_avg": {...}} - both unscaled per-serving
    sums (see static/plan-shopping.js: rebuildWeeklyNutritionSummary()
    for the same "always per portion, never multiplied by servings"
    convention), averaged only over days that actually have at least one
    dish somewhere, not over all 7.}
    """
    dates = week_dates_for(start)
    memberships = user_plan_memberships(user)
    plan_names = {m.plan_id: m.plan.name for m in memberships}
    plan_ids = list(plan_names.keys())

    plan_days = []
    if plan_ids:
        plan_days = PlanDay.query.filter(
            PlanDay.plan_id.in_(plan_ids), PlanDay.date.in_(dates), PlanDay.main_recipe_id.isnot(None)
        ).all()

    entries_by_date = {d: [] for d in dates}
    totals = {"calories": 0, "protein": 0.0, "carbs": 0.0, "fat": 0.0}
    planned_dates = set()

    for pd in plan_days:
        recipe = pd.main_recipe
        entries_by_date[pd.date].append({
            "plan_id": pd.plan_id,
            "plan_name": plan_names.get(pd.plan_id, ""),
            "recipe_id": recipe.id,
            "recipe_name": recipe.name,
            "date": pd.date.isoformat(),
        })
        totals["calories"] += recipe.calories or 0
        totals["protein"] += recipe.protein or 0.0
        totals["carbs"] += recipe.carbs or 0.0
        totals["fat"] += recipe.fat or 0.0
        planned_dates.add(pd.date)

    for entries in entries_by_date.values():
        entries.sort(key=lambda e: e["plan_name"])

    nutrition = None
    if planned_dates:
        day_count = len(planned_dates)
        nutrition = {
            "week": totals,
            "daily_avg": {key: value / day_count for key, value in totals.items()},
        }

    return {
        "days": [entries_by_date[d] for d in dates],
        "nutrition": nutrition,
    }
