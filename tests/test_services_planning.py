"""Tests für services/planning.py: Datums-Helfer, Kategorie-Balance und
Rezept-Auswahl (das Herzstück der automatischen Wochenplanung)."""
from datetime import date, timedelta

import pytest

from services.planning import (
    FAVORITE_WEIGHT,
    assign_balanced_categories,
    choose_recipe,
    jsonify_recipe,
    jsonify_side,
    monday_of,
    parse_iso_date,
    recent_usage_counts,
    week_dates_for,
    weighted_recipe_choice,
)


# --- Datums-Helfer ---

def test_monday_of_returns_same_date_for_a_monday():
    monday = date(2026, 6, 15)  # ist ein Montag
    assert monday_of(monday) == monday


def test_monday_of_rewinds_to_previous_monday():
    wednesday = date(2026, 6, 17)
    assert monday_of(wednesday) == date(2026, 6, 15)


def test_week_dates_for_returns_seven_consecutive_days():
    start = date(2026, 6, 15)
    dates = week_dates_for(start)
    assert len(dates) == 7
    assert dates[0] == start
    assert dates[-1] == start + timedelta(days=6)


def test_parse_iso_date_valid():
    assert parse_iso_date("2026-06-15") == date(2026, 6, 15)


@pytest.mark.parametrize("value", ["not-a-date", "", None, "2026-13-40"])
def test_parse_iso_date_invalid_returns_none(value):
    assert parse_iso_date(value) is None


# --- weighted_recipe_choice: Gewichtungs-Berechnung ---

class FakeRecipe:
    def __init__(self, id, is_favorite=False):
        self.id = id
        self.is_favorite = is_favorite


def test_weighted_recipe_choice_favorite_gets_favorite_weight(monkeypatch):
    captured = {}

    def fake_choices(population, weights, k):
        captured["weights"] = weights
        return [population[0]]

    monkeypatch.setattr("services.planning.random.choices", fake_choices)

    recipes = [FakeRecipe(1, is_favorite=True), FakeRecipe(2, is_favorite=False)]
    weighted_recipe_choice(recipes)
    assert captured["weights"] == [FAVORITE_WEIGHT, 1]


def test_weighted_recipe_choice_usage_counts_reduce_weight(monkeypatch):
    captured = {}

    def fake_choices(population, weights, k):
        captured["weights"] = weights
        return [population[0]]

    monkeypatch.setattr("services.planning.random.choices", fake_choices)

    recipes = [FakeRecipe(1), FakeRecipe(2)]
    weighted_recipe_choice(recipes, usage_counts={1: 1, 2: 0})
    assert captured["weights"] == [0.5, 1]


def test_weighted_recipe_choice_favorite_and_usage_combine_multiplicatively(monkeypatch):
    captured = {}

    def fake_choices(population, weights, k):
        captured["weights"] = weights
        return [population[0]]

    monkeypatch.setattr("services.planning.random.choices", fake_choices)

    recipes = [FakeRecipe(1, is_favorite=True)]
    weighted_recipe_choice(recipes, usage_counts={1: 2})
    assert captured["weights"] == [FAVORITE_WEIGHT / 3]


# --- assign_balanced_categories ---

class FakeCategory:
    def __init__(self, id):
        self.id = id


class FakeFinalPlanEntry:
    def __init__(self, category_id):
        self.category_id = category_id


def test_assign_balanced_categories_avoids_neighbor_category():
    cats = [FakeCategory(1), FakeCategory(2)]
    final_plan = [None] * 7
    final_plan[0] = FakeFinalPlanEntry(category_id=1)  # Montag ist fest Kategorie 1

    # Dienstag (Index 1) neu zu befüllen - direkter Nachbar von Montag
    assigned = assign_balanced_categories(cats, [1], final_plan)
    assert assigned[1] == 2  # weicht der Nachbarkategorie aus


