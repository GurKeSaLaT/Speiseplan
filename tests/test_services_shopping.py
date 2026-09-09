"""Tests for services/shopping.py: the fixed shopping-list category list."""
from services.shopping import SHOPPING_CATEGORIES, UNCATEGORIZED, infer_category, infer_is_pantry


def test_shopping_categories_order():
    assert SHOPPING_CATEGORIES == [
        "Obst/Gemüse",
        "Backwaren",
        "Milchprodukte",
        "Gewürze",
        "Hygieneartikel",
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


def test_pantry_categories_removed_from_shopping_categories():
    # "Vorratsschrank"/"Verbrauchsartikel" used to imply "pantry item" -
    # removed now that models/recipe.py: Ingredient.is_pantry is its own
    # checkbox instead (see migrations.py:
    # _migrate_remove_pantry_shopping_categories()).
    assert "Vorratsschrank" not in SHOPPING_CATEGORIES
    assert "Verbrauchsartikel" not in SHOPPING_CATEGORIES


def test_shopping_categories_injected_into_templates(client):
    resp = client.get("/manage")
    assert resp.status_code == 200
    # tojson escapes umlauts as \uXXXX instead of raw UTF-8 bytes, see
    # templates/base.html: window.SHOPPING_CATEGORIES.
    assert b"Gew\\u00fcrze" in resp.data
    assert b"Konserven" in resp.data


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


def test_infer_is_pantry_returns_false_without_existing_rows(app, test_plan_id):
    with app.app_context():
        assert infer_is_pantry(test_plan_id, "Salz") is False


def test_infer_is_pantry_returns_true_when_flagged(app, test_plan_id, make_recipe):
    make_recipe("Gewürztes Gericht", ingredients=[
        {"name": "Salz", "amount": 5, "unit": "g", "is_pantry": True},
    ])
    with app.app_context():
        assert infer_is_pantry(test_plan_id, "Salz") is True


def test_infer_is_pantry_resolves_via_alias(app, test_plan_id, make_recipe):
    from services.ingredient_aliases import set_alias

    make_recipe("Gewürztes Gericht", ingredients=[
        {"name": "Meersalz", "amount": 5, "unit": "g", "is_pantry": True},
    ])
    with app.app_context():
        set_alias(test_plan_id, "Meersalz", "Salz")
        assert infer_is_pantry(test_plan_id, "Salz") is True


def test_infer_is_pantry_majority_wins(app, test_plan_id, make_recipe):
    make_recipe("Erstes Gericht", ingredients=[
        {"name": "Zwiebel", "amount": 1, "unit": "Stk", "is_pantry": False},
    ])
    make_recipe("Zweites Gericht", ingredients=[
        {"name": "Zwiebel", "amount": 1, "unit": "Stk", "is_pantry": False},
    ])
    make_recipe("Drittes Gericht", ingredients=[
        {"name": "Zwiebel", "amount": 1, "unit": "Stk", "is_pantry": True},
    ])
    with app.app_context():
        assert infer_is_pantry(test_plan_id, "Zwiebel") is False
