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

2. Ingredients & nutrition (ingredient_aliases_view): ONE page covering
   both which concrete ingredient names (e.g. "spaghetti", "fusilli")
   should count as the same item for the shopping list (e.g. "pasta",
   see services/ingredient_aliases.py) AND the nutrition reference per
   resulting canonical ingredient (see services/nutrition.py), from
   which recipe nutrition values are automatically calculated (see
   routes/recipes/crud.py: add_recipe()/edit_recipe()). Used to be two
   separate pages/routes (ingredient_nutrition_view/
   update_ingredient_nutrition) - merged because a main ingredient's
   nutrition reference and the individual spellings merged into it are
   really one editing task, not two (see IDEAS.md). Equating an
   ingredient does NOT change the ingredient names shown in a recipe,
   only the grouping on the shopping list. Every field on this page
   autosaves via api_set_ingredient_alias()/api_set_ingredient_nutrition()
   below - there was a batch-save update_ingredients() endpoint here
   briefly, replaced once the page itself became autosaving (see
   IDEAS.md).

Both areas are separated PER PLAN (see models/settings.py: AppSettings.
plan_id/IngredientAlias.plan_id/IngredientNutrition.plan_id) - each page
shows a tab switcher when a user has access to more than one plan (see
services/auth.py: selected_plan_id/user_plan_memberships) and acts on
the CURRENTLY selected plan, not necessarily the otherwise active one
(current_plan()).
"""

from flask import Blueprint, redirect, render_template, request, url_for
from flask_babel import gettext as _

from services.auth import current_plan, current_user, selected_plan_id, user_has_plan_access, user_plan_memberships
from services.ingredient_aliases import (
    get_all_aliases, list_known_ingredient_names, normalize_ingredient_name, normalize_name,
    recipes_by_ingredient_name, set_alias,
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


def _nutrition_row(entries, inferred_units, name):
    """Builds the nutrition-editing fields shared by both a "main
    ingredient" card and a standalone "other ingredient" card (see
    ingredient_aliases_view() below) - pre-filled with the maintained
    entry or, without one yet, sensible defaults (see
    ingredient_nutrition_view() formerly here, now folded into this one
    view).

    inferred_units is the WHOLE-PLAN guess computed once by
    ingredient_aliases_view() (services/nutrition.py:
    infer_reference_units_for_plan()) - calling the single-name
    infer_reference_unit() here instead, once per row, used to mean a
    full ingredient scan (with an alias-resolving query inside it) PER
    ROW, which became a genuine multi-second page load once this
    function started running for every unaliased ingredient too, not
    just the (usually far fewer) alias targets (see git history)."""
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
    """Union of recipes_by_name.get(n, []) across several names, deduped by
    recipe id and re-sorted by recipe name - used to give a main
    ingredient's group heading a link that covers every recipe any of its
    merged spellings appears in (see ingredient_aliases_view() below),
    since recipes_by_name itself only knows about literal, as-typed
    ingredient names, not canonical/alias ones."""
    seen = {}
    for name in names:
        for recipe_id, recipe_name in recipes_by_name.get(name, []):
            seen[recipe_id] = recipe_name
    return sorted(seen.items(), key=lambda pair: pair[1])


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
    twice, once as its own row and once nested under its target.

    Every name/alias also carries "recipes" - the (id, name) pairs of
    every recipe that uses it directly (services/ingredient_aliases.py:
    recipes_by_ingredient_name()), so the template can link straight to
    "the recipe this is part of" instead of only being editable here."""
    user = current_user()
    plan_id = selected_plan_id(request.args, user)

    aliases = get_all_aliases(plan_id)
    entries = get_all_nutrition_entries(plan_id)
    inferred_units = infer_reference_units_for_plan(plan_id)
    recipes_by_name = recipes_by_ingredient_name(plan_id)
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
            # The union across the canonical name itself AND every alias
            # merged into it - not just recipes_by_name.get(name, []).
            # A canonical name is often an invented umbrella (e.g.
            # "Noodles" for "Spaghetti"/"Fusilli") that was never itself
            # typed as an ingredient anywhere, so looking it up alone
            # would show NO recipe link even though its merged ingredients
            # obviously belong to some.
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
    """Resolves which plan an AJAX body applies to: an explicit plan_id
    in the JSON body wins, but ONLY if user is actually a member of it
    (never trust a client-supplied ID otherwise) - falls back to
    current_plan() when absent, which is what both callers below
    originally always used unconditionally (the recipe form's inline
    hint, see static/ingredient_alias_hint.js, always means the active
    plan and never sends one). Added so templates/ingredient_aliases_manage.html's
    autosave can target whichever plan its OWN tab switcher has selected
    (services/auth.py: selected_plan_id()), which is not necessarily the
    active plan - without this, autosaving on a non-active plan's tab
    would silently write to the wrong plan."""
    requested = data.get('plan_id')
    if requested is not None and user_has_plan_access(user, requested):
        return requested
    plan = current_plan()
    return plan.id if plan else None


@settings_bp.route('/api/ingredient-alias/set', methods=['POST'])
def api_set_ingredient_alias():
    """Sets EXACTLY ONE alias immediately - used both by the recipe form's inline hint
    (recipe_form.html/recipe_edit_list.html, see
    static/ingredient_alias_hint.js - the "Set alias" button there, which
    appears for the case "neither alias nor base ingredient", always for
    the active plan) AND by the autosave on
    templates/ingredient_aliases_manage.html itself (which may target a
    non-active plan, see _resolve_ajax_plan_id() above).

    Expects a JSON body {"raw_name": str, "canonical_name": str, "plan_id": int (optional)}.
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
    """AJAX endpoint - used both by the inline hint while entering an
    ingredient (see static/ingredient_alias_hint.js: immediately adds a
    nutrition entry without leaving the recipe page, offered exactly when
    window.INGREDIENT_NUTRITION doesn't yet have an entry for the
    resolved canonical ingredient, always for the active plan) AND by the
    autosave on templates/ingredient_aliases_manage.html itself (which
    may target a non-active plan, see api_set_ingredient_alias() above:
    _resolve_ajax_plan_id()).

    Expects a JSON body {"name": str, "reference_unit": "g"|"ml"|"Stk",
    "protein"/"carbs"/"fat": number, "plan_id": int (optional)}. calories
    in the response is purely informational (calculated from
    protein/carbs/fat), not a stored value."""
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