def test_assign_balanced_categories_falls_back_to_neighbor_if_only_one_category():
    cats = [FakeCategory(1)]
    final_plan = [None] * 7
    final_plan[0] = FakeFinalPlanEntry(category_id=1)

    assigned = assign_balanced_categories(cats, [1], final_plan)
    assert assigned[1] == 1  # keine Alternative vorhanden


def test_assign_balanced_categories_balances_counts_over_multiple_days():
    cats = [FakeCategory(1), FakeCategory(2)]
    final_plan = [None] * 7

    # Alle 7 Tage frei aufzufüllen, keine Nachbarn vorbelegt -> sollte am
    # Ende möglichst gleichmäßig zwischen beiden Kategorien aufgeteilt sein.
    assigned = assign_balanced_categories(cats, list(range(7)), final_plan)
    counts = {1: 0, 2: 0}
    for cid in assigned.values():
        counts[cid] += 1
    assert abs(counts[1] - counts[2]) <= 1


def test_assign_balanced_categories_returns_empty_without_categories():
    assert assign_balanced_categories([], [0, 1], [None] * 7) == {}


def test_assign_balanced_categories_preexisting_counts_influence_balance():
    cats = [FakeCategory(1), FakeCategory(2)]
    final_plan = [None] * 7
    # Kategorie 1 ist bereits stark überrepräsentiert -> neue Tage sollten
    # bevorzugt Kategorie 2 bekommen. Tage 3 und 5 sind NICHT direkt
    # benachbart (anders als 3/4), damit hier ausschließlich die Balance-
    # Regel (Priorität 2) greift, nicht die Nachbarschaftsregel (Priorität 1).
    assigned = assign_balanced_categories(
        cats, [3, 5], final_plan, preexisting_counts={1: 10, 2: 0}
    )
    assert list(assigned.values()) == [2, 2]


# --- choose_recipe / recent_usage_counts / jsonify_* (mit echter DB) ---

def test_choose_recipe_respects_side_dish_pool_separation(app, make_recipe):
    main_id = make_recipe("Hauptgericht", is_side_dish=False)
    side_id = make_recipe("Beilage", is_side_dish=True)

    with app.app_context():
        chosen = choose_recipe(is_side_dish=True, exclude_ids=set())
        assert chosen.id == side_id
        assert chosen.id != main_id


def test_choose_recipe_excludes_given_ids(app, make_recipe):
    cat_id = shared_category(app)
    r1 = make_recipe("R1", category_id=cat_id)
    r2 = make_recipe("R2", category_id=cat_id)

    with app.app_context():
        chosen = choose_recipe(is_side_dish=False, exclude_ids={r1})
        assert chosen.id == r2


def test_choose_recipe_returns_none_when_no_candidates(app, make_recipe):
    r1 = make_recipe("Einziges")
    with app.app_context():
        assert choose_recipe(is_side_dish=False, exclude_ids={r1}) is None


def test_choose_recipe_filters_by_category(app, make_recipe):
    cat_a = shared_category(app, "Kategorie A")
    cat_b = shared_category(app, "Kategorie B")
    r_a = make_recipe("In A", category_id=cat_a)
    make_recipe("In B", category_id=cat_b)

    with app.app_context():
        chosen = choose_recipe(is_side_dish=False, exclude_ids=set(), category_id=cat_a)
        assert chosen.id == r_a


def test_choose_recipe_season_preference_falls_back_when_none_available(app, make_recipe):
    from models import RecipeSeason, db
    from services.seasons import SEASON_PRESETS

    # Einziges Rezept ist nur im Winter verfügbar - unabhängig vom
    # tatsächlichen heutigen Datum darf choose_recipe trotzdem NICHT leer
    # ausgehen (Saison darf die Auswahl nie komplett blockieren).
    recipe_id = make_recipe("Nur Winter")
    with app.app_context():
        db.session.add(RecipeSeason(recipe_id=recipe_id, start_month=SEASON_PRESETS["Winter"][0],
                                     start_day=SEASON_PRESETS["Winter"][1],
                                     end_month=SEASON_PRESETS["Winter"][2],
                                     end_day=SEASON_PRESETS["Winter"][3]))
        db.session.commit()

        chosen = choose_recipe(is_side_dish=False, exclude_ids=set(), prefer_season=True)
        assert chosen is not None
        assert chosen.id == recipe_id


