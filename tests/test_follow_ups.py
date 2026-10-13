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


def _source_date(dish):
    """Date of the source dish a main dish (PlanDay) or side (PlanDaySide)
    or pending follow-up is coupled to, or None."""
    from models import PlanDay, PlanDaySide, db
    if dish.source_side_id is not None:
        return db.session.get(PlanDaySide, dish.source_side_id).day.date
    if dish.source_day_id is not None:
        return db.session.get(PlanDay, dish.source_day_id).date
    return None


def _days(app, plan_id, start=FRIDAY):
    """[(main_recipe_id, source dish date, excluded)] for the 7 days from start."""
    from models import PlanDay
    with app.app_context():
        rows = {pd.date: pd for pd in PlanDay.query.filter_by(plan_id=plan_id).all()}
        return [
            (rows[d].main_recipe_id, _source_date(rows[d]), rows[d].excluded) if d in rows else None
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
        assert (pending.date, pending.recipe_id, _source_date(pending), pending.is_side) == (
            NEXT_FRIDAY, b, FRIDAY + timedelta(days=5), False)

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
    """Every stored coupling of a main dish or side points at an earlier
    dish (main dish or side) that has that follow-up."""
    from models import PlanDay, PlanDaySide, RecipeFollowUp, db
    with app.app_context():
        dishes = [(pd, pd.date, pd.main_recipe_id) for pd in PlanDay.query.filter_by(plan_id=plan_id)]
        dishes += [(side, side.day.date, side.recipe_id)
                   for side in PlanDaySide.query.join(PlanDay).filter(PlanDay.plan_id == plan_id)]
        for dish, day, recipe_id in dishes:
            if dish.source_side_id is not None:
                source = db.session.get(PlanDaySide, dish.source_side_id)
                source_plan_id, source_date, source_recipe_id = source.day.plan_id, source.day.date, source.recipe_id
            elif dish.source_day_id is not None:
                source = db.session.get(PlanDay, dish.source_day_id)
                source_plan_id, source_date, source_recipe_id = source.plan_id, source.date, source.main_recipe_id
            else:
                continue
            assert source_plan_id == plan_id and source_date < day
            assert RecipeFollowUp.query.filter_by(
                recipe_id=source_recipe_id, follow_up_recipe_id=recipe_id).count() == 1


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
        "fu_recipe[]": [str(b), str(b), str(side), "999999", "x"],
        "fu_min[]": ["0", "1", "2", "2", "2"],
        "fu_max[]": ["99", "1", "3", "3", "3"],
    })
    resp = client.post(f"/edit-recipe/{a}", data=form, headers={"X-Requested-With": "XMLHttpRequest"})
    assert resp.status_code == 200
    with app.app_context():
        recipe = db.session.get(Recipe, a)
        assert [(l.follow_up_recipe_id, l.min_days, l.max_days) for l in recipe.follow_ups] == [
            (b, 1, 14), (side, 2, 3)]
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


# --- shopping servings (PLAN_DATA.shoppingServings, ADR 0001) ---

def _shopping(data, index):
    return data["shoppingServings"][index]


def test_week_view_carries_shopping_servings_per_dish(app, client, make_recipe, make_category):
    _week_with_link(app, client, make_recipe, make_category)
    client.post("/day/2026-06-14/servings", json={"servings": 3})
    side = make_recipe("Salat", category_id=make_category("Beilagen"), is_side_dish=True)
    side_id = client.post("/day/2026-06-12/side/add", json={"recipe_id": side}).get_json()["side_id"]

    data = _plan_data(client.get("/plan/2026-06-12"))
    # Source dish: own 2 + the follow-up's 3; its sides only their own day's 2.
    assert _shopping(data, 0)["main"] == {"servings": 5, "followUpServings": 3, "skipPrecooked": False}
    assert _shopping(data, 0)["sides"] == {str(side_id): {"servings": 2, "followUpServings": 0, "skipPrecooked": False}}
    # Coupled follow-up dish: its own servings, pre-cooked ingredients skipped.
    assert _shopping(data, 2)["main"] == {"servings": 3, "followUpServings": 0, "skipPrecooked": True}
    assert _shopping(data, 1)["main"] == {"servings": 2, "followUpServings": 0, "skipPrecooked": False}
    assert _shopping(data, 1)["sides"] == {}


