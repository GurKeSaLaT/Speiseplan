"""Season assignment for recipes.

A recipe can have zero, one, or several "availability ranges"
(RecipeSeason rows): either predefined standard seasons (Frühling/Sommer/
Herbst/Winter - spring/summer/autumn/winter, see SEASON_PRESETS) or a
freely chosen custom range, or a mix of both. All ranges are
year-independent (only month+day, no year) and support wrapping around
the turn of the year (e.g. winter: Dec 1 to Feb 28, running across New
Year's Eve).

This module encapsulates all the logic around these ranges:
- Availability check for "is this recipe in season right now?"
  (recipe_available_now)
- Form parsing when creating/editing a recipe (parse_recipe_seasons,
  save_recipe_seasons)
- Preparation for the edit view: which checkboxes to pre-check, which
  date to put in the custom-range field (describe_recipe_seasons), and
  how the ranges are displayed as badges (format_recipe_seasons)

Important: the season assignment ONLY restricts the automatic selection
during random-pick/auto-fill (see services/planning.py: choose_recipe).
Manually selecting a recipe via search on the create page is never
affected by it - a recipe "from the wrong season" can still be scheduled
there at any time.
"""

from datetime import date

from models import db, RecipeSeason

# The four selectable standard seasons, also shown as checkboxes in
# recipe_form.html in this order.
# NOTE: kept in German (Frühling/Sommer/Herbst/Winter) rather than
# translated - these values are matched 1:1 against the checkbox values
# submitted from recipe_form.html (see parse_recipe_seasons) and are also
# used directly as SEASON_PRESETS keys, so they function as data-matching
# identifiers, not just display text. Left untranslated; flagged in the
# report per the module's data-compatibility caution.
SEASONS = ['Frühling', 'Sommer', 'Herbst', 'Winter']

# Fixed (start_month, start_day, end_month, end_day) ranges per standard
# season. Winter wraps around the turn of the year (start > end) -
# date_in_range() below handles this case correctly.
SEASON_PRESETS = {
    'Frühling': (3, 1, 5, 31),
    'Sommer': (6, 1, 8, 31),
    'Herbst': (9, 1, 11, 30),
    'Winter': (12, 1, 2, 28),
}

# Reverse lookup dict (range tuple -> season name), so that a stored
# RecipeSeason row can be recognized as matching a standard season
# exactly, or being a freely chosen custom range. Needed both to pre-fill
# the edit form and for badge labeling.
SEASON_PRESET_BY_RANGE = {v: k for k, v in SEASON_PRESETS.items()}


def _season_range(rs):
    """Extracts the plain (start_month, start_day, end_month, end_day)
    tuple from a RecipeSeason row, in the same format as SEASON_PRESETS -
    this lets both be compared directly via dict lookup."""
    return (rs.start_month, rs.start_day, rs.end_month, rs.end_day)


def date_in_range(month, day, start_month, start_day, end_month, end_day):
    """Checks whether a given (month, day) falls within a year-independent
    month/day range.

    Normal case (start <= end, e.g. summer Jun 1-Aug 31): simple range
    comparison. Special case (start > end, e.g. winter Dec 1-Feb 28): the
    range wraps around the turn of the year, so (month, day) counts as
    "within the range" if it is either still BEFORE New Year's Eve but
    after the start, OR already AFTER New Year's Day but still before the
    end.
    """
    current = (month, day)
    start = (start_month, start_day)
    end = (end_month, end_day)
    if start <= end:
        return start <= current <= end
    return current >= start or current <= end


def recipe_available_now(recipe):
    """Is this recipe available TODAY (by calendar day, not time of day)
    for automatic selection?

    A recipe with no RecipeSeason rows at all counts as available
    year-round (this is the default case - most recipes have no season
    restriction). If ranges are set, it's enough for today's date to fall
    within AT LEAST ONE of them (OR logic, not AND) - a recipe with
    "Sommer" and "Herbst" (summer and autumn) is, for example, available
    continuously from June through November.
    """
    if not recipe.seasons:
        return True
    today = date.today()
    return any(date_in_range(today.month, today.day, *_season_range(rs)) for rs in recipe.seasons)