def test_recent_usage_counts_only_counts_within_lookback_window(app, make_recipe):
    from models import PlanDay, db

    recipe_id = make_recipe("Oft gekocht")
    reference = date(2026, 6, 15)

    with app.app_context():
        # Innerhalb der letzten 8 Wochen
        db.session.add(PlanDay(date=reference - timedelta(weeks=2), main_recipe_id=recipe_id, servings=2))
        # Zu lange her (9 Wochen), darf NICHT mitgezählt werden
        db.session.add(PlanDay(date=reference - timedelta(weeks=9), main_recipe_id=recipe_id, servings=2))
        # Genau am reference_date selbst (exklusiv, siehe date < reference_date)
        db.session.add(PlanDay(date=reference, main_recipe_id=recipe_id, servings=2))
        db.session.commit()

        counts = recent_usage_counts([recipe_id], reference, is_side_dish=False)
        assert counts[recipe_id] == 1


def test_recent_usage_counts_side_dish_pool_uses_plan_day_side(app, make_recipe):
    from models import PlanDay, PlanDaySide, db

    recipe_id = make_recipe("Beilage", is_side_dish=True)
    reference = date(2026, 6, 15)

    with app.app_context():
        pd = PlanDay(date=reference - timedelta(weeks=1), servings=2)
        db.session.add(pd)
        db.session.flush()
        db.session.add(PlanDaySide(plan_day_id=pd.id, recipe_id=recipe_id))
        db.session.commit()

        counts = recent_usage_counts([recipe_id], reference, is_side_dish=True)
        assert counts[recipe_id] == 1


def test_recent_usage_counts_empty_ids_returns_empty_dict():
    assert recent_usage_counts([], date.today(), is_side_dish=False) == {}


def test_jsonify_recipe_normalizes_ingredient_names(app, make_recipe):
    from models import Recipe, db

    recipe_id = make_recipe(
        "Suppe",
        calories=300, protein=10.0, carbs=20.0, fat=5.0,
        ingredients=[{"name": "  nudeln", "amount": 200, "unit": "g", "category": "Teigwaren"}],
    )
    with app.app_context():
        recipe = db.session.get(Recipe, recipe_id)
        data = jsonify_recipe(recipe)
        assert data["name"] == "Suppe"
        assert data["calories"] == 300
        assert data["ingredients"] == [{"name": "Nudeln", "amount": 200, "unit": "g", "category": "Teigwaren"}]


def test_jsonify_side_adds_side_id(app, make_recipe):
    from models import PlanDay, PlanDaySide, db

    recipe_id = make_recipe("Salat", is_side_dish=True)
    with app.app_context():
        pd = PlanDay(date=date(2026, 6, 15), servings=2)
        db.session.add(pd)
        db.session.flush()
        side = PlanDaySide(plan_day_id=pd.id, recipe_id=recipe_id)
        db.session.add(side)
        db.session.commit()

        data = jsonify_side(side)
        assert data["side_id"] == side.id
        assert data["name"] == "Salat"


def shared_category(app, name="Testkategorie"):
    """Kleiner, lokaler Helfer (kein pytest-Fixture, absichtlich mit
    unverwechselbarem Namenspräfix) für Tests, die mehrere Rezepte
    DERSELBEN Kategorie brauchen - make_recipe legt ohne category_id sonst
    für jedes Rezept eine eigene neue Kategorie an."""
    from models import Category, db

    with app.app_context():
        cat = Category(name=name)
        db.session.add(cat)
        db.session.commit()
        return cat.id
