"""Leftovers (WeekLeftover): parsing, leftover-first week generation, the
create/week pages and the plan page's add/delete endpoints."""
import json
import re
from datetime import date

from werkzeug.datastructures import MultiDict

WEEK = "2026-06-15"          # a Monday; its week starts Friday 2026-06-12
FRIDAY = date(2026, 6, 12)


def _plan_data(resp):
    match = re.search(r"window\.PLAN_DATA = (.*?);\n", resp.data.decode("utf-8"), re.S)
    return json.loads(match.group(1))


def _ing(name, amount=100, unit="g", **kwargs):
    return {"name": name, "amount": amount, "unit": unit, **kwargs}


def _week_mains(app, plan_id):
    from models import PlanDay
    with app.app_context():
        days = PlanDay.query.filter_by(plan_id=plan_id).order_by(PlanDay.date).all()
        return [pd.main_recipe_id for pd in days]


# --- parsing ---

def test_parse_amount_accepts_decimal_comma_and_rejects_garbage():
    from services.leftovers import parse_amount
    assert parse_amount("1,5") == 1.5
    assert parse_amount(" 300 ") == 300
    for bad in ("", None, "abc", "0", "-2", "nan", "inf", True):
        assert parse_amount(bad) is None


def test_parse_leftovers_form_normalizes_names_units_and_aliases(app, test_plan_id):
    from models import IngredientAlias, db
    from services.leftovers import parse_leftovers_form

    with app.app_context():
        db.session.add(IngredientAlias(plan_id=test_plan_id, raw_name="Spaghetti", canonical_name="Nudeln"))
        db.session.commit()
        form = MultiDict([
            ("leftover_name[]", " zucchini "), ("leftover_amount[]", "0,5"), ("leftover_unit[]", "kg"),
            ("leftover_name[]", "spaghetti"), ("leftover_amount[]", ""), ("leftover_unit[]", "g"),
            ("leftover_name[]", "  "), ("leftover_amount[]", "3"), ("leftover_unit[]", "g"),
        ])
        leftovers = parse_leftovers_form(form, test_plan_id)

    assert leftovers == [
        {"name": "Zucchini", "amount": 500, "unit": "g"},
        # No amount -> no unit either ("all of it").
        {"name": "Nudeln", "amount": None, "unit": None},
    ]


def test_parse_leftovers_form_merges_duplicates(app, test_plan_id):
    from services.leftovers import parse_leftovers_form

    with app.app_context():
        form = MultiDict([
            ("leftover_name[]", "Sahne"), ("leftover_amount[]", "100"), ("leftover_unit[]", "ml"),
            ("leftover_name[]", "sahne"), ("leftover_amount[]", "0,1"), ("leftover_unit[]", "l"),
            ("leftover_name[]", "Reis"), ("leftover_amount[]", "200"), ("leftover_unit[]", "g"),
            ("leftover_name[]", "Reis"), ("leftover_amount[]", ""), ("leftover_unit[]", ""),
        ])
        leftovers = parse_leftovers_form(form, test_plan_id)

    assert {"name": "Sahne", "amount": 200, "unit": "ml"} in leftovers
    # Reis without unit and Reis in g are different keys; both kept.
    assert [(lo["amount"], lo["unit"]) for lo in leftovers if lo["name"] == "Reis"] == [(200, "g"), (None, None)]


# --- generation ---

def test_generate_puts_leftover_recipes_on_earliest_free_days(app, client, make_recipe, make_category):
    cat = make_category("Alles")
    plain = [make_recipe(f"Normal {i}", category_id=cat, ingredients=[_ing("Kartoffeln")]) for i in range(8)]
    zucchini = make_recipe("Zucchini-Pfanne", category_id=cat, ingredients=[_ing("Zucchini")])
    sahne = make_recipe("Sahnesoße", category_id=cat, ingredients=[_ing("Sahne", unit="ml")])

    resp = client.post(f"/plan/{WEEK}/generate", data=MultiDict([
        ("day_excluded_0", "1"),
        ("day_recipe_1", str(plain[0])),
        ("leftover_name[]", "zucchini"), ("leftover_amount[]", "300"), ("leftover_unit[]", "g"),
        ("leftover_name[]", "Sahne"), ("leftover_amount[]", ""), ("leftover_unit[]", ""),
    ]))
    assert resp.status_code == 302

    mains = _week_mains(app, client.plan_id)
    assert mains[0] is None and mains[1] == plain[0]
    # Day 0 excluded and day 1 pinned: the leftover dishes take days 2 and 3.
    assert set(mains[2:4]) == {zucchini, sahne}
    assert all(m in plain for m in mains[4:])