def test_shopping_servings_count_follow_ups_outside_the_week(app, client, make_recipe, make_category):
    cat = make_category("Alles")
    a = make_recipe("Ofengemüse", category_id=cat)
    b = make_recipe("Nudeln mit Gemüsesoße", category_id=cat)
    _link(app, a, b)
    _fillers(make_recipe, cat, count=14)
    # A on Wednesday: the follow-up waits as pending in next week (2 servings).
    client.post(f"/plan/{WEEK}/generate", data={"day_recipe_5": str(a)})
    assert _shopping(_plan_data(client.get("/plan/2026-06-12")), 5)["main"]["servings"] == 4

    # Next week created with it: a stored day outside this week counts too.
    client.post("/plan/2026-06-19/generate", data={"day_recipe_0": str(b)})
    client.post("/day/2026-06-19/servings", json={"servings": 4})
    assert _shopping(_plan_data(client.get("/plan/2026-06-12")), 5)["main"] == {
        "servings": 6, "followUpServings": 4, "skipPrecooked": False}
    assert _shopping(_plan_data(client.get("/plan/2026-06-19")), 0)["main"]["skipPrecooked"] is True


def test_week_without_dishes_has_empty_shopping_servings(client):
    data = _plan_data(client.get("/plan/2026-06-12"))
    assert data["shoppingServings"] == [{"main": None, "sides": {}}] * 7


def test_changing_servings_returns_fresh_shopping_servings(app, client, make_recipe, make_category):
    _week_with_link(app, client, make_recipe, make_category)
    body = client.post("/day/2026-06-14/servings", json={"servings": 4}).get_json()
    assert body["shopping_servings"][0]["main"]["servings"] == 6
    assert body["shopping_servings"][2]["main"]["servings"] == 4


def test_dish_actions_return_fresh_shopping_servings(app, client, make_recipe, make_category):
    _week_with_link(app, client, make_recipe, make_category)
    side = make_recipe("Salat", category_id=make_category("Beilagen"), is_side_dish=True)
    added = client.post("/day/2026-06-13/side/add", json={"recipe_id": side}).get_json()
    assert added["shopping_servings"][1]["sides"] == {
        str(added["side_id"]): {"servings": 2, "followUpServings": 0, "skipPrecooked": False}}

    rerolled = client.post("/day/2026-06-13/reroll-main").get_json()
    assert rerolled["links_changed"] is False
    assert rerolled["shopping_servings"][1]["main"]["servings"] == 2
    assert client.post("/day/2026-06-17/swap/2026-06-18").get_json()["shopping_servings"][0]["main"]["servings"] == 4


# --- side dishes as follow-up dishes ---

def _sides(app, plan_id, start=FRIDAY):
    """[[(side recipe_id, source dish date)]] for the 7 days from start."""
    from models import PlanDay
    with app.app_context():
        rows = {pd.date: pd for pd in PlanDay.query.filter_by(plan_id=plan_id).all()}
        return [
            [(side.recipe_id, _source_date(side)) for side in rows[d].sides] if d in rows else []
            for d in (start + timedelta(days=i) for i in range(7))
        ]


def _side_id(app, plan_id, recipe_id):
    from models import PlanDay, PlanDaySide
    with app.app_context():
        return PlanDaySide.query.join(PlanDay).filter(
            PlanDay.plan_id == plan_id, PlanDaySide.recipe_id == recipe_id).one().id


def _week_with_side_link(app, client, make_recipe, make_category):
    """Ofengemüse on Friday, its follow-up side Gemüsereis on Sunday."""
    cat = make_category("Alles")
    a = make_recipe("Ofengemüse", category_id=cat)
    s = make_recipe("Gemüsereis", category_id=cat, is_side_dish=True)
    _link(app, a, s)
    fillers = _fillers(make_recipe, cat, count=10)
    client.post(f"/plan/{WEEK}/generate", data={"day_recipe_0": str(a)})
    return a, s, fillers


