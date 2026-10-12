"""Leftovers from the previous week (WeekLeftover): parsing the create-week
form, storing them per week, and matching them against recipe ingredients
so week generation can use them up first."""

import math

from models import db, Ingredient, WeekLeftover
from services.ingredient_aliases import get_all_aliases, normalize_name
from services.settings import get_display_units
from services.units import convert_for_display, normalize_amount_unit

MAX_LEFTOVERS_PER_WEEK = 30


def parse_amount(raw):
    """A positive finite float from user input ("1,5" works too), else None."""
    if raw is None or isinstance(raw, bool):
        return None
    try:
        value = float(str(raw).strip().replace(',', '.'))
    except ValueError:
        return None
    return value if math.isfinite(value) and value > 0 else None


def canonical_name(aliases, raw_name):
    """Like normalize_ingredient_name(), with a preloaded alias map."""
    key = normalize_name(raw_name)
    return aliases.get(key, key)


def build_leftover(aliases, raw_name, raw_amount=None, raw_unit=None):
    """{name, amount, unit} in canonical form, or None for a blank name.
    A unit without an amount is dropped (it would mean nothing)."""
    if not (raw_name or '').strip():
        return None
    amount = parse_amount(raw_amount)
    unit = (raw_unit or '').strip()[:20] or None
    if amount is None:
        unit = None
    elif unit is not None:
        amount, unit = normalize_amount_unit(amount, unit)
    return {"name": canonical_name(aliases, raw_name)[:100], "amount": amount, "unit": unit}


def parse_leftovers_form(form, plan_id):
    """Leftovers from the create-week form's parallel leftover_name[] /
    leftover_amount[] / leftover_unit[] lists. Entries with the same name
    and unit are merged (amounts added; no amount wins, it means "all")."""
    aliases = get_all_aliases(plan_id)
    names = form.getlist('leftover_name[]')
    amounts = form.getlist('leftover_amount[]')
    units = form.getlist('leftover_unit[]')

    merged = {}
    for i, raw_name in enumerate(names[:MAX_LEFTOVERS_PER_WEEK]):
        leftover = build_leftover(
            aliases, raw_name,
            amounts[i] if i < len(amounts) else None,
            units[i] if i < len(units) else None,
        )
        if leftover is None:
            continue
        key = (leftover["name"], (leftover["unit"] or '').lower())
        if key in merged:
            existing = merged[key]
            if existing["amount"] is None or leftover["amount"] is None:
                existing["amount"] = None
                existing["unit"] = None
            else:
                existing["amount"] += leftover["amount"]
        else:
            merged[key] = leftover
    return list(merged.values())


def replace_week_leftovers(plan_id, week_start, leftovers):
    """Stores exactly these leftovers for the week (no commit)."""
    WeekLeftover.query.filter_by(plan_id=plan_id, week_start=week_start).delete()
    for leftover in leftovers:
        db.session.add(WeekLeftover(plan_id=plan_id, week_start=week_start, **leftover))


def week_leftovers(plan_id, week_start):
    return (
        WeekLeftover.query.filter_by(plan_id=plan_id, week_start=week_start)
        .order_by(WeekLeftover.id).all()
    )


def leftover_payload(leftover, display_units):
    """JSON for the client, amount in plan_id's display unit (the same one
    jsonify_recipe() uses, so the shopping list can subtract it)."""
    amount, unit = (
        convert_for_display(leftover.amount, leftover.unit, display_units)
        if leftover.amount is not None else (None, None)
    )
    return {"id": leftover.id, "name": leftover.name, "amount": amount, "unit": unit}


def week_leftovers_payload(plan_id, week_start):
    display_units = get_display_units(plan_id)
    return [leftover_payload(lo, display_units) for lo in week_leftovers(plan_id, week_start)]


def ingredient_names_by_recipe(plan_id, recipe_ids):
    """{recipe_id: {canonical ingredient name, ...}} in one query, using
    plan_id's aliases (the plan being generated decides what matches)."""
    if not recipe_ids:
        return {}
    aliases = get_all_aliases(plan_id)
    rows = (
        db.session.query(Ingredient.recipe_id, Ingredient.name)
        .filter(Ingredient.recipe_id.in_(list(recipe_ids)))
        .all()
    )
    names = {}
    for recipe_id, name in rows:
        if name and name.strip():
            names.setdefault(recipe_id, set()).add(canonical_name(aliases, name))
    return names