def test_generate_prefers_recipe_using_most_leftovers(app, client, make_recipe, make_category):
    cat = make_category("Alles")
    for i in range(7):
        make_recipe(f"Normal {i}", category_id=cat)
    make_recipe("Nur Zucchini", category_id=cat, ingredients=[_ing("Zucchini")])
    both = make_recipe("Zucchini mit Paprika", category_id=cat, ingredients=[_ing("Zucchini"), _ing("Paprika")])

    client.post(f"/plan/{WEEK}/generate", data=MultiDict([
        ("leftover_name[]", "Zucchini"), ("leftover_name[]", "Paprika"),
    ]))
    mains = _week_mains(app, client.plan_id)
    assert mains[0] == both
    # Everything was used by day 0, so "Nur Zucchini" isn't forced in.
    assert mains[1] != both


def test_generate_skips_leftover_already_used_by_pinned_side(app, client, make_recipe, make_category):
    cat = make_category("Alles")
    for i in range(7):
        make_recipe(f"Normal {i}", category_id=cat)
    make_recipe("Zucchini-Pfanne", category_id=cat, ingredients=[_ing("Zucchini")])
    side = make_recipe("Zucchini-Salat", category_id=cat, is_side_dish=True, ingredients=[_ing("Zucchini")])

    from services.week_generation import fill_leftover_days
    from models import Plan, Recipe, db
    with app.app_context():
        plan = db.session.get(Plan, client.plan_id)
        final_plan = [None] * 7
        sides = [[db.session.get(Recipe, side)]] + [[] for _ in range(6)]
        remaining = fill_leftover_days(
            plan.id, [FRIDAY] * 7, list(range(7)), final_plan, sides, set(), {"Zucchini"}
        )
    assert remaining == set()
    assert final_plan == [None] * 7


def test_generate_unusable_leftover_changes_nothing(app, client, make_recipe, make_category):
    cat = make_category("Alles")
    recipes = [make_recipe(f"Normal {i}", category_id=cat) for i in range(7)]
    client.post(f"/plan/{WEEK}/generate", data={"leftover_name[]": "Drachenfrucht"})
    assert sorted(_week_mains(app, client.plan_id)) == sorted(recipes)


def test_generate_leftover_day_counts_for_category_balance(app, client, make_recipe, make_category):
    """A leftover dish counts like a pinned one for category balance. Days
    1, 3 and 5 are excluded so the neighbor rule doesn't decide: day 2 must
    get the other category because day 0's leftover dish already used fish."""
    fish, meat = make_category("Fisch"), make_category("Fleisch")
    lachs = make_recipe("Lachs", category_id=fish, ingredients=[_ing("Lachs")])
    for i in range(3):
        make_recipe(f"Fisch {i}", category_id=fish)
        make_recipe(f"Fleisch {i}", category_id=meat)

    from models import Recipe, db
    for _ in range(5):
        client.post(f"/plan/{WEEK}/generate", data=MultiDict([
            ("day_excluded_1", "1"), ("day_excluded_3", "1"), ("day_excluded_5", "1"),
            ("leftover_name[]", "Lachs"),
        ]))
        mains = _week_mains(app, client.plan_id)
        assert mains[0] == lachs
        with app.app_context():
            assert db.session.get(Recipe, mains[2]).category_id == meat


def test_generate_stores_and_replaces_week_leftovers(app, client, make_recipe):
    from models import WeekLeftover
    make_recipe("Irgendwas")
    client.post(f"/plan/{WEEK}/generate", data=MultiDict([
        ("leftover_name[]", "Zucchini"), ("leftover_amount[]", "1"), ("leftover_unit[]", "kg"),
    ]))
    with app.app_context():
        stored = WeekLeftover.query.all()
        assert [(lo.week_start, lo.name, lo.amount, lo.unit) for lo in stored] == [(FRIDAY, "Zucchini", 1000, "g")]

    client.post(f"/plan/{WEEK}/generate", data={})
    with app.app_context():
        assert WeekLeftover.query.count() == 0


