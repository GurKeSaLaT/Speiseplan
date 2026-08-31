"""Fixed category list for the shopping list (supermarket sections).

Unlike Category (recipe categories such as "Fleisch"/"Vegetarisch", which
the user freely creates/deletes via the category management page), this is
a small, deliberately FIXED enumeration with a fixed order - hence a plain
Python list instead of its own database table. Passed to ALL templates via
the context processor inject_shopping_categories() (app.py) and also made
available client-side via window.SHOPPING_CATEGORIES (base.html) for the
client-side sorting/grouping of the shopping list (static/plan.js:
rebuildShoppingList) - so both sides use exactly the same order.
"""

SHOPPING_CATEGORIES = [
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

# Catch-all category for ingredients/items without a category (or with one
# that has since been removed) - always sorts to the end of the shopping
# list, see categorySortIndex() in static/plan.js.
UNCATEGORIZED = "Sonstiges"

# Ingredients in these categories are, as a rule, already stocked at home
# (spices, pantry baking ingredients/nuts/sauces, consumables like plastic
# wrap/trash bags) - they therefore do NOT automatically end up on the
# weekly shopping list, but on a separate "check pantry" list (see
# static/plan-shopping.js: rebuildShoppingList/rebuildPantryList), from
# which individual items can still be pulled onto the shopping list via a
# dedicated button, e.g. if the salt happens to have run out. This applies
# explicitly only to items derived from recipes - a manually added item
# (even one that was just pulled from the pantry list via said button) has
# thereby already declared its "I really need to buy this" intent and
# always ends up directly on the shopping list, regardless of its category
# (see the isExtra check in rebuildShoppingList()). Backwaren (baked goods)
# is deliberately NOT included here: bread/rolls, in contrast, are
# typically a fresh weekly purchase, not a pantry staple.
PANTRY_CATEGORIES = {"Gewürze", "Vorratsschrank", "Verbrauchsartikel"}


def infer_category(plan_id, canonical_name):
    """Guesses the shopping-list category for a canonical ingredient based
    on already existing ingredient rows VISIBLE for plan_id (see
    services/recipe_visibility.py): the non-empty category assigned most
    often under this name (after alias resolution) - or None, if not a
    single row of this canonical ingredient is categorized yet.

    Used when setting an alias in static/ingredient_alias_hint.js (see
    routes/settings.py: api_set_ingredient_alias): this way, all ingredients
    equated to the same name (e.g. "Spaghetti" and "Fusilli" -> "Nudeln")
    automatically end up in the same category, instead of the same
    canonical ingredient appearing in different groups on the shopping list
    depending on the recipe - analogous to infer_reference_unit() in
    services/nutrition.py for the nutrition reference unit."""
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