def test_recipe_form_accepts_side_dish_follow_ups(app, client, make_recipe, make_category):
    from models import Recipe, db
    cat = make_category("Alles")
    a = make_recipe("Ofengemüse", category_id=cat)
    side = make_recipe("Gemüsereis", category_id=cat, is_side_dish=True)
    html = client.get(f"/manage/recipe/edit/{a}").data.decode("utf-8")
    choices = json.loads(re.search(r"window\.FOLLOW_UP_CHOICES = (.*?);\n", html).group(1))
    assert side in choices

    form = _recipe_form(cat, **{"fu_recipe[]": [str(side)], "fu_min[]": ["1"], "fu_max[]": ["2"]})
    resp = client.post(f"/edit-recipe/{a}", data=form, headers={"X-Requested-With": "XMLHttpRequest"})
    assert resp.status_code == 200
    with app.app_context():
        assert [(l.follow_up_recipe_id, l.min_days, l.max_days)
                for l in db.session.get(Recipe, a).follow_ups] == [(side, 1, 2)]


def test_generate_adds_follow_up_side_as_extra_side(app, client, make_recipe, make_category):
    a, s, fillers = _week_with_side_link(app, client, make_recipe, make_category)
    days = _days(app, client.plan_id)
    # Sunday keeps a normal main dish of its own; the side comes on top.
    assert days[2][0] in fillers and days[2][1] is None
    assert _sides(app, client.plan_id) == [[], [], [(s, FRIDAY)], [], [], [], []]


def test_follow_up_side_skips_excluded_days(app, client, make_recipe, make_category):
    cat = make_category("Alles")
    a = make_recipe("Ofengemüse", category_id=cat)
    s = make_recipe("Gemüsereis", category_id=cat, is_side_dish=True)
    _link(app, a, s)
    _fillers(make_recipe, cat)
    client.post(f"/plan/{WEEK}/generate", data=MultiDict([("day_recipe_0", str(a))] + _exclude(2)))
    assert _sides(app, client.plan_id) == [[], [], [], [(s, FRIDAY)], [], [], []]


def test_day_action_places_follow_up_side(app, client, make_recipe, make_category):
    cat = make_category("Alles")
    a = make_recipe("Ofengemüse", category_id=cat)
    s = make_recipe("Gemüsereis", category_id=cat, is_side_dish=True)
    _fillers(make_recipe, cat)
    client.post(f"/plan/{WEEK}/generate", data={})
    _link(app, a, s)

    resp = client.post("/day/2026-06-13/set-main", json={"recipe_id": a})
    assert resp.get_json()["links_changed"] is True
    assert _sides(app, client.plan_id)[3] == [(s, FRIDAY + timedelta(days=1))]


def test_side_rolls_never_draw_follow_up_recipes(app, client, make_recipe, make_category):
    cat = make_category("Alles")
    a = make_recipe("Ofengemüse", category_id=cat)
    s = make_recipe("Gemüsereis", category_id=cat, is_side_dish=True)
    normal = make_recipe("Salat", category_id=cat, is_side_dish=True)
    _link(app, a, s)
    _fillers(make_recipe, cat)
    client.post(f"/plan/{WEEK}/generate", data=MultiDict(_exclude(0, 1, 2, 3, 4, 5, 6)))

    added = client.post("/day/2026-06-12/side/add", json={}).get_json()
    assert added["id"] == normal
    # Salat is the only drawable side and already in the week.
    assert client.post(f"/day/2026-06-12/side/{added['side_id']}/reroll").status_code == 400


def test_follow_up_side_shopping_servings(app, client, make_recipe, make_category):
    a, s, fillers = _week_with_side_link(app, client, make_recipe, make_category)
    client.post("/day/2026-06-14/servings", json={"servings": 3})
    side_id = _side_id(app, client.plan_id, s)
    data = _plan_data(client.get("/plan/2026-06-12"))
    assert _shopping(data, 0)["main"] == {"servings": 5, "followUpServings": 3, "skipPrecooked": False}
    assert _shopping(data, 2)["sides"] == {
        str(side_id): {"servings": 3, "followUpServings": 0, "skipPrecooked": True}}
    # Sunday's own main dish is not coupled.
    assert _shopping(data, 2)["main"]["skipPrecooked"] is False
    out = data["followUpsOut"][0]
    assert [(e["index"], e["name"], e["pending"]) for e in out] == [(2, "Gemüsereis", False)]


