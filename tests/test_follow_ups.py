"""Linked recipes (RecipeFollowUp): a dish A is cooked for more servings and
its follow-up B is planned a few days later (services/follow_ups.py)."""
import json
import re
from datetime import date, timedelta

from werkzeug.datastructures import MultiDict

WEEK = "2026-06-15"            # Monday; the week starts Friday 2026-06-12
FRIDAY = date(2026, 6, 12)
NEXT_FRIDAY = date(2026, 6, 19)


def _link(app, source_id, follow_up_id, min_days=2, max_days=3):
    from models import RecipeFollowUp, db
    with app.app_context():
        db.session.add(RecipeFollowUp(recipe_id=source_id, follow_up_recipe_id=follow_up_id,
                                      min_days=min_days, max_days=max_days))
        db.session.commit()


def _days(app, plan_id, start=FRIDAY):
    """[(main_recipe_id, follow_up_of_date, excluded)] for the 7 days from start."""
    from models import PlanDay
    with app.app_context():
        rows = {pd.date: pd for pd in PlanDay.query.filter_by(plan_id=plan_id).all()}
        return [
            (rows[d].main_recipe_id, rows[d].follow_up_of_date, rows[d].excluded) if d in rows else None
            for d in (start + timedelta(days=i) for i in range(7))
        ]


def _exclude(*indexes):
    return [(f"day_excluded_{i}", "1") for i in indexes]


def _plan_data(resp):
    return json.loads(re.search(r"window\.PLAN_DATA = (.*?);\n", resp.data.decode("utf-8"), re.S).group(1))


def _fillers(make_recipe, category_id, count=7, prefix="Normal"):
    return [make_recipe(f"{prefix} {i}", category_id=category_id) for i in range(count)]


# --- drawing ---

def test_follow_up_dishes_are_never_drawn_on_their_own(app, test_plan_id, make_recipe, make_category):
    from services.planning import choose_recipe
    cat = make_category("Alles")
    a = make_recipe("Ofengemüse", category_id=cat)
    b = make_recipe("Nudeln mit Gemüsesoße", category_id=cat)
    _link(app, a, b)
    with app.app_context():
        for _ in range(20):
            assert choose_recipe(False, set(), test_plan_id).id == a
        assert choose_recipe(False, {a}, test_plan_id) is None


# --- week generation ---

def test_generate_places_follow_up_on_earliest_free_day_and_links_it(app, client, make_recipe, make_category):
    cat = make_category("Alles")
    a = make_recipe("Ofengemüse", category_id=cat)
    b = make_recipe("Nudeln mit Gemüsesoße", category_id=cat)
    _link(app, a, b)
    fillers = _fillers(make_recipe, cat)

    client.post(f"/plan/{WEEK}/generate", data={"day_recipe_0": str(a)})
    days = _days(app, client.plan_id)
    assert days[0][0] == a
    assert days[2] == (b, FRIDAY, False)
    assert all(d[0] in fillers and d[1] is None for i, d in enumerate(days) if i not in (0, 2))


def test_generate_without_free_day_in_window_plans_source_alone(app, client, make_recipe, make_category):
    cat = make_category("Alles")
    a = make_recipe("Ofengemüse", category_id=cat)
    b = make_recipe("Nudeln mit Gemüsesoße", category_id=cat)
    _link(app, a, b)
    fillers = _fillers(make_recipe, cat)

    client.post(f"/plan/{WEEK}/generate", data=MultiDict(
        [("day_recipe_0", str(a)), ("day_recipe_3", str(fillers[0]))] + _exclude(2)
    ))
    days = _days(app, client.plan_id)
    assert b not in [d[0] for d in days]
    assert all(d[1] is None for d in days)


def test_generate_picks_one_of_several_follow_ups(app, client, make_recipe, make_category):
    cat = make_category("Alles")
    a = make_recipe("Ofengemüse", category_id=cat)
    b1 = make_recipe("Gemüsesoße", category_id=cat)
    b2 = make_recipe("Gemüsesuppe", category_id=cat)
    _link(app, a, b1)
    _link(app, a, b2)
    _fillers(make_recipe, cat)

    client.post(f"/plan/{WEEK}/generate", data={"day_recipe_0": str(a)})
    mains = [d[0] for d in _days(app, client.plan_id)]
    assert (b1 in mains) != (b2 in mains)
    assert mains[2] in (b1, b2)


