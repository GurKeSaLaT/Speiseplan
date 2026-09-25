"""Fixed shopping-list categories (supermarket sections) in shelf order,
shared with the client via window.SHOPPING_CATEGORIES.

Ingredients marked is_pantry go to a separate "check pantry" list instead
of the shopping list; manually added items always go on the shopping list.
"""

SHOPPING_CATEGORIES = [
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

# For missing or removed categories; always sorted last.
UNCATEGORIZED = "Sonstiges"


def infer_category(plan_id, canonical_name):
    """Most common category among existing rows of this canonical ingredient
    (None if none is categorized) - so merged spellings land in the same
    shopping-list group."""
    from collections import Counter
    from models import Ingredient
    from services.ingredient_aliases import normalize_ingredient_name
    from services.recipe_visibility import visible_recipe_ids_subquery

    visible_ingredients = Ingredient.query.filter(Ingredient.recipe_id.in_(visible_recipe_ids_subquery(plan_id)))
    categories = [
        ing.category for ing in visible_ingredients
        if ing.category and normalize_ingredient_name(plan_id, ing.name) == canonical_name
    ]
    if not categories:
        return None
    return Counter(categories).most_common(1)[0][0]


def infer_is_pantry(plan_id, canonical_name):
    """Majority pantry flag among existing rows of this canonical ingredient."""
    from collections import Counter
    from models import Ingredient
    from services.ingredient_aliases import normalize_ingredient_name
    from services.recipe_visibility import visible_recipe_ids_subquery

    visible_ingredients = Ingredient.query.filter(Ingredient.recipe_id.in_(visible_recipe_ids_subquery(plan_id)))
    flags = [
        ing.is_pantry for ing in visible_ingredients
        if normalize_ingredient_name(plan_id, ing.name) == canonical_name
    ]
    if not flags:
        return False
    return Counter(flags).most_common(1)[0][0]