def test_removing_follow_up_side_drops_coupling(app, client, make_recipe, make_category):
    a, s, fillers = _week_with_side_link(app, client, make_recipe, make_category)
    side_id = _side_id(app, client.plan_id, s)
    resp = client.post(f"/day/2026-06-14/side/{side_id}/remove")
    assert resp.get_json()["links_changed"] is True
    assert _shopping(_plan_data(client.get("/plan/2026-06-12")), 0)["main"]["servings"] == 2


def test_rerolling_follow_up_side_drops_coupling(app, client, make_recipe, make_category):
    a, s, fillers = _week_with_side_link(app, client, make_recipe, make_category)
    normal = make_recipe("Salat", category_id=make_category("Beilagen"), is_side_dish=True)
    side_id = _side_id(app, client.plan_id, s)
    body = client.post(f"/day/2026-06-14/side/{side_id}/reroll").get_json()
    assert body["id"] == normal and body["links_changed"] is True
    assert _sides(app, client.plan_id)[2] == [(normal, None)]
    assert body["shopping_servings"][0]["main"]["servings"] == 2


def test_setting_follow_up_side_by_hand_drops_coupling(app, client, make_recipe, make_category):
    a, s, fillers = _week_with_side_link(app, client, make_recipe, make_category)
    normal = make_recipe("Salat", category_id=make_category("Beilagen"), is_side_dish=True)
    side_id = _side_id(app, client.plan_id, s)
    body = client.post(f"/day/2026-06-14/side/{side_id}/set", json={"recipe_id": normal}).get_json()
    assert body["links_changed"] is True
    assert _sides(app, client.plan_id)[2] == [(normal, None)]


def test_moving_follow_up_side_keeps_coupling(app, client, make_recipe, make_category):
    a, s, fillers = _week_with_side_link(app, client, make_recipe, make_category)
    side_id = _side_id(app, client.plan_id, s)
    body = client.post(f"/day/2026-06-14/side/{side_id}/move/2026-06-15").get_json()
    assert body["links_changed"] is True
    assert _sides(app, client.plan_id)[3] == [(s, FRIDAY)]
    assert body["shopping_servings"][0]["main"]["servings"] == 4


def test_replacing_source_releases_follow_up_side(app, client, make_recipe, make_category):
    a, s, fillers = _week_with_side_link(app, client, make_recipe, make_category)
    body = client.post("/day/2026-06-12/reroll-main").get_json()
    assert body["links_changed"] is True
    assert _sides(app, client.plan_id) == [[]] * 7
    assert body["shopping_servings"][0]["main"]["servings"] == 2


def test_swap_carries_follow_up_side_coupling(app, client, make_recipe, make_category):
    a, s, fillers = _week_with_side_link(app, client, make_recipe, make_category)
    client.post("/day/2026-06-12/swap/2026-06-13")
    assert _sides(app, client.plan_id)[2] == [(s, FRIDAY + timedelta(days=1))]