def test_generate_places_follow_up_of_a_drawn_dish(app, client, make_recipe, make_category):
    cat = make_category("Alles")
    a = make_recipe("Ofengemüse", category_id=cat)
    b = make_recipe("Nudeln mit Gemüsesoße", category_id=cat)
    _link(app, a, b)
    # Only day 0 and day 2 are open, and A is the only drawable dish.
    client.post(f"/plan/{WEEK}/generate", data=MultiDict(_exclude(1, 3, 4, 5, 6)))
    days = _days(app, client.plan_id)
    assert days[0][0] == a
    assert days[2] == (b, FRIDAY, False)


def test_follow_up_across_week_boundary_waits_as_pending(app, client, make_recipe, make_category):
    from models import PendingFollowUp
    cat = make_category("Alles")
    a = make_recipe("Ofengemüse", category_id=cat)
    b = make_recipe("Nudeln mit Gemüsesoße", category_id=cat)
    _link(app, a, b)
    _fillers(make_recipe, cat, count=12)

    # A on Wednesday (index 5): +2 days = next Friday, a week not created yet.
    client.post(f"/plan/{WEEK}/generate", data={"day_recipe_5": str(a)})
    with app.app_context():
        pending = PendingFollowUp.query.one()
        assert (pending.date, pending.recipe_id, pending.source_date) == (NEXT_FRIDAY, b, FRIDAY + timedelta(days=5))

    data = _plan_data(client.get("/plan/2026-06-12"))
    assert data["followUpsOut"][5][0]["pending"] is True
    assert data["followUpsOut"][5][0]["name"] == "Nudeln mit Gemüsesoße"

    html = client.get("/plan/2026-06-19/create").data.decode("utf-8")
    incoming = json.loads(re.search(r"window\.INCOMING_FOLLOW_UPS = (.*?);\n", html).group(1))
    assert [(e["dayIndex"], e["recipeId"], e["sourceName"]) for e in incoming] == [(0, b, "Ofengemüse")]

    # Kept as pinned on its day -> linked; the pending entry is used up.
    client.post("/plan/2026-06-19/generate", data={"day_recipe_0": str(b)})
    assert _days(app, client.plan_id, NEXT_FRIDAY)[0] == (b, FRIDAY + timedelta(days=5), False)
    with app.app_context():
        assert PendingFollowUp.query.filter_by(date=NEXT_FRIDAY).count() == 0


def test_pending_follow_up_dropped_when_unpinned(app, client, make_recipe, make_category):
    from models import PendingFollowUp
    cat = make_category("Alles")
    a = make_recipe("Ofengemüse", category_id=cat)
    b = make_recipe("Nudeln mit Gemüsesoße", category_id=cat)
    _link(app, a, b)
    _fillers(make_recipe, cat, count=12)
    client.post(f"/plan/{WEEK}/generate", data={"day_recipe_5": str(a)})

    client.post("/plan/2026-06-19/generate", data={})
    next_week = _days(app, client.plan_id, NEXT_FRIDAY)
    # Nothing links back to Wednesday's dish any more (A may well be drawn
    # again next week and bring its own follow-up).
    assert all(d[1] is None or d[1] >= NEXT_FRIDAY for d in next_week)
    with app.app_context():
        assert PendingFollowUp.query.filter_by(date=NEXT_FRIDAY).count() == 0


def test_follow_up_into_existing_week_needs_an_empty_day(app, client, make_recipe, make_category):
    cat = make_category("Alles")
    a = make_recipe("Ofengemüse", category_id=cat)
    b = make_recipe("Nudeln mit Gemüsesoße", category_id=cat)
    _link(app, a, b)
    _fillers(make_recipe, cat, count=14)
    # Next week exists; its Friday is excluded, its Saturday is full.
    client.post("/plan/2026-06-19/generate", data=MultiDict(_exclude(0)))
    before = _days(app, client.plan_id, NEXT_FRIDAY)

    client.post(f"/plan/{WEEK}/generate", data={"day_recipe_5": str(a)})
    assert _days(app, client.plan_id, NEXT_FRIDAY) == before


# --- day actions ---

