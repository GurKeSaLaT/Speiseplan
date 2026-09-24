"""Settings pages of the app: currently two thematically separate areas
that share this one blueprint (analogous to the routes/plan/ package -
but here in a single, manageable file instead of its own package, since
both areas are small):

1. Units (units_view/update_units): in which unit ingredient amounts
   should be displayed (mass: grams/kilograms, volume: milliliters/
   liters) - see services/units.py for the actual conversion and
   services/settings.py for the storage. Does NOT change how amounts
   are stored internally (always canonical g/ml), only how they are
   displayed in forms/the shopping list.

2. Ingredients & nutrition (ingredient_aliases_view/update_ingredients):
   ONE page covering both which concrete ingredient names (e.g.
   "spaghetti", "fusilli") should count as the same item for the
   shopping list (e.g. "pasta", see services/ingredient_aliases.py) AND
   the nutrition reference per resulting canonical ingredient (see
   services/nutrition.py), from which recipe nutrition values are
   automatically calculated (see routes/recipes/crud.py:
   add_recipe()/edit_recipe()). Used to be two separate pages/routes
   (ingredient_nutrition_view/update_ingredient_nutrition) - merged
   because a main ingredient's nutrition reference and the individual
   spellings merged into it are really one editing task, not two (see
   IDEAS.md). Equating an ingredient does NOT change the ingredient
   names shown in a recipe, only the grouping on the shopping list.

Both areas are separated PER PLAN (see models/settings.py: AppSettings.
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
from services.shopping import infer_category, infer_is_pantry
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


def _nutrition_row(plan_id, entries, name):
    """Builds the nutrition-editing fields shared by both a "main
    ingredient" card and a standalone "other ingredient" card (see
    ingredient_aliases_view() below) - pre-filled with the maintained
    entry or, without one yet, sensible defaults (see
    ingredient_nutrition_view() formerly here, now folded into this one
    view)."""
    entry = entries.get(name)
    protein = entry["protein"] if entry else 0
    carbs = entry["carbs"] if entry else 0
    fat = entry["fat"] if entry else 0
    return {
        "reference_unit": entry["reference_unit"] if entry else infer_reference_unit(plan_id, name),
        "calories": compute_calories(protein, carbs, fat),
        "protein": protein,
        "carbs": carbs,
        "fat": fat,
        "has_entry": entry is not None,
    }


@settings_bp.route('/manage/ingredient-aliases')
def ingredient_aliases_view():
    """Shows two groups of ingredient names known for the selected plan
    (formerly two separate pages - see IDEAS.md):

    - "Main ingredients" (main_groups): every canonical name that at
      least one other ingredient is aliased to (services/nutrition.py:
      list_alias_canonical_names()) - each with its own nutrition
      reference (see _nutrition_row above) and, nested under it, every
      raw ingredient name currently aliased to it.
    - "Everything else" (other_rows): every other known ingredient name
      (services/ingredient_aliases.py: list_known_ingredient_names()) -
      neither a main ingredient nor aliased to one - with its OWN
      nutrition reference (an ingredient with no alias is its own
      canonical name, see services/nutrition.py: get_nutrition_entry())
      and an editable "counts as" field to promote it into a main
      ingredient's group.

    A name can never appear in both groups at once: list_alias_canonical_names()
    already only returns names that are actual alias TARGETS, and
    other_rows explicitly excludes those plus every name that is itself
    an alias SOURCE (aliased_raw_names) - it would otherwise show up
    twice, once as its own row and once nested under its target."""
    user = current_user()
    plan_id = selected_plan_id(request.args, user)

    aliases = get_all_aliases(plan_id)
    entries = get_all_nutrition_entries(plan_id)
    main_names = list_alias_canonical_names(plan_id)

    aliased_raw_names_by_target = {}
    for raw_name, canonical_name in aliases.items():
        aliased_raw_names_by_target.setdefault(canonical_name, []).append(raw_name)

    main_groups = [
        {
            "canonical_name": name,
            "aliases": sorted(aliased_raw_names_by_target.get(name, [])),
            **_nutrition_row(plan_id, entries, name),
        }
        for name in main_names
    ]

    main_name_set = set(main_names)
    aliased_raw_names = set(aliases.keys())
    other_rows = [
        {"raw_name": name, **_nutrition_row(plan_id, entries, name)}
        for name in list_known_ingredient_names(plan_id)
        if name not in main_name_set and name not in aliased_raw_names
    ]

    return render_template(
        'ingredient_aliases_manage.html',
        main_groups=main_groups, other_rows=other_rows,
        plan_id=plan_id, user_plans=user_plan_memberships(user),
    )


@settings_bp.route('/update-ingredients', methods=['POST'])
def update_ingredients():
    """Saves EVERY editable field of ingredient_aliases_view() at once
    (parallel lists, like the ingredient rows of the recipe forms) -
    replaces the two formerly separate update_ingredient_aliases()/
    update_ingredient_nutrition() endpoints (see IDEAS.md).

    Alias pairs (raw_name[]/canonical_name[]) are saved FIRST, before any
    nutrition value - both a nested alias's "×" removal (see
    templates/ingredient_aliases_manage.html: the hidden inputs behind
    it) and an "other ingredient" row's "counts as" field arrive this
    way. Nutrition rows are identified by nutrition_name[] (a main
    group's canonical name, or an "other" row's own name) rather than
    reusing canonical_name[], since the two lists differ in length/order
    and would otherwise collide. Saving nutrition AFTER the alias pairs
    means set_nutrition()'s own alias resolution (via
    normalize_ingredient_name()) already sees this same submission's
    fresh mapping - so re-pointing an ingredient's "counts as" AND
    editing its nutrition in the same submit lands the nutrition under
    the new canonical name, not the old one."""
    plan_id = selected_plan_id(request.form, current_user())

    raw_names = request.form.getlist('raw_name[]')
    canonical_names = request.form.getlist('canonical_name[]')
    for raw_name, canonical_name in zip(raw_names, canonical_names):
        set_alias(plan_id, raw_name, canonical_name)

    nutrition_names = request.form.getlist('nutrition_name[]')
    reference_units = request.form.getlist('reference_unit[]')
    protein_list = request.form.getlist('protein[]')
    carbs_list = request.form.getlist('carbs[]')
    fat_list = request.form.getlist('fat[]')
    for i, name in enumerate(nutrition_names):
        values = _parse_nutrition_form_values({
            "reference_unit": reference_units[i] if i < len(reference_units) else None,
            "protein": protein_list[i] if i < len(protein_list) else None,
            "carbs": carbs_list[i] if i < len(carbs_list) else None,
            "fat": fat_list[i] if i < len(fat_list) else None,
        })
        set_nutrition(plan_id, name, **values)

    return redirect(url_for('settings.ingredient_aliases_view', plan_id=plan_id))


@settings_bp.route('/api/ingredient-alias/set', methods=['POST'])
def api_set_ingredient_alias():
    """AJAX counterpart to update_ingredients() above: sets EXACTLY
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
    the frontend field untouched. is_pantry (services/shopping.py:
    infer_is_pantry) is adopted the same way into the pantry checkbox,
    but only ever to CHECK it, never to uncheck one the user already set -
    see static/ingredient_alias_hint.js: fillPantryFromAlias()."""
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
        "is_pantry": infer_is_pantry(plan.id, resolved_canonical),
    }


def _parse_nutrition_form_values(data):
    """Reads the four nutrition fields from a JSON body (dict-like,
    .get()) and robustly converts them to numbers - an empty or invalid
    field becomes 0 instead of an error, analogous to the other form
    parsers in this app (e.g. routes/recipes/crud.py: add_recipe()).
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


