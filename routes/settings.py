"""Settings pages of the app: currently three thematically separate
areas that share this one blueprint (analogous to the routes/plan/
package - but here in a single, manageable file instead of its own
package, since all three areas are small):

1. Units (units_view/update_units): in which unit ingredient amounts
   should be displayed (mass: grams/kilograms, volume: milliliters/
   liters) - see services/units.py for the actual conversion and
   services/settings.py for the storage. Does NOT change how amounts
   are stored internally (always canonical g/ml), only how they are
   displayed in forms/the shopping list.

2. Equating ingredients (ingredient_aliases_view/update_ingredient_aliases):
   which concrete ingredient names (e.g. "spaghetti", "fusilli") should
   count as the same item for the shopping list (e.g. "pasta") - see
   services/ingredient_aliases.py. Does NOT change the ingredient names
   shown in a recipe, only the grouping on the shopping list.

3. Nutrition (ingredient_nutrition_view/update_ingredient_nutrition): the
   nutrition reference per canonical ingredient (see services/nutrition.py),
   from which recipe nutrition values are automatically calculated (see
   routes/recipes.py: add_recipe()/edit_recipe()).

All three areas are separated PER PLAN (see models/settings.py: AppSettings.
plan_id/IngredientAlias.plan_id/IngredientNutrition.plan_id) - each page
shows a tab switcher when a user has access to more than one plan (see
services/auth.py: selected_plan_id/user_plan_memberships) and acts on
the CURRENTLY selected plan, not necessarily the otherwise active one
(current_plan()).
"""

from flask import Blueprint, redirect, render_template, request, url_for
from flask_babel import gettext as _

from services.auth import current_plan, current_user, selected_plan_id, user_plan_memberships
from services.ingredient_aliases import (
    get_all_aliases, list_known_ingredient_names, normalize_ingredient_name, normalize_name, set_alias,
)
from services.nutrition import (
    compute_calories, get_all_nutrition_entries, infer_reference_unit, list_alias_canonical_names, set_nutrition,
)
from services.settings import get_settings, update_display_units
from services.shopping import infer_category
from services.units import DISPLAY_UNIT_CHOICES, MASS, VOLUME

settings_bp = Blueprint('settings', __name__)


@settings_bp.route('/manage/units')
def units_view():
    """Shows the currently chosen display units of the selected plan
    along with the respectively available options (DISPLAY_UNIT_CHOICES) -
    the template builds the two radio groups from these."""
    user = current_user()
    plan_id = selected_plan_id(request.args, user)
    settings = get_settings(plan_id)
    return render_template(
        'units_manage.html', settings=settings, plan_id=plan_id, user_plans=user_plan_memberships(user),
        mass_choices=DISPLAY_UNIT_CHOICES[MASS], volume_choices=DISPLAY_UNIT_CHOICES[VOLUME],
    )


@settings_bp.route('/update-units', methods=['POST'])
def update_units():
    """Saves the display units chosen in the form for the selected plan.
    An invalid value (e.g. from manipulated form data) is rejected by
    update_display_units() - the setting then remains unchanged, instead
    of throwing a 500 or saving a nonsensical value."""
    plan_id = selected_plan_id(request.form, current_user())
    mass_unit = request.form.get('mass_unit', '')
    volume_unit = request.form.get('volume_unit', '')
    update_display_units(plan_id, mass_unit, volume_unit)
    return redirect(url_for('settings.units_view', plan_id=plan_id))


@settings_bp.route('/manage/ingredient-aliases')
def ingredient_aliases_view():
    """Shows EVERY ingredient name currently used in any recipe visible
    for the selected plan as its own row with an editable "counts as"
    field, pre-filled with the maintained canonical name or (without an
    existing alias) the name itself - this makes it easy to see at a
    glance which names are already assigned to a group."""
    user = current_user()
    plan_id = selected_plan_id(request.args, user)
    aliases = get_all_aliases(plan_id)
    rows = [
        {"raw_name": name, "canonical_name": aliases.get(name, name)}
        for name in list_known_ingredient_names(plan_id)
    ]
    return render_template(
        'ingredient_aliases_manage.html', rows=rows, plan_id=plan_id, user_plans=user_plan_memberships(user),
    )