# --- pages ---

def test_create_view_prefills_leftovers_and_suggests_ingredients(app, client, make_recipe):
    from models import WeekLeftover, db
    make_recipe("Ofengemüse", ingredients=[_ing("Paprika")])
    with app.app_context():
        db.session.add(WeekLeftover(plan_id=client.plan_id, week_start=FRIDAY, name="Sahne", amount=200, unit="ml"))
        db.session.commit()

    html = client.get(f"/plan/{WEEK}/create").data.decode("utf-8")
    assert '<option value="Paprika">' in html
    initial = json.loads(re.search(r"window\.INITIAL_LEFTOVERS = (.*?);</script>", html).group(1))
    assert [(lo["name"], lo["amount"], lo["unit"]) for lo in initial] == [("Sahne", 200, "ml")]


def test_week_view_plan_data_has_leftovers_in_display_units(app, client):
    from models import WeekLeftover, db
    from services.settings import update_display_units
    with app.app_context():
        update_display_units(client.plan_id, "kg", "ml")
        db.session.add(WeekLeftover(plan_id=client.plan_id, week_start=FRIDAY, name="Mehl", amount=1500, unit="g"))
        db.session.add(WeekLeftover(plan_id=client.plan_id, week_start=date(2026, 6, 19), name="Andere Woche"))
        db.session.commit()

    data = _plan_data(client.get("/plan/2026-06-12"))
    assert [(lo["name"], lo["amount"], lo["unit"]) for lo in data["leftovers"]] == [("Mehl", 1.5, "kg")]


# --- add/delete endpoints ---

def test_add_leftover_normalizes_and_returns_display_units(app, client):
    from models import WeekLeftover
    resp = client.post(f"/plan/{WEEK}/leftover/add", json={"name": "zucchini", "amount": "250", "unit": "g"})
    assert resp.status_code == 200
    assert resp.get_json()["name"] == "Zucchini"
    with app.app_context():
        stored = WeekLeftover.query.one()
        assert (stored.week_start, stored.amount, stored.unit) == (FRIDAY, 250, "g")


def test_add_leftover_rejects_empty_name_and_bad_date(client):
    assert client.post(f"/plan/{WEEK}/leftover/add", json={"name": " "}).status_code == 400
    assert client.post("/plan/garbage/leftover/add", json={"name": "Reis"}).status_code == 400


def test_add_leftover_caps_entries_per_week(app, client):
    from models import WeekLeftover, db
    from services.leftovers import MAX_LEFTOVERS_PER_WEEK
    with app.app_context():
        for i in range(MAX_LEFTOVERS_PER_WEEK):
            db.session.add(WeekLeftover(plan_id=client.plan_id, week_start=FRIDAY, name=f"Rest {i}"))
        db.session.commit()
    assert client.post(f"/plan/{WEEK}/leftover/add", json={"name": "Noch einer"}).status_code == 400


def test_delete_leftover_only_in_own_plan(app, client, make_user):
    from models import WeekLeftover, db
    _, other_plan_id = make_user("Fremd")
    with app.app_context():
        own = WeekLeftover(plan_id=client.plan_id, week_start=FRIDAY, name="Reis")
        foreign = WeekLeftover(plan_id=other_plan_id, week_start=FRIDAY, name="Reis")
        db.session.add_all([own, foreign])
        db.session.commit()
        own_id, foreign_id = own.id, foreign.id

    assert client.post(f"/leftover/{foreign_id}/delete").status_code == 404
    assert client.post(f"/leftover/{own_id}/delete").status_code == 200
    assert client.post("/leftover/999999/delete").status_code == 404
    with app.app_context():
        assert [lo.id for lo in WeekLeftover.query.all()] == [foreign_id]


def test_deleting_plan_removes_its_leftovers(app, client):
    from models import Plan, WeekLeftover, db
    from services.plans import delete_plan
    with app.app_context():
        db.session.add(WeekLeftover(plan_id=client.plan_id, week_start=FRIDAY, name="Reis"))
        db.session.commit()
        delete_plan(db.session.get(Plan, client.plan_id))
        db.session.commit()
        assert WeekLeftover.query.count() == 0
