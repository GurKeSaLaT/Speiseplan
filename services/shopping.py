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


def group_category_map(plan_id):
    """{canonical name: category} over all ingredient rows visible to
    plan_id, so an ingredient and all its aliases share one shopping-list
    group. The target ingredient's own rows win (most common category among
    rows literally named like the canonical name); only if those carry none,
    the most common category of the whole group applies. Groups without
    any categorized row are left out."""
    from collections import Counter
    from models import Ingredient, db
    from services.ingredient_aliases import get_all_aliases, normalize_name
    from services.recipe_visibility import visible_recipe_ids_subquery

    aliases = get_all_aliases(plan_id)
    rows = (
        db.session.query(Ingredient.name, Ingredient.category)
        .filter(Ingredient.recipe_id.in_(visible_recipe_ids_subquery(plan_id)), Ingredient.category.isnot(None))
        .all()
    )
    target_counts, group_counts = {}, {}
    for name, category in rows:
        if not category:
            continue
        key = normalize_name(name)
        canonical = aliases.get(key, key)
        group_counts.setdefault(canonical, Counter())[category] += 1
        if key == canonical:
            target_counts.setdefault(canonical, Counter())[category] += 1
    return {
        canonical: (target_counts.get(canonical) or counts).most_common(1)[0][0]
        for canonical, counts in group_counts.items()
    }


def infer_category(plan_id, canonical_name):
    """The shopping-list category of this canonical ingredient (see
    group_category_map), None if none of its rows is categorized."""
    return group_category_map(plan_id).get(canonical_name)


def apply_group_category(plan_id, canonical_name):
    """Writes the group's category (group_category_map) onto every row of
    the group in recipes owned by plan_id; returns how many rows changed.
    Rows of other plans' recipes stay untouched - aliases are per plan, and
    those plans may group the ingredient differently."""
    from models import Ingredient, Recipe, db
    from services.ingredient_aliases import get_all_aliases, normalize_name

    category = infer_category(plan_id, canonical_name)
    if category is None:
        return 0
    aliases = get_all_aliases(plan_id)
    own_rows = Ingredient.query.join(Recipe, Ingredient.recipe_id == Recipe.id).filter(Recipe.owner_plan_id == plan_id)
    changed = 0
    for ing in own_rows:
        key = normalize_name(ing.name)
        if aliases.get(key, key) == canonical_name and ing.category != category:
            ing.category = category
            changed += 1
    if changed:
        db.session.commit()
    return changed


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