@settings_bp.route('/update-ingredient-aliases', methods=['POST'])
def update_ingredient_aliases():
    """Saves ALL rows of the form at once (raw_name[]/canonical_name[],
    parallel lists like the ingredient rows of the recipe forms) instead
    of one button per row - with potentially hundreds of ingredient names,
    a separate round trip per row would be impractical. set_alias()
    automatically deletes an alias again if the entered name matches the
    original (see there)."""
    plan_id = selected_plan_id(request.form, current_user())
    raw_names = request.form.getlist('raw_name[]')
    canonical_names = request.form.getlist('canonical_name[]')
    for raw_name, canonical_name in zip(raw_names, canonical_names):
        set_alias(plan_id, raw_name, canonical_name)
    return redirect(url_for('settings.ingredient_aliases_view', plan_id=plan_id))


@settings_bp.route('/api/ingredient-alias/set', methods=['POST'])
def api_set_ingredient_alias():
    """AJAX counterpart to update_ingredient_aliases() above: sets EXACTLY
    ONE alias immediately while entering an ingredient in recipe_form.html/
    recipe_edit_list.html, without leaving the page (see
    static/ingredient_alias_hint.js - the "Set alias" button there, which
    appears for the case "neither alias nor base ingredient"). Always
    applies to the currently ACTIVE plan (current_plan(), not
    selected_plan_id() - this AJAX action comes from a recipe page, not
    from one of the tab-capable settings pages).

    Expects a JSON body {"raw_name": str, "canonical_name": str}.
    Returns the NORMALIZED values so the frontend can keep its local copy
    of window.INGREDIENT_ALIASES consistent with the lookup key that the
    server also uses (see services/ingredient_aliases.py: normalize_name).
    category is the shopping-list category guessed from existing
    ingredient rows for the canonical ingredient (see services/shopping.py:
    infer_category) - the frontend automatically adopts it into the
    category field of THIS ingredient row, so that all equated ingredients
    end up in the same category instead of being sorted differently
    depending on the recipe. None (no existing row categorized yet) leaves
    the frontend field untouched."""
    plan = current_plan()
    data = request.get_json() or {}
    raw_name = (data.get('raw_name') or '').strip()
    canonical_name = (data.get('canonical_name') or '').strip()
    if not raw_name or not canonical_name:
        return {"error": _("Name and alias must not be empty.")}, 400

    set_alias(plan.id, raw_name, canonical_name)
    resolved_canonical = normalize_ingredient_name(plan.id, raw_name)
    return {
        "ok": True,
        "raw_name": normalize_name(raw_name),
        "canonical_name": resolved_canonical,
        "category": infer_category(plan.id, resolved_canonical),
    }


def _parse_nutrition_form_values(data):
    """Reads the four nutrition fields from a JSON body (dict-like,
    .get()) and robustly converts them to numbers - an empty or invalid
    field becomes 0 instead of an error, analogous to the other form
    parsers in this app (e.g. routes/recipes.py: add_recipe()).
    reference_amount is deliberately NOT read - it always follows fixedly
    from reference_unit (see services/nutrition.py: REFERENCE_BASES),
    set_nutrition() checks/enforces this itself. calories doesn't even
    exist here as a field - it is never entered anywhere, but always
    calculated from protein/carbs/fat (see services/nutrition.py:
    compute_calories())."""
    def _num(key, cast, default=0):
        try:
            return cast(data.get(key) or default)
        except (TypeError, ValueError):
            return default

    return {
        "reference_unit": (data.get("reference_unit") or "g").strip(),
        "protein": _num("protein", float),
        "carbs": _num("carbs", float),
        "fat": _num("fat", float),
    }


