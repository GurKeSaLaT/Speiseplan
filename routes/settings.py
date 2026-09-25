"""Per-plan settings pages: display units, and the ingredients & nutrition
page (aliases that merge spellings on the shopping list, plus nutrition
references). Everything on the ingredients page autosaves via the two
/api/ endpoints below."""

from flask import Blueprint, redirect, render_template, request, url_for
from flask_babel import gettext as _

from services.auth import current_plan, current_user, selected_plan_id, user_has_plan_access, user_plan_memberships
from services.ingredient_aliases import (
    get_all_aliases, list_known_ingredient_names, normalize_ingredient_name, normalize_name,
    prune_orphaned_aliases, recipes_by_ingredient_name, set_alias,
)
from services.nutrition import (
    compute_calories, get_all_nutrition_entries, infer_reference_units_for_plan, list_alias_canonical_names,
    set_nutrition,
)
from services.settings import get_settings, update_display_units
from services.shopping import infer_category, infer_is_pantry
from services.units import DISPLAY_UNIT_CHOICES, MASS, VOLUME

settings_bp = Blueprint('settings', __name__)


@settings_bp.route('/manage/units')
def units_view():
    user = current_user()
    plan_id = selected_plan_id(request.args, user)
    settings = get_settings(plan_id)
    return render_template(
        'units_manage.html', settings=settings, plan_id=plan_id, user_plans=user_plan_memberships(user),
        mass_choices=DISPLAY_UNIT_CHOICES[MASS], volume_choices=DISPLAY_UNIT_CHOICES[VOLUME],
    )


@settings_bp.route('/update-units', methods=['POST'])
def update_units():
    """Invalid values are ignored by update_display_units()."""
    plan_id = selected_plan_id(request.form, current_user())
    mass_unit = request.form.get('mass_unit', '')
    volume_unit = request.form.get('volume_unit', '')
    update_display_units(plan_id, mass_unit, volume_unit)
    return redirect(url_for('settings.units_view', plan_id=plan_id))


def _nutrition_row(entries, inferred_units, name):
    """Nutrition fields for one ingredient card. inferred_units must be the
    precomputed whole-plan dict - a per-row lookup made this page take 30+
    seconds on real data."""
    entry = entries.get(name)
    protein = entry["protein"] if entry else 0
    carbs = entry["carbs"] if entry else 0
    fat = entry["fat"] if entry else 0
    return {
        "reference_unit": entry["reference_unit"] if entry else inferred_units.get(name, 'g'),
        "calories": compute_calories(protein, carbs, fat),
        "protein": protein,
        "carbs": carbs,
        "fat": fat,
        "has_entry": entry is not None,
    }


def _merged_recipes(recipes_by_name, names):
    """Recipes using any of names, deduped and sorted by recipe name."""
    seen = {}
    for name in names:
        for recipe_id, recipe_name in recipes_by_name.get(name, []):
            seen[recipe_id] = recipe_name
    return sorted(seen.items(), key=lambda pair: pair[1])


@settings_bp.route('/manage/ingredient-aliases')
def ingredient_aliases_view():
    """Two groups, never overlapping: main_groups (canonical names with at
    least one alias, aliases nested underneath) and other_rows (names that
    are neither an alias target nor an alias). Orphaned aliases are pruned
    first, on every view."""
    user = current_user()
    plan_id = selected_plan_id(request.args, user)

    recipes_by_name = recipes_by_ingredient_name(plan_id)
    prune_orphaned_aliases(plan_id, recipes_by_name)

    aliases = get_all_aliases(plan_id)
    entries = get_all_nutrition_entries(plan_id)
    inferred_units = infer_reference_units_for_plan(plan_id)
    main_names = list_alias_canonical_names(plan_id)

    aliased_raw_names_by_target = {}
    for raw_name, canonical_name in aliases.items():
        aliased_raw_names_by_target.setdefault(canonical_name, []).append(raw_name)

    main_groups = [
        {
            "canonical_name": name,
            "aliases": [
                {"name": alias, "recipes": recipes_by_name.get(alias, [])}
                for alias in sorted(aliased_raw_names_by_target.get(name, []))
            ],
            # A canonical name is often an umbrella never typed as an
            # ingredient itself, so include its aliases' recipes.
            "recipes": _merged_recipes(recipes_by_name, [name] + aliased_raw_names_by_target.get(name, [])),
            **_nutrition_row(entries, inferred_units, name),
        }
        for name in main_names
    ]

    main_name_set = set(main_names)
    aliased_raw_names = set(aliases.keys())
    other_rows = [
        {"raw_name": name, "recipes": recipes_by_name.get(name, []), **_nutrition_row(entries, inferred_units, name)}
        for name in list_known_ingredient_names(plan_id)
        if name not in main_name_set and name not in aliased_raw_names
    ]

    return render_template(
        'ingredient_aliases_manage.html',
        main_groups=main_groups, other_rows=other_rows,
        plan_id=plan_id, user_plans=user_plan_memberships(user),
    )


def _resolve_ajax_plan_id(data, user):
    """plan_id from the JSON body if the user is a member, else the active
    plan. The ingredients page sends the plan its own tab selector shows;
    the recipe form's inline hint sends none."""
    requested = data.get('plan_id')
    if requested is not None and user_has_plan_access(user, requested):
        return requested
    plan = current_plan()
    return plan.id if plan else None


@settings_bp.route('/api/ingredient-alias/set', methods=['POST'])
def api_set_ingredient_alias():
    """Body: {"raw_name", "canonical_name", "plan_id"?}. Returns the
    normalized names plus the shopping category and pantry flag guessed for
    the canonical ingredient, which the recipe form adopts for that row."""
    user = current_user()
    data = request.get_json() or {}
    plan_id = _resolve_ajax_plan_id(data, user)
    raw_name = (data.get('raw_name') or '').strip()
    canonical_name = (data.get('canonical_name') or '').strip()
    if not plan_id or not raw_name or not canonical_name:
        return {"error": _("Name and alias must not be empty.")}, 400

    set_alias(plan_id, raw_name, canonical_name)
    resolved_canonical = normalize_ingredient_name(plan_id, raw_name)
    return {
        "ok": True,
        "raw_name": normalize_name(raw_name),
        "canonical_name": resolved_canonical,
        "category": infer_category(plan_id, resolved_canonical),
        "is_pantry": infer_is_pantry(plan_id, resolved_canonical),
    }


def _parse_nutrition_form_values(data):
    """Invalid numbers become 0. reference_amount follows from the unit and
    calories are always computed, so neither is read."""
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
    """Body: {"name", "reference_unit": "g"|"ml"|"Stk", "protein", "carbs",
    "fat", "plan_id"?}."""
    user = current_user()
    data = request.get_json() or {}
    plan_id = _resolve_ajax_plan_id(data, user)
    name = (data.get('name') or '').strip()
    if not plan_id or not name:
        return {"error": _("Ingredient name must not be empty.")}, 400

    values = _parse_nutrition_form_values(data)
    entry = set_nutrition(plan_id, name, **values)
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