def test_follow_up_side_across_week_boundary(app, client, make_recipe, make_category):
    from models import PendingFollowUp
    cat = make_category("Alles")
    a = make_recipe("Ofengemüse", category_id=cat)
    b = make_recipe("Braten", category_id=cat)
    s = make_recipe("Gemüsereis", category_id=cat, is_side_dish=True)
    n = make_recipe("Nudeln", category_id=cat)
    _link(app, a, s)
    _link(app, b, n, min_days=1, max_days=1)
    _fillers(make_recipe, cat, count=12)

    # Ofengemüse on Wednesday -> its side waits for next Friday; Braten on
    # Thursday -> its main follow-up waits for the same Friday.
    client.post(f"/plan/{WEEK}/generate", data={"day_recipe_5": str(a), "day_recipe_6": str(b)})
    with app.app_context():
        pending = sorted((p.date, p.recipe_id, _source_date(p), p.is_side) for p in PendingFollowUp.query)
    assert pending == sorted([
        (NEXT_FRIDAY, s, FRIDAY + timedelta(days=5), True),
        (NEXT_FRIDAY, n, FRIDAY + timedelta(days=6), False),
    ])
    data = _plan_data(client.get("/plan/2026-06-12"))
    assert _shopping(data, 5)["main"]["servings"] == 4
    assert [(e["name"], e["pending"]) for e in data["followUpsOut"][5]] == [("Gemüsereis", True)]

    html = client.get("/plan/2026-06-19/create").data.decode("utf-8")
    incoming = json.loads(re.search(r"window\.INCOMING_FOLLOW_UPS = (.*?);\n", html).group(1))
    assert sorted((e["dayIndex"], e["recipeId"], e["isSide"], e["sourceName"]) for e in incoming) == sorted([
        (0, s, True, "Ofengemüse"), (0, n, False, "Braten")])

    client.post("/plan/2026-06-19/generate", data={"day_recipe_0": str(n), "day_side_recipes_0[]": str(s)})
    assert _sides(app, client.plan_id, NEXT_FRIDAY)[0] == [(s, FRIDAY + timedelta(days=5))]
    assert _days(app, client.plan_id, NEXT_FRIDAY)[0] == (n, FRIDAY + timedelta(days=6), False)
    with app.app_context():
        assert PendingFollowUp.query.count() == 0

    # Recreating next week keeps the coupling while the side stays pinned...
    client.post("/plan/2026-06-19/generate", data={"day_side_recipes_0[]": str(s)})
    assert _sides(app, client.plan_id, NEXT_FRIDAY)[0] == [(s, FRIDAY + timedelta(days=5))]
    # ...and drops it once it isn't.
    client.post("/plan/2026-06-19/generate", data={})
    assert _sides(app, client.plan_id, NEXT_FRIDAY)[0] == []
    assert _shopping(_plan_data(client.get("/plan/2026-06-12")), 5)["main"]["servings"] == 2


def test_follow_up_side_into_existing_week(app, client, make_recipe, make_category):
    cat = make_category("Alles")
    a = make_recipe("Ofengemüse", category_id=cat)
    s = make_recipe("Gemüsereis", category_id=cat, is_side_dish=True)
    _link(app, a, s)
    _fillers(make_recipe, cat, count=14)
    client.post("/plan/2026-06-19/generate", data={})  # next week full of main dishes

    client.post(f"/plan/{WEEK}/generate", data={"day_recipe_5": str(a)})
    assert _sides(app, client.plan_id, NEXT_FRIDAY)[0] == [(s, FRIDAY + timedelta(days=5))]


def test_deleting_source_recipe_keeps_follow_up_side_uncoupled(app, client, make_recipe, make_category):
    a, s, fillers = _week_with_side_link(app, client, make_recipe, make_category)
    client.post(f"/delete-recipe/{a}")
    assert _sides(app, client.plan_id)[2] == [(s, None)]


# --- side dishes as source dishes ---

def _side_source_week(app, client, make_recipe, make_category):
    """A week of normal main dishes with Sunday left empty, plus two side
    sources: Salzkartoffeln -> Bratkartoffeln (main dish) and Reis ->
    Gebratener Reis (side). Nothing is planned from them yet."""
    cat = make_category("Alles")
    sides = make_category("Beilagen")
    fillers = _fillers(make_recipe, cat, count=10)
    k = make_recipe("Salzkartoffeln", category_id=sides, is_side_dish=True)
    b = make_recipe("Bratkartoffeln", category_id=cat)
    r = make_recipe("Reis", category_id=sides, is_side_dish=True)
    g = make_recipe("Gebratener Reis", category_id=sides, is_side_dish=True)
    _link(app, k, b)
    _link(app, r, g)
    client.post(f"/plan/{WEEK}/generate", data=MultiDict(_exclude(2)))
    client.post("/day/2026-06-14/toggle-exclude")  # Sunday open again, no main dish
    assert _days(app, client.plan_id)[2] == (None, None, False)
    return k, b, r, g, fillers


