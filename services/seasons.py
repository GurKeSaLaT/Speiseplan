"""Seasonal availability of recipes.

A recipe has zero or more year-independent month/day ranges (standard
seasons and/or one custom range); ranges may wrap around New Year. No
ranges = available year-round. Seasons only steer automatic selection,
never manual picks.
"""

from datetime import date

from models import db, RecipeSeason

# German on purpose: these are form values and SEASON_PRESETS keys, i.e.
# data identifiers, not just display text.
SEASONS = ['Frühling', 'Sommer', 'Herbst', 'Winter']

# (start_month, start_day, end_month, end_day); winter wraps around New Year.
SEASON_PRESETS = {
    'Frühling': (3, 1, 5, 31),
    'Sommer': (6, 1, 8, 31),
    'Herbst': (9, 1, 11, 30),
    'Winter': (12, 1, 2, 28),
}

SEASON_PRESET_BY_RANGE = {v: k for k, v in SEASON_PRESETS.items()}


def _season_range(rs):
    return (rs.start_month, rs.start_day, rs.end_month, rs.end_day)


def date_in_range(month, day, start_month, start_day, end_month, end_day):
    """start > end means the range wraps around New Year."""
    current = (month, day)
    start = (start_month, start_day)
    end = (end_month, end_day)
    if start <= end:
        return start <= current <= end
    return current >= start or current <= end


def recipe_available_now(recipe):
    """True without ranges, otherwise if today falls in any of them."""
    if not recipe.seasons:
        return True
    today = date.today()
    return any(date_in_range(today.month, today.day, *_season_range(rs)) for rs in recipe.seasons)


def parse_recipe_seasons(form):
    """Range tuples from the form's season checkboxes plus the custom range
    (only if both dates are set; the year is ignored, invalid input is
    skipped)."""
    ranges = []
    for season_name in form.getlist('seasons'):
        preset = SEASON_PRESETS.get(season_name)
        if preset:
            ranges.append(preset)

    custom_start = form.get('season_custom_start')
    custom_end = form.get('season_custom_end')
    if custom_start and custom_end:
        try:
            start_month, start_day = (int(p) for p in custom_start.split('-')[1:])
            end_month, end_day = (int(p) for p in custom_end.split('-')[1:])
            ranges.append((start_month, start_day, end_month, end_day))
        except (ValueError, IndexError):
            pass

    return ranges


def save_recipe_seasons(recipe_id, form):
    """Replaces the recipe's ranges; the caller commits."""
    RecipeSeason.query.filter_by(recipe_id=recipe_id).delete()
    for start_month, start_day, end_month, end_day in parse_recipe_seasons(form):
        db.session.add(RecipeSeason(
            recipe_id=recipe_id,
            start_month=start_month, start_day=start_day,
            end_month=end_month, end_day=end_day
        ))


def describe_recipe_seasons(recipe):
    """(selected preset names, first custom range or None) for the edit
    form, which has room for only one custom range."""
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
    """Badge labels: preset names, or "15.5.–20.6." for custom ranges."""
    labels = []
    for rs in recipe.seasons:
        preset_name = SEASON_PRESET_BY_RANGE.get(_season_range(rs))
        if preset_name:
            labels.append(preset_name)
        else:
            labels.append(f"{rs.start_day}.{rs.start_month}.–{rs.end_day}.{rs.end_month}.")
    return labels
