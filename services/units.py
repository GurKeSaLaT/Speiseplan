"""Unit normalization for ingredient amounts.

Mass is always stored in g and volume in ml (kitchen measures use fixed
approximations: 1 TL = 5 ml, 1 EL = 15 ml, 1 Tasse = 250 ml). The
client-side shopping list merges items by name+unit without converting,
so every row of a family must carry the same unit. Display units (kg/l)
are applied only when showing amounts; the conversion is exact, so a
displayed value saved back unchanged yields the same stored value.
"""

from models import Ingredient, db

MASS = 'mass'
VOLUME = 'volume'

BASE_UNIT = {MASS: 'g', VOLUME: 'ml'}

DISPLAY_UNIT_CHOICES = {MASS: ['g', 'kg'], VOLUME: ['ml', 'l']}
DEFAULT_DISPLAY_UNIT = {MASS: 'g', VOLUME: 'ml'}

# normalized spelling -> (family, factor to the base unit)
_CONVERSIONS = {
    'g': (MASS, 1), 'gr': (MASS, 1), 'gramm': (MASS, 1),
    'mg': (MASS, 0.001), 'milligramm': (MASS, 0.001),
    'dkg': (MASS, 10), 'deka': (MASS, 10), 'dekagramm': (MASS, 10),  # common in Austria
    'kg': (MASS, 1000), 'kilo': (MASS, 1000), 'kilogramm': (MASS, 1000),
    'ml': (VOLUME, 1), 'milliliter': (VOLUME, 1),
    'cl': (VOLUME, 10), 'zentiliter': (VOLUME, 10),
    'l': (VOLUME, 1000), 'liter': (VOLUME, 1000),
    'tl': (VOLUME, 5), 'teel': (VOLUME, 5), 'teelöffel': (VOLUME, 5),
    'el': (VOLUME, 15), 'essl': (VOLUME, 15), 'esslöffel': (VOLUME, 15),
    'tasse': (VOLUME, 250), 'tassen': (VOLUME, 250), 'cup': (VOLUME, 250), 'cups': (VOLUME, 250),
}

# Recognized as units (so the recipe import doesn't treat them as part of
# the name) but left unconverted.
NON_CONVERTIBLE_UNITS = {
    'stk', 'stk.', 'stück', 'stange', 'stangen', 'bund', 'bünde',
    'dose', 'dosen', 'päckchen', 'zehe', 'zehen', 'scheibe', 'scheiben',
    'blatt', 'blätter', 'glas', 'gläser', 'würfel', 'kugel', 'kugeln',
    'packung', 'packungen', 'becher', 'msp', 'msp.', 'prise', 'prisen',
}


def _normalize_key(raw_unit):
    return (raw_unit or '').strip().lower().rstrip('.')


def known_unit_keys():
    return set(_CONVERSIONS) | NON_CONVERTIBLE_UNITS


def normalize_amount_unit(raw_amount, raw_unit):
    """(1, "kg") -> (1000, "g"), (2, "EL") -> (30, "ml"). Other units are
    returned unchanged, spelling included."""
    conv = _CONVERSIONS.get(_normalize_key(raw_unit))
    if not conv:
        return raw_amount, raw_unit
    family, factor = conv
    return raw_amount * factor, BASE_UNIT[family]


def convert_for_display(amount, unit, display_units):
    """Canonical g/ml -> the chosen display unit (kg/l); rounded to avoid
    float artifacts like 0.6999999."""
    if unit == BASE_UNIT[MASS] and display_units.get(MASS) == 'kg':
        return round(amount / 1000, 3), 'kg'
    if unit == BASE_UNIT[VOLUME] and display_units.get(VOLUME) == 'l':
        return round(amount / 1000, 3), 'l'
    return amount, unit


def renormalize_existing_ingredients():
    """Brings stored ingredients into canonical form; idempotent, runs on
    every start."""
    changed = False
    for ingredient in Ingredient.query.all():
        new_amount, new_unit = normalize_amount_unit(ingredient.amount, ingredient.unit)
        if new_amount != ingredient.amount or new_unit != ingredient.unit:
            ingredient.amount = new_amount
            ingredient.unit = new_unit
            changed = True
    if changed:
        db.session.commit()