def parse_recipe_seasons(form):
    """Reads the season selection from the recipe form (create or edit)
    and translates it into a list of (start_month, start_day, end_month,
    end_day) tuples that can subsequently be saved 1:1 as RecipeSeason
    rows.

    Two form sources are combined:
    1. `seasons` (multi-select checkboxes, one value per checked standard
       season) -> translated into a range tuple via SEASON_PRESETS.
    2. `season_custom_start`/`season_custom_end` (two <input type="date">
       fields) -> the year is discarded from the date string (format
       "YYYY-MM-DD"), only month and day count. Only used if BOTH fields
       are filled in; invalid/incomplete input is silently ignored
       instead of raising an error, so that a typo in the date field
       doesn't block saving entirely.

    Both sources can be freely combined - a recipe can, for example, have
    "Sommer" (summer) AND a custom range at the same time.
    """
    ranges = []
    for season_name in form.getlist('seasons'):
        preset = SEASON_PRESETS.get(season_name)
        if preset:
            ranges.append(preset)

    custom_start = form.get('season_custom_start')
    custom_end = form.get('season_custom_end')
    if custom_start and custom_end:
        try:
            # "YYYY-MM-DD".split('-')[1:] -> ["MM", "DD"], the year is
            # deliberately not used further.
            start_month, start_day = (int(p) for p in custom_start.split('-')[1:])
            end_month, end_day = (int(p) for p in custom_end.split('-')[1:])
            ranges.append((start_month, start_day, end_month, end_day))
        except (ValueError, IndexError):
            pass

    return ranges


def save_recipe_seasons(recipe_id, form):
    """Replaces all of a recipe's RecipeSeason rows with the ranges
    currently selected in the form.

    First deletes ALL existing ranges for this recipe (instead of diffing
    them individually) and recreates them entirely from the form
    content - simpler than a diff, and when creating a new recipe (no
    existing rows yet) the DELETE statement is a no-op. Deliberately does
    NOT commit here itself; that's handled by the calling route handler
    together with the recipe's other changes in the same transaction.
    """
    RecipeSeason.query.filter_by(recipe_id=recipe_id).delete()
    for start_month, start_day, end_month, end_day in parse_recipe_seasons(form):
        db.session.add(RecipeSeason(
            recipe_id=recipe_id,
            start_month=start_month, start_day=start_day,
            end_month=end_month, end_day=end_day
        ))


def describe_recipe_seasons(recipe):
    """Prepares a recipe's season data for the edit view.

    Goes through all of the recipe's RecipeSeason rows and sorts them
    into two categories: exact matches to a standard season (whose
    checkbox should be pre-checked in the form) and everything else (a
    freely chosen custom range). Since the form only has ONE input field
    pair for a custom range, only the FIRST non-standard range is
    returned as custom_range - should a recipe theoretically have several
    custom ranges (e.g. via direct database access), the additional ones
    are lost on the next save.

    Returns: (selected_presets, custom_range) - a set of season names
    (e.g. {"Sommer", "Herbst"}) and either a single RecipeSeason row or
    None.
    """
    selected_presets = set()
    custom_range = None
    for rs in recipe.seasons:
        preset_name = SEASON_PRESET_BY_RANGE.get(_season_range(rs))
        if preset_name:
            selected_presets.add(preset_name)
        elif custom_range is None:
            custom_range = rs
    return selected_presets, custom_range


def format_recipe_seasons(recipe):
    """Builds short, human-readable labels from a recipe's season ranges
    for the badge display in the recipe list.

    A range that matches a standard season exactly is labeled with its
    name ("Sommer"); all other (custom) ranges are formatted as
    "day.month.-day.month." (e.g. "15.5.-20.6."). Returns a list (one
    label per range) so the template can render a separate badge for each
    item.
    """
    labels = []
    for rs in recipe.seasons:
        preset_name = SEASON_PRESET_BY_RANGE.get(_season_range(rs))
        if preset_name:
            labels.append(preset_name)
        else:
            labels.append(f"{rs.start_day}.{rs.start_month}.–{rs.end_day}.{rs.end_month}.")
    return labels
