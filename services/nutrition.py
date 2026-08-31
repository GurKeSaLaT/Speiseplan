"""Automatic nutrition calculation from a recipe's ingredients.

Recipe.calories/.protein/.carbs/.fat (see models.py) are, by default, NO
LONGER maintained by hand, but are calculated when a recipe is saved from
the stored nutrition references of its ingredients (see
compute_recipe_nutrition(), called from routes/recipes.py: add_recipe()/
edit_recipe()) - Recipe.nutrition_override=True switches this off for a
single recipe and leaves the manually entered values in place (e.g. for a
ready-made product where only the nutrition value on the package is known).

The nutrition references themselves (IngredientNutrition, see models.py)
are stored per CANONICAL ingredient (services/ingredient_aliases.py:
normalize_ingredient_name()) - for an alias-grouped ingredient like
"Pasta", that means ONE shared entry instead of one per spelling such as
"Spaghetti"/"Fusilli". The management page (/manage/ingredient-nutrition,
see routes/settings.py) deliberately shows ONLY the actual alias target
names (list_alias_canonical_names()) - unaliased individual ingredients
instead get their nutrition value added later directly while entering the
ingredient, via the inline hint (see static/ingredient_alias_hint.js).

Reference basis is ALWAYS 100 g / 100 ml / 1 pc (REFERENCE_BASES below) -
freely chosen reference amounts (e.g. "1 cup", "1 can", "1 pinch") were
deliberately rejected: they are neither comparable to one another nor can
their size be displayed compactly enough on the management page (see
set_nutrition()). "pc" (piece) is deliberately construed more broadly than
just "one egg" or "one slice": a cup, a can, a bunch, or a pinch are each,
in their own right, a countable, natural measure for THIS SPECIFIC
ingredient - the calorie value is calibrated per ingredient anyway (e.g.
"1 pc egg" = 1 egg, "1 pc kidney beans" = 1 can of kidney beans), not
literally limited to a piece in the sense of egg/slice. For the actual
calculation (compute_recipe_nutrition), ALL piece-based unit spellings
from services/units.py: NON_CONVERTIBLE_UNITS therefore count (pc, piece,
stick, clove, slice, bunch, can, packet, cup, pinch, dash, jar, cube,
scoop, leaf, pack, ...) as well as an empty unit as equivalent to "pc"
(see _normalize_unit) - this is deliberately ONLY a relaxation for the
nutrition MATCHING, NOT for services/units.py: normalize_amount_unit()
itself, since different spellings should continue to be listed as
separate line items on the shopping list.

Calories are NOWHERE maintained or summed as their own value - neither on
IngredientNutrition nor on Recipe.calories - but are always calculated
from protein/carbohydrates/fat (compute_calories() below, the Atwater
rule of thumb: 4 kcal per g protein/carbohydrates, 9 kcal per g fat). An
additionally maintained calorie value would only be redundant and could
contradict the other three values.
"""

from collections import Counter

from models import Ingredient, IngredientAlias, IngredientNutrition, db
from services.ingredient_aliases import normalize_ingredient_name
from services.recipe_visibility import visible_recipe_ids_subquery
from services.units import NON_CONVERTIBLE_UNITS, normalize_amount_unit

# Reference basis per unit - see module docstring. set_nutrition() enforces
# reference_unit from these three keys and ALWAYS derives reference_amount
# from it (never freely enterable).
REFERENCE_BASES = {"g": 100, "ml": 100, "Stk": 1}

# Unit spellings that count as "1 Stk" during nutrition MATCHING (not when
# saving the ingredient line itself!) - see module docstring.
# NON_CONVERTIBLE_UNITS is already normalized without a trailing period/
# plural s (see services/units.py: _normalize_key), so "msp"/"prise" also
# cover "Msp."/"Prisen".
_PIECE_LIKE_UNITS = NON_CONVERTIBLE_UNITS | {''}


def _normalize_unit(unit):
    """For the unit comparison during calculation (see
    compute_recipe_nutrition) - case and whitespace should not matter
    ("g" should e.g. also match "G" or " g "), and piece-based spellings
    should all match against a "Stk" reference (see module docstring)."""
    key = (unit or '').strip().lower()
    return 'stk' if key in _PIECE_LIKE_UNITS else key


def compute_calories(protein, carbs, fat):
    """Calculates calories from protein/carbohydrates/fat using the
    Atwater rule of thumb (4 kcal per g protein/carbohydrates, 9 kcal per
    g fat) - the only place where calories are determined at all (see
    module docstring). None values count as 0, so callers don't have to
    guard against that themselves beforehand."""
    return round((protein or 0) * 4 + (carbs or 0) * 4 + (fat or 0) * 9)


