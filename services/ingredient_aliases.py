"""Ingredient equating for the shopping list: maps concrete ingredient
names (e.g. "Spaghetti", "Fusilli") to a shared, higher-level name (e.g.
"Pasta"), so that the shopping list combines them into ONE line item
instead of several. See models.py: IngredientAlias for the storage and
routes/settings.py for the management page where users maintain this
mapping themselves.

Applies exclusively to the shopping list (services/planning.py:
jsonify_recipe) - the ingredient list of a single recipe (create/edit
form) still shows the originally entered name, unaffected by any mapping
maintained here.

Each plan maintains its OWN equating (see models.py:
IngredientAlias.plan_id) - the same ingredient can be grouped differently
(or not at all) in two plans. For a recipe that is visible in multiple
plans via RecipePlanLink, viewing it ALWAYS applies the equating of the
CURRENTLY ACTIVE plan, not that of its owning plan.
"""

from models import Ingredient, IngredientAlias, db
from services.recipe_visibility import visible_recipe_ids_subquery


def normalize_name(raw_name):
    """Same normalization as jsonify_recipe() uses for ingredient names
    (.strip().title()) - case and whitespace should not matter when
    looking up/creating an alias. Public (no more leading underscore),
    since routes/settings.py also needs it for the AJAX response of
    api_set_ingredient_alias()."""
    return (raw_name or '').strip().title()


def normalize_ingredient_name(plan_id, raw_name):
    """Returns the name to use for the shopping list: the canonical name
    maintained (in the context of plan_id), if raw_name (after
    normalization) has an alias entry, otherwise raw_name itself
    (normalized) - an unknown ingredient name thus simply stays itself,
    with no grouping being the default case."""
    key = normalize_name(raw_name)
    alias = IngredientAlias.query.filter_by(plan_id=plan_id, raw_name=key).first()
    return alias.canonical_name if alias else key


def list_known_ingredient_names(plan_id):
    """All ingredient names currently used in a recipe VISIBLE to plan_id
    (normalized, deduplicated, alphabetical) - the basis for the
    management page, which shows EVERY known name as a row, even without
    an existing alias (see routes/settings.py:
    ingredient_aliases_view). "Visible" includes both the plan's own
    recipes and ones included via RecipePlanLink (see
    services/recipe_visibility.py)."""
    names = (
        db.session.query(Ingredient.name)
        .filter(Ingredient.recipe_id.in_(visible_recipe_ids_subquery(plan_id)))
        .distinct().all()
    )
    return sorted({normalize_name(n[0]) for n in names if n[0] and n[0].strip()})


def get_all_aliases(plan_id):
    """All alias mappings maintained for plan_id as a dict {raw_name:
    canonical_name}."""
    return {a.raw_name: a.canonical_name for a in IngredientAlias.query.filter_by(plan_id=plan_id).all()}


def set_alias(plan_id, raw_name, canonical_name):
    """Creates or updates a mapping for plan_id. If canonical_name (after
    normalization) is identical to raw_name, any existing alias is
    DELETED instead - "mapped to itself" is equivalent to "no alias",
    which avoids unnecessary rows."""
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
    """Removes a mapping again (the ingredient name then only groups with
    itself afterward) - no error if none exists."""
    key = normalize_name(raw_name)
    IngredientAlias.query.filter_by(plan_id=plan_id, raw_name=key).delete()
    db.session.commit()