def test_adding_source_side_places_main_follow_up(app, client, make_recipe, make_category):
    k, b, r, g, fillers = _side_source_week(app, client, make_recipe, make_category)
    body = client.post("/day/2026-06-12/side/add", json={"recipe_id": k}).get_json()
    assert body["links_changed"] is True
    assert _days(app, client.plan_id)[2] == (b, FRIDAY, False)
    _assert_consistent(app, client.plan_id)


def test_adding_source_side_places_side_follow_up(app, client, make_recipe, make_category):
    k, b, r, g, fillers = _side_source_week(app, client, make_recipe, make_category)
    body = client.post("/day/2026-06-12/side/add", json={"recipe_id": r}).get_json()
    assert body["links_changed"] is True
    assert _sides(app, client.plan_id) == [[(r, None)], [], [(g, FRIDAY)], [], [], [], []]
    _assert_consistent(app, client.plan_id)


def test_rolling_a_source_side_places_its_follow_up(app, client, make_recipe, make_category):
    k, b, r, g, fillers = _side_source_week(app, client, make_recipe, make_category)
    client.post("/day/2026-06-15/side/add", json={"recipe_id": k})  # Monday: Bratkartoffeln on Wednesday
    # Reis is the only side left to draw (Gebratener Reis is a follow-up).
    body = client.post("/day/2026-06-12/side/add", json={}).get_json()
    assert body["id"] == r and body["links_changed"] is True
    assert _sides(app, client.plan_id)[2] == [(g, FRIDAY)]


def test_source_side_shopping_servings_and_notes(app, client, make_recipe, make_category):
    k, b, r, g, fillers = _side_source_week(app, client, make_recipe, make_category)
    client.post("/day/2026-06-14/servings", json={"servings": 3})
    k_id = client.post("/day/2026-06-12/side/add", json={"recipe_id": k}).get_json()["side_id"]
    r_id = client.post("/day/2026-06-13/side/add", json={"recipe_id": r}).get_json()["side_id"]
    g_id = _side_id(app, client.plan_id, g)
    assert _sides(app, client.plan_id)[3] == [(g, FRIDAY + timedelta(days=1))]
    client.post("/day/2026-06-15/servings", json={"servings": 4})

    data = _plan_data(client.get("/plan/2026-06-12"))
    # Source sides: own 2 plus the follow-up's servings; the day's main dish is not affected.
    assert _shopping(data, 0)["sides"][str(k_id)] == {"servings": 5, "followUpServings": 3, "skipPrecooked": False}
    assert _shopping(data, 0)["main"]["servings"] == 2
    assert _shopping(data, 1)["sides"][str(r_id)] == {"servings": 6, "followUpServings": 4, "skipPrecooked": False}
    # Follow-up dishes skip their pre-cooked ingredients.
    assert _shopping(data, 2)["main"] == {"servings": 3, "followUpServings": 0, "skipPrecooked": True}
    assert _shopping(data, 3)["sides"][str(g_id)] == {"servings": 4, "followUpServings": 0, "skipPrecooked": True}
    # Notes: the follow-ups hang on their source side, not on the day's main dish.
    assert data["followUpOf"][2]["name"] == "Salzkartoffeln" and data["followUpOf"][2]["index"] == 0
    assert data["followUpsOut"][0] == [] and data["followUpsOut"][1] == []
    assert [(e["index"], e["name"], e["pending"]) for e in data["sideFollowUpsOut"][str(k_id)]] == [
        (2, "Bratkartoffeln", False)]
    assert [(e["index"], e["name"], e["pending"]) for e in data["sideFollowUpsOut"][str(r_id)]] == [
        (3, "Gebratener Reis", False)]