def get_nutrition_entry(plan_id, name):
    """Returns the nutrition entry of ONE plan for an ingredient (any
    spelling - resolved internally to its canonical form via
    normalize_ingredient_name()), or None if none has been stored yet."""
    canonical = normalize_ingredient_name(plan_id, name)
    return IngredientNutrition.query.filter_by(plan_id=plan_id, canonical_name=canonical).first()


def get_all_nutrition_entries(plan_id):
    """All nutrition references maintained for plan_id as a dict
    {canonical name: {reference_amount, reference_unit, calories, protein,
    carbs, fat}} - the basis for window.INGREDIENT_NUTRITION (see
    static/ingredient_alias_hint.js), so that the inline hint while
    entering an ingredient knows, without an extra request, for which ones
    a nutrition value has already been stored. calories here is not a
    stored value, but is calculated only here for display from
    protein/carbs/fat (see compute_calories())."""
    return {
        e.canonical_name: {
            "reference_amount": e.reference_amount, "reference_unit": e.reference_unit,
            "calories": compute_calories(e.protein, e.carbs, e.fat),
            "protein": e.protein, "carbs": e.carbs, "fat": e.fat,
        }
        for e in IngredientNutrition.query.filter_by(plan_id=plan_id).all()
    }


def set_nutrition(plan_id, name, reference_unit, protein, carbs, fat):
    """Creates or updates a nutrition entry for plan_id - name is
    normalized to its canonical form the same way as during lookup, so
    that "Spaghetti" and "Fusilli" (both -> "Pasta", if alias-grouped)
    hit the same entry.

    reference_amount is deliberately NOT a parameter here - it always
    results directly from reference_unit (see REFERENCE_BASES/module
    docstring). An unknown/empty reference_unit value falls back to "g"
    instead of raising an error (e.g. with tampered form data). calories
    is also deliberately NOT a parameter here - it is never stored
    anywhere, see module docstring."""
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
    """All canonical names that AT LEAST ONE ingredient references via
    IngredientAlias WITHIN plan_id (the actual alias target names like
    "Pasta"/"Oil", NOT every single unaliased individual ingredient) -
    exactly the set the nutrition management page should list."""
    rows = db.session.query(IngredientAlias.canonical_name).filter_by(plan_id=plan_id).distinct().all()
    return sorted({r[0] for r in rows})


def infer_reference_unit(plan_id, canonical_name):
    """Guesses a sensible default reference unit (g/ml/Stk, see
    REFERENCE_BASES) for a NEW nutrition entry: which of the three
    families is actually used most often under this canonical ingredient
    (among the recipes VISIBLE for plan_id, see
    services/recipe_visibility.py). Each ingredient line is checked for
    this via services/units.py: normalize_amount_unit() against its mass/
    volume family (correctly covers e.g. "kg" or "tbsp" as mass/volume,
    not just the already-canonical "g"/"ml") - everything else (Stk,
    bunch, can, pinch, an empty unit, ...) counts as "Stk", since it is
    not suited for a 100g/100ml reference anyway. Falls back to "g" if no
    ingredient line exists for it yet at all."""
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


def compute_recipe_nutrition(plan_id, ingredient_rows, servings):
    """Calculates the nutrition PER SERVING from a list of ingredient
    lines (dicts/objects with .name/.amount/.unit, e.g. the ones just
    submitted in the form or recipe.ingredients of an existing recipe)
    using the nutrition references OF plan_id - for a recipe included via
    RecipePlanLink, the references of the plan currently being saved to
    apply, not those of its owning plan.

    Ingredient.amount applies, per the model documentation, to the WHOLE
    number of servings, while Recipe.calories/.protein/.carbs/.fat apply
    PER serving - the summed ingredient contributions are therefore
    divided by servings at the end.

    An ingredient with no nutrition entry OR with a unit that deviates
    from the stored reference (e.g. reference in "g", but this line in
    "Stk") contributes 0 instead of raising an error - the caller thus
    always sees a complete (though possibly incomplete) result, never a
    crash due to missing data.

    calories is NOT summed separately (IngredientNutrition no longer has
    its own calories column at all), but is only calculated at the very
    end from the already fully rounded protein/carbs/fat-PER-SERVING
    values (see compute_calories()) - this way, the displayed calorie
    value always matches exactly the also-displayed protein/carbs/fat
    values, instead of deviating slightly due to separate rounding.
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
