"""Unit normalization for ingredient amounts (Ingredient.amount/.unit).

Consolidates different spellings of the same unit (e.g. "g"/"Gramm"/"gr" or
"kg"/"Kilogramm"/"Kilo") and converts amounts from families with a single,
unambiguous base unit - mass -> grams, volume -> milliliters (incl. kitchen
measures like tsp/tbsp/cup, see _CONVERSIONS below) - ALWAYS to this base
when saving, regardless of the entered/imported spelling or magnitude
("1kg" becomes "1000g", "2 tbsp" becomes "30 ml"). normalize_amount_unit()
handles this both for manual recipe entry (routes/recipes.py) and for
import (services/recipe_import.py), as well as once for legacy data
(renormalize_existing_ingredients(), called from migrations.py: init_db()).

The fact that ALL Ingredient rows of a family carry the same unit in the
database is the precondition for the shopping list (static/plan-shopping.js:
rebuildShoppingList) being able to correctly sum up identically named
ingredients across multiple recipes - it groups purely by "name+unit"
there, without doing any conversion itself.

Display is nonetheless in the unit chosen by the user (see
services/settings.py: AppSettings) - convert_for_display() converts back
ONLY for display purposes, without changing the stored (canonical) value.
Since the conversion (factor 1000 or 1) is exact and reversible without
rounding loss, templates may also feed these display values directly back
into a form field (see recipe_edit_list.html) - saving without a change
yields, via normalize_amount_unit(), exactly the same canonical value
again.

Kitchen measures (tsp/tbsp/cup) are deliberately part of the volume family
(fixed approximations commonly used in the kitchen: 1 tsp=5ml, 1 tbsp=15ml,
1 cup=250ml) - these measures can't be made more precise anyway, since they
vary slightly depending on ingredient/vessel.
"""

from models import Ingredient, db

MASS = 'mass'
VOLUME = 'volume'

BASE_UNIT = {MASS: 'g', VOLUME: 'ml'}

# Display units selectable per family on the settings page
# (routes/settings.py) - base unit listed first in each (the default).
DISPLAY_UNIT_CHOICES = {MASS: ['g', 'kg'], VOLUME: ['ml', 'l']}
DEFAULT_DISPLAY_UNIT = {MASS: 'g', VOLUME: 'ml'}

# Key: normalized spelling (lowercase, no trailing period - see
# _normalize_key). Value: (family, factor relative to the family's base
# unit). Not exhaustive, but covers the spellings commonly used on the
# sites listed in services/recipe_import.py: ALLOWED_HOSTS as well as in
# manual entry.
_CONVERSIONS = {
    # Mass (base: grams)
    'g': (MASS, 1), 'gr': (MASS, 1), 'gramm': (MASS, 1),
    'mg': (MASS, 0.001), 'milligramm': (MASS, 0.001),
    'dkg': (MASS, 10), 'deka': (MASS, 10), 'dekagramm': (MASS, 10),  # commonly used in Austria
    'kg': (MASS, 1000), 'kilo': (MASS, 1000), 'kilogramm': (MASS, 1000),
    # Volume (base: milliliters) - incl. kitchen measures, see module docstring
    'ml': (VOLUME, 1), 'milliliter': (VOLUME, 1),
    'cl': (VOLUME, 10), 'zentiliter': (VOLUME, 10),
    'l': (VOLUME, 1000), 'liter': (VOLUME, 1000),
    'tl': (VOLUME, 5), 'teel': (VOLUME, 5), 'teelöffel': (VOLUME, 5),
    'el': (VOLUME, 15), 'essl': (VOLUME, 15), 'esslöffel': (VOLUME, 15),
    'tasse': (VOLUME, 250), 'tassen': (VOLUME, 250), 'cup': (VOLUME, 250), 'cups': (VOLUME, 250),
}

# Additional units recognized in KNOWN_UNITS (services/recipe_import.py)
# but NOT convertible (piece-based / no unambiguous metric equivalent) -
# remain unchanged by normalize_amount_unit(), but still count as a "known
# unit" (see known_unit_keys()), so that _parse_ingredient_line() correctly
# recognizes the following word as a unit rather than part of the
# ingredient name.
NON_CONVERTIBLE_UNITS = {
    'stk', 'stk.', 'stück', 'stange', 'stangen', 'bund', 'bünde',
    'dose', 'dosen', 'päckchen', 'zehe', 'zehen', 'scheibe', 'scheiben',
    'blatt', 'blätter', 'glas', 'gläser', 'würfel', 'kugel', 'kugeln',
    'packung', 'packungen', 'becher', 'msp', 'msp.', 'prise', 'prisen',
}


def _normalize_key(raw_unit):
    return (raw_unit or '').strip().lower().rstrip('.')


def known_unit_keys():
    """All recognized unit spellings (lowercase, no period) - basis for
    KNOWN_UNITS in services/recipe_import.py, so that the same list applies
    there as here for the actual conversion."""
    return set(_CONVERSIONS) | NON_CONVERTIBLE_UNITS


def normalize_amount_unit(raw_amount, raw_unit):
    """Converts an entered/imported amount+unit into the canonical form of
    its family, e.g. (1, "kg") -> (1000, "g") or (2, "tbsp") -> (30, "ml").
    Unknown or non-convertible units (pcs, pinch, bunch, a freely typed
    word, ...) are returned unchanged - only their SPELLING is not
    unified ("Stk"/"stk" both remain, for example), which is deliberately
    not a goal of this function, which only concerns itself with amounts
    that have an unambiguous SI equivalent."""
    conv = _CONVERSIONS.get(_normalize_key(raw_unit))
    if not conv:
        return raw_amount, raw_unit
    family, factor = conv
    return raw_amount * factor, BASE_UNIT[family]


def convert_for_display(amount, unit, display_units):
    """Converts a CANONICAL amount+unit (see normalize_amount_unit) into
    the unit chosen by the user for display (e.g. grams -> kilograms),
    WITHOUT changing the stored value itself.

    display_units is a dict {'mass': 'g'|'kg', 'volume': 'ml'|'l'} (see
    services/settings.py: get_display_units()). Units outside the two base
    units g/ml (e.g. pcs, pinch) remain unchanged, as does the case where
    the chosen display unit already matches the base unit. Rounds to 3
    decimal places to avoid floating-point artifacts from the division
    (e.g. 700g/1000 -> 0.7kg instead of 0.6999999...)."""
    if unit == BASE_UNIT[MASS] and display_units.get(MASS) == 'kg':
        return round(amount / 1000, 3), 'kg'
    if unit == BASE_UNIT[VOLUME] and display_units.get(VOLUME) == 'l':
        return round(amount / 1000, 3), 'l'
    return amount, unit


def renormalize_existing_ingredients():
    """Migrates EXISTING Ingredient rows to the canonical form once (see
    normalize_amount_unit) - called from migrations.py: init_db() on every app
    start. Idempotent like the other migration steps there: a row that is
    already canonical (e.g. amount=1000, unit="g") produces the same value
    on repeated normalization and is thus skipped, so a repeated call does
    nothing further. Commits on its own, analogous to the other migration
    steps in migrations.py: init_db()."""
    changed = False
    for ingredient in Ingredient.query.all():
        new_amount, new_unit = normalize_amount_unit(ingredient.amount, ingredient.unit)
        if new_amount != ingredient.amount or new_unit != ingredient.unit:
            ingredient.amount = new_amount
            ingredient.unit = new_unit
            changed = True
    if changed:
        db.session.commit()