def test_rerolling_source_side_releases_its_follow_ups(app, client, make_recipe, make_category):
    k, b, r, g, fillers = _side_source_week(app, client, make_recipe, make_category)
    salat = make_recipe("Salat", category_id=make_category("Salate"), is_side_dish=True)
    k_id = client.post("/day/2026-06-12/side/add", json={"recipe_id": k}).get_json()["side_id"]
    r_id = client.post("/day/2026-06-13/side/add", json={"recipe_id": r}).get_json()["side_id"]
    assert _sides(app, client.plan_id)[3] == [(g, FRIDAY + timedelta(days=1))]

    # Salat is the only side not in the week yet.
    body = client.post(f"/day/2026-06-13/side/{r_id}/reroll").get_json()
    assert body["id"] == salat and body["links_changed"] is True
    assert g not in [recipe_id for sides in _sides(app, client.plan_id) for recipe_id, _ in sides]

    # Now Reis is: Salzkartoffeln's follow-up is released, Reis places its own.
    body = client.post(f"/day/2026-06-12/side/{k_id}/reroll").get_json()
    assert body["id"] == r and body["links_changed"] is True
    sunday = _days(app, client.plan_id)[2]
    assert sunday[0] in fillers and sunday[1] is None
    assert _sides(app, client.plan_id)[2] == [(g, FRIDAY)]
    assert body["shopping_servings"][0]["sides"][str(k_id)]["followUpServings"] == 2
    _assert_consistent(app, client.plan_id)


def test_setting_source_side_releases_and_places_anew(app, client, make_recipe, make_category):
    k, b, r, g, fillers = _side_source_week(app, client, make_recipe, make_category)
    k_id = client.post("/day/2026-06-12/side/add", json={"recipe_id": k}).get_json()["side_id"]

    body = client.post(f"/day/2026-06-12/side/{k_id}/set", json={"recipe_id": r}).get_json()
    assert body["links_changed"] is True
    days = _days(app, client.plan_id)
    assert days[2][0] in fillers and days[2][1] is None
    assert _sides(app, client.plan_id)[2] == [(g, FRIDAY)]
    assert body["shopping_servings"][0]["sides"][str(k_id)]["followUpServings"] == 2
    _assert_consistent(app, client.plan_id)

    salat = make_recipe("Salat", category_id=make_category("Salate"), is_side_dish=True)
    body = client.post(f"/day/2026-06-12/side/{k_id}/set", json={"recipe_id": salat}).get_json()
    assert body["links_changed"] is True
    assert _sides(app, client.plan_id) == [[(salat, None)], [], [], [], [], [], []]


def test_removing_source_side_releases_its_follow_ups(app, client, make_recipe, make_category):
    k, b, r, g, fillers = _side_source_week(app, client, make_recipe, make_category)
    k_id = client.post("/day/2026-06-12/side/add", json={"recipe_id": k}).get_json()["side_id"]
    r_id = client.post("/day/2026-06-13/side/add", json={"recipe_id": r}).get_json()["side_id"]

    assert client.post(f"/day/2026-06-12/side/{k_id}/remove").get_json()["links_changed"] is True
    sunday = _days(app, client.plan_id)[2]
    assert sunday[0] in fillers and sunday[1] is None
    assert client.post(f"/day/2026-06-13/side/{r_id}/remove").get_json()["links_changed"] is True
    assert _sides(app, client.plan_id) == [[]] * 7


def test_moving_source_side_keeps_coupling(app, client, make_recipe, make_category):
    k, b, r, g, fillers = _side_source_week(app, client, make_recipe, make_category)
    k_id = client.post("/day/2026-06-12/side/add", json={"recipe_id": k}).get_json()["side_id"]
    r_id = client.post("/day/2026-06-12/side/add", json={"recipe_id": r}).get_json()["side_id"]
    assert _sides(app, client.plan_id)[2] == [(g, FRIDAY)]

    body = client.post(f"/day/2026-06-12/side/{r_id}/move/2026-06-13").get_json()
    assert body["links_changed"] is True
    assert _sides(app, client.plan_id)[2] == [(g, FRIDAY + timedelta(days=1))]
    assert body["shopping_servings"][0]["sides"] == {
        str(k_id): {"servings": 4, "followUpServings": 2, "skipPrecooked": False}}

    body = client.post(f"/day/2026-06-12/side/{k_id}/move/2026-06-13").get_json()
    assert body["links_changed"] is True
    assert _days(app, client.plan_id)[2] == (b, FRIDAY + timedelta(days=1), False)

    # Swapping days carries the sides and their couplings along.
    client.post("/day/2026-06-12/swap/2026-06-13")
    assert _days(app, client.plan_id)[2] == (b, FRIDAY, False)
    assert _sides(app, client.plan_id)[2] == [(g, FRIDAY)]
    _assert_consistent(app, client.plan_id)


