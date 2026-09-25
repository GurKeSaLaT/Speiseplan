"""Per-plan ingredient aliases: map spellings (e.g. "Spaghetti",
"Fusilli") to a shared name ("Nudeln") so the shopping list merges them.
Only affects the shopping list and nutrition lookups; recipes keep
showing their own spelling. The viewing plan's aliases always apply.
"""

from models import Ingredient, IngredientAlias, Recipe, db
from services.recipe_visibility import visible_recipe_ids_subquery


def normalize_name(raw_name):
    """Lookup key for names: stripped and title-cased."""
    return (raw_name or '').strip().title()


def normalize_ingredient_name(plan_id, raw_name):
    """The alias target if one exists, else the normalized name itself."""
    key = normalize_name(raw_name)
    alias = IngredientAlias.query.filter_by(plan_id=plan_id, raw_name=key).first()
    return alias.canonical_name if alias else key


def list_known_ingredient_names(plan_id):
    """Sorted, normalized names of all ingredients in recipes visible to plan_id."""
    names = (
        db.session.query(Ingredient.name)
        .filter(Ingredient.recipe_id.in_(visible_recipe_ids_subquery(plan_id)))
        .distinct().all()
    )
    return sorted({normalize_name(n[0]) for n in names if n[0] and n[0].strip()})


def get_all_aliases(plan_id):
    """{raw_name: canonical_name}"""
    return {a.raw_name: a.canonical_name for a in IngredientAlias.query.filter_by(plan_id=plan_id).all()}


def recipes_by_ingredient_name(plan_id):
    """{normalized literal ingredient name: [(recipe_id, recipe_name), ...]}
    for all visible recipes, in a single query (a per-name query here once
    made the ingredients page take 30+ seconds)."""
    rows = (
        db.session.query(Ingredient.name, Recipe.id, Recipe.name)
        .join(Recipe, Ingredient.recipe_id == Recipe.id)
        .filter(Ingredient.recipe_id.in_(visible_recipe_ids_subquery(plan_id)))
        .all()
    )
    recipes_by_name = {}
    for ingredient_name, recipe_id, recipe_name in rows:
        key = normalize_name(ingredient_name)
        seen_ids = {rid for rid, _ in recipes_by_name.get(key, [])}
        if recipe_id not in seen_ids:
            recipes_by_name.setdefault(key, []).append((recipe_id, recipe_name))
    for entries in recipes_by_name.values():
        entries.sort(key=lambda pair: pair[1])
    return recipes_by_name


def prune_orphaned_aliases(plan_id, recipes_by_name):
    """Deletes aliases whose raw_name no visible recipe uses anymore (e.g.
    after the ingredient was renamed) - aliases are plain strings, so
    nothing else cleans them up. Returns the removed raw names."""
    orphaned_raw_names = [
        raw_name for raw_name in get_all_aliases(plan_id)
        if not recipes_by_name.get(raw_name)
    ]
    for raw_name in orphaned_raw_names:
        delete_alias(plan_id, raw_name)
    return orphaned_raw_names


def set_alias(plan_id, raw_name, canonical_name):
    """Upsert; aliasing a name to itself deletes the alias instead."""
    key = normalize_name(raw_name)
    canonical = normalize_name(canonical_name)
    if not key:
        return
    if canonical == key:
        delete_alias(plan_id, key)
        return

    alias = IngredientAlias.query.filter_by(plan_id=plan_id, raw_name=key).first()
    if alias:
        alias.canonical_name = canonical
    else:
        db.session.add(IngredientAlias(plan_id=plan_id, raw_name=key, canonical_name=canonical))
    db.session.commit()


def delete_alias(plan_id, raw_name):
    key = normalize_name(raw_name)
    IngredientAlias.query.filter_by(plan_id=plan_id, raw_name=key).delete()
    db.session.commit()