def _assert_consistent(app, plan_id):
    """Every stored link points at a day whose dish has that follow-up."""
    from models import PlanDay, RecipeFollowUp
    with app.app_context():
        for pd in PlanDay.query.filter(PlanDay.plan_id == plan_id, PlanDay.follow_up_of_date.isnot(None)):
            source = PlanDay.query.filter_by(plan_id=plan_id, date=pd.follow_up_of_date).one()
            assert RecipeFollowUp.query.filter_by(
                recipe_id=source.main_recipe_id, follow_up_recipe_id=pd.main_recipe_id).count() == 1


def _week_with_link(app, client, make_recipe, make_category, extra_source=False):
    cat = make_category("Alles")
    a = make_recipe("Ofengemüse", category_id=cat)
    b = make_recipe("Nudeln mit Gemüsesoße", category_id=cat)
    _link(app, a, b)
    fillers = _fillers(make_recipe, cat, count=10)
    client.post(f"/plan/{WEEK}/generate", data={"day_recipe_0": str(a)})
    assert _days(app, client.plan_id)[2] == (b, FRIDAY, False)
    return a, b, fillers


def test_reroll_source_rerolls_follow_up_day(app, client, make_recipe, make_category):
    a, b, fillers = _week_with_link(app, client, make_recipe, make_category)
    resp = client.post("/day/2026-06-12/reroll-main")
    assert resp.get_json()["links_changed"] is True
    days = _days(app, client.plan_id)
    assert days[0][0] != a and days[0][0] in fillers
    assert days[2][0] not in (None, b) and days[2][1] is None
    _assert_consistent(app, client.plan_id)


def test_reroll_source_into_new_source_reuses_freed_day(app, client, make_recipe, make_category):
    from models import Recipe, db
    a, b, fillers = _week_with_link(app, client, make_recipe, make_category)
    with app.app_context():
        cat = db.session.get(Recipe, a).category_id
    a2 = make_recipe("Ofenkartoffeln", category_id=cat)
    b2 = make_recipe("Bratkartoffeln", category_id=cat)
    _link(app, a2, b2)

    client.post("/day/2026-06-12/set-main", json={"recipe_id": a2})
    days = _days(app, client.plan_id)
    assert days[0][0] == a2
    assert days[2] == (b2, FRIDAY, False)


def test_reroll_follow_up_only_drops_link(app, client, make_recipe, make_category):
    a, b, fillers = _week_with_link(app, client, make_recipe, make_category)
    resp = client.post("/day/2026-06-14/reroll-main")
    assert resp.get_json()["links_changed"] is True
    days = _days(app, client.plan_id)
    assert days[0][0] == a
    assert days[2][0] != b and days[2][1] is None


def test_excluding_source_day_rerolls_follow_up(app, client, make_recipe, make_category):
    a, b, fillers = _week_with_link(app, client, make_recipe, make_category)
    resp = client.post("/day/2026-06-12/toggle-exclude")
    assert resp.get_json() == {"excluded": True, "links_changed": True}
    days = _days(app, client.plan_id)
    assert days[0] == (None, None, True)
    assert days[2][0] not in (None, b) and days[2][1] is None
    _assert_consistent(app, client.plan_id)


def test_excluding_follow_up_day_unlinks(app, client, make_recipe, make_category):
    a, b, fillers = _week_with_link(app, client, make_recipe, make_category)
    client.post("/day/2026-06-14/toggle-exclude")
    days = _days(app, client.plan_id)
    assert days[0][0] == a
    assert days[2] == (None, None, True)


def test_swap_moves_links_with_dishes(app, client, make_recipe, make_category):
    a, b, fillers = _week_with_link(app, client, make_recipe, make_category)
    # Source to Saturday: the follow-up now points to Saturday.
    resp = client.post("/day/2026-06-12/swap/2026-06-13")
    assert resp.get_json()["links_changed"] is True
    days = _days(app, client.plan_id)
    assert days[1][0] == a and days[2] == (b, FRIDAY + timedelta(days=1), False)
    # Follow-up to Thursday: its link travels along.
    client.post("/day/2026-06-14/swap/2026-06-18")
    days = _days(app, client.plan_id)
    assert days[6] == (b, FRIDAY + timedelta(days=1), False)
    assert days[2][1] is None