@settings_bp.route('/api/ingredient-nutrition/set', methods=['POST'])
def api_set_ingredient_nutrition():
    """AJAX endpoint for the inline hint while entering an ingredient (see
    static/ingredient_alias_hint.js): immediately adds a nutrition entry
    for an ingredient, without leaving the recipe page - offered exactly
    when window.INGREDIENT_NUTRITION doesn't yet have an entry for the
    resolved canonical ingredient. Like api_set_ingredient_alias() above,
    always for the currently ACTIVE plan (current_plan()).

    Expects a JSON body {"name": str, "reference_unit": "g"|"ml"|"Stk",
    "protein"/"carbs"/"fat": number}. calories in the response is purely
    informational (calculated from protein/carbs/fat), not a stored
    value."""
    plan = current_plan()
    data = request.get_json() or {}
    name = (data.get('name') or '').strip()
    if not name:
        return {"error": _("Ingredient name must not be empty.")}, 400

    values = _parse_nutrition_form_values(data)
    entry = set_nutrition(plan.id, name, **values)
    return {
        "ok": True,
        "canonical_name": entry.canonical_name,
        "reference_amount": entry.reference_amount,
        "reference_unit": entry.reference_unit,
        "calories": compute_calories(entry.protein, entry.carbs, entry.fat),
        "protein": entry.protein,
        "carbs": entry.carbs,
        "fat": entry.fat,
    }


@settings_bp.route('/manage/ingredient-nutrition')
def ingredient_nutrition_view():
    """Shows ONLY the actual alias target names of the selected plan
    (services/nutrition.py: list_alias_canonical_names() - e.g. "pasta",
    "oil", NOT every unaliased individual ingredient) with editable
    nutrition fields, pre-filled with the maintained entry or (without an
    existing entry) with sensible default values (reference amount 100,
    reference unit guessed from the actually used ingredient rows, see
    infer_reference_unit()) - unaliased individual ingredients instead
    get their nutrition values added directly while entering the
    ingredient (see api_set_ingredient_nutrition above)."""
    user = current_user()
    plan_id = selected_plan_id(request.args, user)
    entries = get_all_nutrition_entries(plan_id)
    rows = []
    for name in list_alias_canonical_names(plan_id):
        entry = entries.get(name)
        protein = entry["protein"] if entry else 0
        carbs = entry["carbs"] if entry else 0
        fat = entry["fat"] if entry else 0
        rows.append({
            "canonical_name": name,
            "reference_unit": entry["reference_unit"] if entry else infer_reference_unit(plan_id, name),
            # Display only (see ingredient_nutrition_manage.html) - not an
            # editable/stored field, always follows from protein/carbs/fat.
            "calories": compute_calories(protein, carbs, fat),
            "protein": protein,
            "carbs": carbs,
            "fat": fat,
            "has_entry": entry is not None,
        })
    return render_template(
        'ingredient_nutrition_manage.html', rows=rows, plan_id=plan_id, user_plans=user_plan_memberships(user),
    )


@settings_bp.route('/update-ingredient-nutrition', methods=['POST'])
def update_ingredient_nutrition():
    """Saves ALL rows of the form at once (parallel lists, analogous to
    update_ingredient_aliases() above) instead of one button per row."""
    plan_id = selected_plan_id(request.form, current_user())
    names = request.form.getlist('canonical_name[]')
    reference_units = request.form.getlist('reference_unit[]')
    protein_list = request.form.getlist('protein[]')
    carbs_list = request.form.getlist('carbs[]')
    fat_list = request.form.getlist('fat[]')

    for i, name in enumerate(names):
        values = _parse_nutrition_form_values({
            "reference_unit": reference_units[i] if i < len(reference_units) else None,
            "protein": protein_list[i] if i < len(protein_list) else None,
            "carbs": carbs_list[i] if i < len(carbs_list) else None,
            "fat": fat_list[i] if i < len(fat_list) else None,
        })
        set_nutrition(plan_id, name, **values)

    return redirect(url_for('settings.ingredient_nutrition_view', plan_id=plan_id))