def test_generate_places_follow_ups_of_pinned_sides(app, client, make_recipe, make_category):
    k, b, r, g, fillers = _side_source_week(app, client, make_recipe, make_category)
    client.post(f"/plan/{WEEK}/generate", data={
        "day_side_recipes_0[]": str(k), "day_side_recipes_1[]": str(r)})
    days = _days(app, client.plan_id)
    assert days[2] == (b, FRIDAY, False)
    assert _sides(app, client.plan_id) == [
        [(k, None)], [(r, None)], [], [(g, FRIDAY + timedelta(days=1))], [], [], []]
    _assert_consistent(app, client.plan_id)


def test_source_side_follow_up_waits_across_week_boundary(app, client, make_recipe, make_category):
    from models import PendingFollowUp
    k, b, r, g, fillers = _side_source_week(app, client, make_recipe, make_category)
    client.post(f"/plan/{WEEK}/generate", data={"day_side_recipes_5[]": str(r)})
    with app.app_context():
        assert [(p.date, p.recipe_id, _source_date(p), p.is_side) for p in PendingFollowUp.query] == [
            (NEXT_FRIDAY, g, FRIDAY + timedelta(days=5), True)]
    data = _plan_data(client.get("/plan/2026-06-12"))
    r_id = str(_side_id(app, client.plan_id, r))
    assert _shopping(data, 5)["sides"][r_id]["servings"] == 4
    assert [(e["index"], e["pending"]) for e in data["sideFollowUpsOut"][r_id]] == [(None, True)]

    html = client.get("/plan/2026-06-19/create").data.decode("utf-8")
    incoming = json.loads(re.search(r"window\.INCOMING_FOLLOW_UPS = (.*?);\n", html).group(1))
    assert [(e["dayIndex"], e["recipeId"], e["isSide"], e["sourceName"]) for e in incoming] == [(0, g, True, "Reis")]

    # Recreating this week without Reis drops the waiting follow-up.
    client.post(f"/plan/{WEEK}/generate", data={})
    with app.app_context():
        assert PendingFollowUp.query.count() == 0


def test_recreating_week_releases_follow_ups_of_its_sides(app, client, make_recipe, make_category):
    k, b, r, g, fillers = _side_source_week(app, client, make_recipe, make_category)
    client.post("/plan/2026-06-19/generate", data=MultiDict(_exclude(0)))
    client.post("/day/2026-06-19/toggle-exclude")  # next Friday open again, no main dish
    client.post(f"/plan/{WEEK}/generate", data={"day_side_recipes_5[]": str(k)})
    assert _days(app, client.plan_id, NEXT_FRIDAY)[0] == (b, FRIDAY + timedelta(days=5), False)

    client.post(f"/plan/{WEEK}/generate", data={})
    friday = _days(app, client.plan_id, NEXT_FRIDAY)[0]
    assert friday[0] not in (None, b) and friday[1] is None


def test_deleting_source_side_recipe_keeps_follow_ups_uncoupled(app, client, make_recipe, make_category):
    k, b, r, g, fillers = _side_source_week(app, client, make_recipe, make_category)
    client.post("/day/2026-06-12/side/add", json={"recipe_id": k})
    client.post("/day/2026-06-13/side/add", json={"recipe_id": r})
    client.post(f"/delete-recipe/{k}")
    client.post(f"/delete-recipe/{r}")
    assert _days(app, client.plan_id)[2] == (b, None, False)
    assert _sides(app, client.plan_id)[3] == [(g, None)]
