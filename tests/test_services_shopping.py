"""Tests for services/shopping.py: the fixed shopping-list categories and
one category per ingredient group (target ingredient plus its aliases)."""
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


# --- group_category_map / apply_group_category: one category per ingredient group ---

def _categories_by_name(recipe_id):
    from models import Ingredient
    return {ing.name: ing.category for ing in Ingredient.query.filter_by(recipe_id=recipe_id)}


def test_group_category_target_rows_win_over_alias_majority(app, test_plan_id, make_recipe):
    from services.ingredient_aliases import set_alias
    from services.shopping import group_category_map

    make_recipe("Ziel", ingredients=[
        {"name": "Frühlingszwiebel", "amount": 1, "unit": "Bund", "category": "Obst/Gemüse"},
    ])
    make_recipe("Alias A", ingredients=[{"name": "Lauchzwiebeln", "amount": 1, "unit": "", "category": "Konserven"}])
    make_recipe("Alias B", ingredients=[{"name": "Lauchzwiebeln", "amount": 2, "unit": "", "category": "Konserven"}])
    with app.app_context():
        set_alias(test_plan_id, "Lauchzwiebeln", "Frühlingszwiebel")
        assert group_category_map(test_plan_id)["Frühlingszwiebel"] == "Obst/Gemüse"


def test_group_category_falls_back_to_alias_when_target_has_none(app, test_plan_id, make_recipe):
    from services.shopping import group_category_map
    from services.ingredient_aliases import set_alias

    make_recipe("Ziel", ingredients=[{"name": "Frühlingszwiebel", "amount": 1, "unit": "", "category": None}])
    make_recipe("Alias", ingredients=[{"name": "Lauchzwiebeln", "amount": 1, "unit": "Bund", "category": "Obst/Gemüse"}])
    with app.app_context():
        set_alias(test_plan_id, "Lauchzwiebeln", "Frühlingszwiebel")
        assert group_category_map(test_plan_id)["Frühlingszwiebel"] == "Obst/Gemüse"


def test_group_category_leaves_out_uncategorized_groups(app, test_plan_id, make_recipe):
    from services.shopping import group_category_map

    make_recipe("Gericht", ingredients=[{"name": "Wasser", "amount": 1, "unit": "l", "category": None}])
    with app.app_context():
        assert "Wasser" not in group_category_map(test_plan_id)


def test_set_alias_adopts_target_category_in_own_recipes(app, test_plan_id, make_recipe):
    from services.ingredient_aliases import set_alias

    target_id = make_recipe("Ziel", ingredients=[
        {"name": "Frühlingszwiebel", "amount": 1, "unit": "Bund", "category": "Obst/Gemüse"},
    ])
    alias_id = make_recipe("Alias", ingredients=[
        {"name": "Lauchzwiebel(n)", "amount": 1, "unit": "", "category": None},
        {"name": "Mehl", "amount": 100, "unit": "g", "category": "Backwaren"},
    ])
    with app.app_context():
        set_alias(test_plan_id, "Lauchzwiebel(n)", "Frühlingszwiebel")
        assert _categories_by_name(alias_id) == {"Lauchzwiebel(n)": "Obst/Gemüse", "Mehl": "Backwaren"}
        assert _categories_by_name(target_id) == {"Frühlingszwiebel": "Obst/Gemüse"}


def test_set_alias_aligns_target_rows_without_category(app, test_plan_id, make_recipe):
    from services.ingredient_aliases import set_alias

    target_id = make_recipe("Ziel", ingredients=[{"name": "Frühlingszwiebel", "amount": 1, "unit": "", "category": None}])
    make_recipe("Alias", ingredients=[{"name": "Lauchzwiebeln", "amount": 1, "unit": "Bund", "category": "Obst/Gemüse"}])
    with app.app_context():
        set_alias(test_plan_id, "Lauchzwiebeln", "Frühlingszwiebel")
        assert _categories_by_name(target_id) == {"Frühlingszwiebel": "Obst/Gemüse"}


def test_set_alias_leaves_other_plans_recipes_untouched(app, test_plan_id, make_recipe, make_user):
    """A recipe shared into this plan from another plan is visible here,
    but its rows belong to the other plan, whose aliases may differ."""
    from models import RecipePlanLink, db
    from services.ingredient_aliases import set_alias

    _, other_plan_id = make_user("Andere")
    make_recipe("Ziel", ingredients=[{"name": "Frühlingszwiebel", "amount": 1, "unit": "", "category": "Obst/Gemüse"}])
    shared_id = make_recipe("Geteilt", plan_id=other_plan_id, ingredients=[
        {"name": "Lauchzwiebeln", "amount": 1, "unit": "", "category": "Konserven"},
    ])
    with app.app_context():
        db.session.add(RecipePlanLink(recipe_id=shared_id, plan_id=test_plan_id))
        db.session.commit()
        set_alias(test_plan_id, "Lauchzwiebeln", "Frühlingszwiebel")
        assert _categories_by_name(shared_id) == {"Lauchzwiebeln": "Konserven"}


def test_plan_json_uses_group_category_for_existing_aliases(app, test_plan_id, make_recipe):
    """Existing data where alias rows still carry another category: the
    shopping list (plan page JSON) groups them by the target's category."""
    from models import IngredientAlias, Recipe, db
    from services.planning import jsonify_recipe

    recipe_id = make_recipe("Gericht", ingredients=[
        {"name": "Frühlingszwiebel", "amount": 1, "unit": "Bund", "category": "Obst/Gemüse"},
        {"name": "Lauchzwiebeln", "amount": 50, "unit": "g", "category": None},
    ])
    with app.app_context():
        # Inserted directly, as on tower before this fix: no category sync ran.
        db.session.add(IngredientAlias(plan_id=test_plan_id, raw_name="Lauchzwiebeln", canonical_name="Frühlingszwiebel"))
        db.session.commit()
        data = jsonify_recipe(db.session.get(Recipe, recipe_id), test_plan_id)
        assert [(i["name"], i["category"]) for i in data["ingredients"]] == [
            ("Frühlingszwiebel", "Obst/Gemüse"), ("Frühlingszwiebel", "Obst/Gemüse"),
        ]
