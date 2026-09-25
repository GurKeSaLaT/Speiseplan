"""Recipe nutrition computed from per-ingredient references.

References (IngredientNutrition) are stored per canonical, alias-resolved
ingredient and always per 100 g, 100 ml or 1 piece. For matching, every
piece-like unit (can, bunch, pinch, empty, ...) counts as a piece -
matching only; the shopping list still keeps those spellings apart.
Calories are never stored, always computed from protein/carbs/fat.
"""

from collections import Counter

from models import Ingredient, IngredientAlias, IngredientNutrition, db
from services.ingredient_aliases import get_all_aliases, normalize_ingredient_name, normalize_name
from services.recipe_visibility import visible_recipe_ids_subquery
from services.units import NON_CONVERTIBLE_UNITS, normalize_amount_unit

# reference_amount always follows from the unit, it is never entered.
REFERENCE_BASES = {"g": 100, "ml": 100, "Stk": 1}

_PIECE_LIKE_UNITS = NON_CONVERTIBLE_UNITS | {''}


def _normalize_unit(unit):
    key = (unit or '').strip().lower()
    return 'stk' if key in _PIECE_LIKE_UNITS else key


def compute_calories(protein, carbs, fat):
    """Atwater: 4 kcal/g protein and carbs, 9 kcal/g fat. None counts as 0."""
    return round((protein or 0) * 4 + (carbs or 0) * 4 + (fat or 0) * 9)


def get_nutrition_entry(plan_id, name):
    canonical = normalize_ingredient_name(plan_id, name)
    return IngredientNutrition.query.filter_by(plan_id=plan_id, canonical_name=canonical).first()


def get_all_nutrition_entries(plan_id):
    """{canonical_name: {...}} for window.INGREDIENT_NUTRITION."""
    return {
        e.canonical_name: {
            "reference_amount": e.reference_amount, "reference_unit": e.reference_unit,
            "calories": compute_calories(e.protein, e.carbs, e.fat),
            "protein": e.protein, "carbs": e.carbs, "fat": e.fat,
        }
        for e in IngredientNutrition.query.filter_by(plan_id=plan_id).all()
    }


def set_nutrition(plan_id, name, reference_unit, protein, carbs, fat):
    """Upsert by canonical name; an unknown reference_unit falls back to "g"."""
    canonical = normalize_ingredient_name(plan_id, name)
    reference_unit = (reference_unit or 'g').strip()
    if reference_unit not in REFERENCE_BASES:
        reference_unit = 'g'

    entry = IngredientNutrition.query.filter_by(plan_id=plan_id, canonical_name=canonical).first()
    if not entry:
        entry = IngredientNutrition(plan_id=plan_id, canonical_name=canonical)
        db.session.add(entry)
    entry.reference_amount = REFERENCE_BASES[reference_unit]
    entry.reference_unit = reference_unit
    entry.protein = protein
    entry.carbs = carbs
    entry.fat = fat
    db.session.commit()
    return entry


def list_alias_canonical_names(plan_id):
    """Names that at least one alias points to."""
    rows = db.session.query(IngredientAlias.canonical_name).filter_by(plan_id=plan_id).distinct().all()
    return sorted({r[0] for r in rows})


def infer_reference_unit(plan_id, canonical_name):
    """Most common unit family (g/ml/Stk) of this ingredient in the plan's
    recipes, "g" if unused. Slow (queries per ingredient) - for many names
    use infer_reference_units_for_plan()."""
    families = []
    visible_ingredients = Ingredient.query.filter(Ingredient.recipe_id.in_(visible_recipe_ids_subquery(plan_id)))
    for ing in visible_ingredients:
        if normalize_ingredient_name(plan_id, ing.name) != canonical_name:
            continue
        _, unit = normalize_amount_unit(1, ing.unit)
        families.append(unit if unit in ('g', 'ml') else 'Stk')
    if not families:
        return 'g'
    return Counter(families).most_common(1)[0][0]


def infer_reference_units_for_plan(plan_id):
    """{canonical_name: family} for every used ingredient in one pass.
    Unused names have no key; callers default to "g"."""
    aliases = get_all_aliases(plan_id)
    visible_ingredients = Ingredient.query.filter(Ingredient.recipe_id.in_(visible_recipe_ids_subquery(plan_id)))

    families_by_name = {}
    for ing in visible_ingredients:
        canonical = aliases.get(normalize_name(ing.name), normalize_name(ing.name))
        _, unit = normalize_amount_unit(1, ing.unit)
        family = unit if unit in ('g', 'ml') else 'Stk'
        families_by_name.setdefault(canonical, []).append(family)

    return {
        name: Counter(families).most_common(1)[0][0]
        for name, families in families_by_name.items()
    }


def compute_recipe_nutrition(plan_id, ingredient_rows, servings):
    """Per-serving nutrition from ingredient rows (dicts or Ingredient
    objects), using plan_id's references. Amounts are for all servings.
    Rows without a reference or with a mismatching unit contribute 0.
    Calories are computed from the rounded per-serving values so all four
    numbers stay consistent.
    """
    totals = {"protein": 0.0, "carbs": 0.0, "fat": 0.0}
    for ing in ingredient_rows:
        name = ing["name"] if isinstance(ing, dict) else ing.name
        amount = ing["amount"] if isinstance(ing, dict) else ing.amount
        unit = ing["unit"] if isinstance(ing, dict) else ing.unit

        entry = get_nutrition_entry(plan_id, name)
        if not entry or not entry.reference_amount:
            continue
        if _normalize_unit(unit) != _normalize_unit(entry.reference_unit):
            continue

        factor = (amount or 0) / entry.reference_amount
        totals["protein"] += factor * (entry.protein or 0)
        totals["carbs"] += factor * (entry.carbs or 0)
        totals["fat"] += factor * (entry.fat or 0)

    servings = servings or 1
    protein = round(totals["protein"] / servings, 1)
    carbs = round(totals["carbs"] / servings, 1)
    fat = round(totals["fat"] / servings, 1)
    return {
        "calories": compute_calories(protein, carbs, fat),
        "protein": protein,
        "carbs": carbs,
        "fat": fat,
    }
