"""Read-only overview of one week's main dishes across all of a user's plans
(the "/" home page)."""

from models import PlanDay
from services.auth import user_plan_memberships
from services.planning import week_dates_for


def build_week_summary(user, start):
    """{"days": 7 lists of {plan_id, plan_name, recipe_id, recipe_name,
    date}, Friday first; "nutrition": None if nothing is planned, else
    {"week": totals, "daily_avg": ...}}.

    Includes every plan (show_in_week_overview doesn't apply here) and only
    main dishes. Values are per serving, and the daily average only counts
    days that have a dish.
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
