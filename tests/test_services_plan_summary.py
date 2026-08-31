"""Tests for services/plan_summary.py: the cross-plan weekly summary data
(the "/" landing page)."""
from datetime import date


def test_build_week_summary_groups_main_dishes_by_day_across_all_plans(app, client, make_user, make_recipe):
    from models import PlanDay, PlanMembership, User, db
    from services.plan_summary import build_week_summary

    other_id, other_plan_id = make_user("Mitbewohner")
    with app.app_context():
        db.session.add(PlanMembership(plan_id=other_plan_id, user_id=client.user_id, is_starred=False))
        db.session.commit()

    recipe_own = make_recipe("Eigenes Gericht", plan_id=client.plan_id)
    recipe_other = make_recipe("Anderes Gericht", plan_id=other_plan_id)

    monday = date(2026, 6, 15)
    with app.app_context():
        db.session.add(PlanDay(plan_id=client.plan_id, date=monday, main_recipe_id=recipe_own, servings=2))
        db.session.add(PlanDay(plan_id=other_plan_id, date=monday, main_recipe_id=recipe_other, servings=2))
        db.session.commit()

        user = User.query.get(client.user_id)
        summary = build_week_summary(user, monday)

    monday_entries = summary["days"][0]
    assert len(monday_entries) == 2
    assert {e["recipe_name"] for e in monday_entries} == {"Eigenes Gericht", "Anderes Gericht"}
    assert {e["plan_id"] for e in monday_entries} == {client.plan_id, other_plan_id}
    # No dish anywhere else in the week.
    assert all(summary["days"][i] == [] for i in range(1, 7))


def test_build_week_summary_nutrition_sums_across_plans_unscaled(app, client, make_user, make_recipe):
    """Regression test for the "combined weekly nutrition" figure on the
    summary page - the sum/average must add up dishes from EVERY plan,
    not just the active one, and stay unscaled by servings (matching the
    existing single-plan convention, see
    static/plan-shopping.js: rebuildWeeklyNutritionSummary())."""
    from models import PlanDay, PlanMembership, User, db
    from services.plan_summary import build_week_summary

    other_id, other_plan_id = make_user("Mitbewohner")
    with app.app_context():
        db.session.add(PlanMembership(plan_id=other_plan_id, user_id=client.user_id, is_starred=False))
        db.session.commit()

    recipe_a = make_recipe("A", plan_id=client.plan_id, calories=500, protein=20.0, carbs=50.0, fat=10.0)
    recipe_b = make_recipe("B", plan_id=other_plan_id, calories=300, protein=10.0, carbs=30.0, fat=5.0)

    monday = date(2026, 6, 15)
    tuesday = date(2026, 6, 16)
    with app.app_context():
        # Both dishes on Monday (two different plans), only A again on
        # Tuesday, in its own plan, with an unrelated servings count.
        db.session.add(PlanDay(plan_id=client.plan_id, date=monday, main_recipe_id=recipe_a, servings=2))
        db.session.add(PlanDay(plan_id=other_plan_id, date=monday, main_recipe_id=recipe_b, servings=4))
        db.session.add(PlanDay(plan_id=client.plan_id, date=tuesday, main_recipe_id=recipe_a, servings=1))
        db.session.commit()

        user = User.query.get(client.user_id)
        summary = build_week_summary(user, monday)

    assert summary["nutrition"]["week"]["calories"] == 500 + 300 + 500
    assert summary["nutrition"]["week"]["protein"] == 20.0 + 10.0 + 20.0
    # 2 planned days (Monday, Tuesday) - Wednesday..Sunday don't count.
    assert summary["nutrition"]["daily_avg"]["calories"] == (500 + 300 + 500) / 2


def test_build_week_summary_nutrition_is_none_when_nothing_planned(app, client):
    from models import User
    from services.plan_summary import build_week_summary

    with app.app_context():
        user = User.query.get(client.user_id)
        summary = build_week_summary(user, date(2026, 6, 15))

    assert summary["nutrition"] is None
    assert all(entries == [] for entries in summary["days"])


def test_build_week_summary_ignores_side_dishes(app, client, make_recipe):
    """Only main dishes count here, matching the existing "other plans"
    row's precedent (routes/plan/pages.py: week_view()) - a side dish
    must not show up in the summary."""
    from models import PlanDay, PlanDaySide, User, db
    from services.plan_summary import build_week_summary

    main = make_recipe("Hauptgericht")
    side = make_recipe("Beilage", is_side_dish=True)
    monday = date(2026, 6, 15)
    with app.app_context():
        plan_day = PlanDay(plan_id=client.plan_id, date=monday, main_recipe_id=main, servings=2)
        db.session.add(plan_day)
        db.session.flush()
        db.session.add(PlanDaySide(plan_day_id=plan_day.id, recipe_id=side))
        db.session.commit()

        user = User.query.get(client.user_id)
        summary = build_week_summary(user, monday)

    assert len(summary["days"][0]) == 1
    assert summary["days"][0][0]["recipe_name"] == "Hauptgericht"