def test_recreating_week_rerolls_follow_ups_in_next_week(app, client, make_recipe, make_category):
    cat = make_category("Alles")
    a = make_recipe("Ofengemüse", category_id=cat)
    b = make_recipe("Nudeln mit Gemüsesoße", category_id=cat)
    _link(app, a, b)
    fillers = _fillers(make_recipe, cat, count=14)
    client.post("/plan/2026-06-19/generate", data=MultiDict(_exclude(0)))
    client.post("/day/2026-06-19/toggle-exclude")                      # next Friday open again, no dish
    client.post(f"/plan/{WEEK}/generate", data={"day_recipe_5": str(a)})
    assert _days(app, client.plan_id, NEXT_FRIDAY)[0] == (b, FRIDAY + timedelta(days=5), False)

    client.post(f"/plan/{WEEK}/generate", data={"day_recipe_5": str(fillers[0])})
    friday = _days(app, client.plan_id, NEXT_FRIDAY)[0]
    assert friday[0] is not None and friday[0] != b and friday[1] is None


# --- recipe form ---

def _recipe_form(category_id, **extra):
    form = MultiDict([
        ("name", "Ofengemüse"), ("category_id", str(category_id)), ("servings", "2"),
        ("ing_name[]", "Paprika"), ("ing_amount[]", "300"), ("ing_unit[]", "g"),
        ("ing_category[]", ""), ("ing_pantry[]", "0"), ("ing_from_previous[]", "1"),
    ])
    for key, values in extra.items():
        for value in values:
            form.add(key, value)
    return form


def test_recipe_form_saves_follow_ups_and_from_previous(app, client, make_recipe, make_category):
    from models import Recipe, db
    cat = make_category("Alles")
    a = make_recipe("Ofengemüse", category_id=cat)
    b = make_recipe("Nudeln", category_id=cat)
    side = make_recipe("Salat", category_id=cat, is_side_dish=True)
    form = _recipe_form(cat, **{
        "fu_recipe[]": [str(b), str(b), str(a), str(side), "999999", "x"],
        "fu_min[]": ["0", "1", "2", "2", "2", "2"],
        "fu_max[]": ["99", "1", "3", "3", "3", "3"],
    })
    resp = client.post(f"/edit-recipe/{a}", data=form, headers={"X-Requested-With": "XMLHttpRequest"})
    assert resp.status_code == 200
    with app.app_context():
        recipe = db.session.get(Recipe, a)
        assert [(l.follow_up_recipe_id, l.min_days, l.max_days) for l in recipe.follow_ups] == [(b, 1, 14)]
        assert recipe.ingredients[0].from_previous is True

    html = client.get(f"/manage/recipe/edit/{a}").data.decode("utf-8")
    assert 'name="fu_recipe[]"' in html and f'<option value="{b}" selected>' in html


def test_deleting_recipes_cleans_up_links(app, client, make_recipe, make_category):
    from models import PendingFollowUp, RecipeFollowUp, db
    a, b, fillers = _week_with_link(app, client, make_recipe, make_category)
    client.post(f"/delete-recipe/{a}")
    days = _days(app, client.plan_id)
    assert days[0][0] is None and days[2] == (b, None, False)
    with app.app_context():
        assert RecipeFollowUp.query.count() == 0

    # Deleting a follow-up removes the definitions pointing at it.
    cat = make_category("Neu")
    a2 = make_recipe("A2", category_id=cat)
    _link(app, a2, b)
    client.post(f"/delete-recipe/{b}")
    with app.app_context():
        assert RecipeFollowUp.query.count() == 0 and PendingFollowUp.query.count() == 0


# --- week page data ---

def test_week_view_carries_link_data(app, client, make_recipe, make_category):
    a, b, fillers = _week_with_link(app, client, make_recipe, make_category)
    data = _plan_data(client.get("/plan/2026-06-12"))
    assert data["followUpOf"][2]["index"] == 0 and data["followUpOf"][2]["name"] == "Ofengemüse"
    out = data["followUpsOut"][0]
    assert [(e["index"], e["name"], e["pending"]) for e in out] == [(2, "Nudeln mit Gemüsesoße", False)]
    assert data["followUpOf"][0] is None and data["followUpsOut"][2] == []
