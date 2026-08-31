"""Tests for services/shopping.py: the fixed shopping-list category list."""
from services.shopping import PANTRY_CATEGORIES, SHOPPING_CATEGORIES, UNCATEGORIZED, infer_category


def test_shopping_categories_order():
    assert SHOPPING_CATEGORIES == [
        "Obst/Gemüse",
        "Backwaren",
        "Milchprodukte",
        "Gewürze",
        "Vorratsschrank",
        "Hygieneartikel",
        "Verbrauchsartikel",
        "Getränke",
        "Teigwaren",
        "Konserven",
        "Tiefkühlware",
    ]


def test_uncategorized_not_part_of_fixed_list():
    # "Sonstiges" is the catch-all category, sorted separately to the end
    # (see categorySortIndex() in static/plan-shopping.js) - it's not
    # its own entry in SHOPPING_CATEGORIES.
    assert UNCATEGORIZED not in SHOPPING_CATEGORIES


def test_pantry_categories_are_valid_shopping_categories():
    # Every pantry category must also be a genuine shopping-list category
    # (otherwise it wouldn't show up in the category dropdown, for example).
    assert PANTRY_CATEGORIES == {"Gewürze", "Vorratsschrank", "Verbrauchsartikel"}
    assert PANTRY_CATEGORIES.issubset(set(SHOPPING_CATEGORIES))
    # "Backwaren" is deliberately NOT part of the pantry categories - bread
    # is typically a fresh weekly purchase.
    assert "Backwaren" not in PANTRY_CATEGORIES


def test_shopping_categories_injected_into_templates(client):
    resp = client.get("/manage")
    assert resp.status_code == 200
    # tojson escapes umlauts as \uXXXX instead of raw UTF-8 bytes, see
    # templates/base.html: window.SHOPPING_CATEGORIES.
    assert b"Gew\\u00fcrze" in resp.data
    assert b"Verbrauchsartikel" in resp.data


def test_pantry_categories_injected_into_templates(client):
    resp = client.get("/manage")
    assert resp.status_code == 200
    assert b"window.PANTRY_CATEGORIES" in resp.data
    assert b"Gew\\u00fcrze" in resp.data
    assert b"Verbrauchsartikel" in resp.data


def test_infer_category_returns_none_without_existing_rows(app, test_plan_id):
    with app.app_context():
        assert infer_category(test_plan_id, "Nudeln") is None


def test_infer_category_returns_existing_category(app, test_plan_id, make_recipe):
    make_recipe("Nudelgericht", ingredients=[
        {"name": "Spaghetti", "amount": 500, "unit": "g", "category": "Teigwaren"},
    ])
    with app.app_context():
        assert infer_category(test_plan_id, "Spaghetti") == "Teigwaren"


def test_infer_category_resolves_via_alias(app, test_plan_id, make_recipe):
    """An ingredient row stays stored in the DB under its original name
    ("Spaghetti") - infer_category must still find it when asked for the
    ALIAS-TARGET category ("Nudeln"), since it internally resolves every
    row via normalize_ingredient_name()."""
    from services.ingredient_aliases import set_alias

    make_recipe("Nudelgericht", ingredients=[
        {"name": "Spaghetti", "amount": 500, "unit": "g", "category": "Teigwaren"},
    ])
    with app.app_context():
        set_alias(test_plan_id, "Spaghetti", "Nudeln")
        assert infer_category(test_plan_id, "Nudeln") == "Teigwaren"


def test_infer_category_ignores_uncategorized_rows(app, test_plan_id, make_recipe):
    make_recipe("Nudelgericht", ingredients=[
        {"name": "Fusilli", "amount": 300, "unit": "g", "category": None},
    ])
    with app.app_context():
        assert infer_category(test_plan_id, "Fusilli") is None


def test_infer_category_majority_wins(app, test_plan_id, make_recipe):
    make_recipe("Erstes Gericht", ingredients=[
        {"name": "Nudeln", "amount": 200, "unit": "g", "category": "Teigwaren"},
    ])
    make_recipe("Zweites Gericht", ingredients=[
        {"name": "Nudeln", "amount": 300, "unit": "g", "category": "Teigwaren"},
    ])
    make_recipe("Drittes Gericht", ingredients=[
        {"name": "Nudeln", "amount": 100, "unit": "g", "category": "Konserven"},
    ])
    with app.app_context():
        assert infer_category(test_plan_id, "Nudeln") == "Teigwaren"


def test_infer_category_ignores_other_plans_recipes(app, test_plan_id, make_recipe, make_user):
    _, other_plan_id = make_user("Andere")
    make_recipe("Fremdes Gericht", plan_id=other_plan_id, ingredients=[
        {"name": "Nudeln", "amount": 200, "unit": "g", "category": "Teigwaren"},
    ])
    with app.app_context():
        assert infer_category(test_plan_id, "Nudeln") is None
