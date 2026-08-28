"""Saison-Zuordnung für Rezepte: Standard-Saisons + eigene Zeiträume,
jahresunabhängig über Monat/Tag, mit Unterstützung für über den Jahreswechsel
laufende Zeiträume (z.B. Winter: Dezember-Februar)."""

from datetime import date

from models import db, RecipeSeason

SEASONS = ['Frühling', 'Sommer', 'Herbst', 'Winter']
# Jahresunabhängige (Monat, Tag)-Zeiträume je Standard-Saison
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
    """Prüft, ob (month, day) in einem jahresunabhängigen Monat/Tag-Zeitraum liegt.
    Unterstützt über den Jahreswechsel laufende Zeiträume (z.B. Winter: Dez-Feb)."""
    current = (month, day)
    start = (start_month, start_day)
    end = (end_month, end_day)
    if start <= end:
        return start <= current <= end
    return current >= start or current <= end


def recipe_available_now(recipe):
    """Ganzjährig verfügbar, wenn das Rezept keine Zeiträume hinterlegt hat -
    sonst verfügbar, sobald heute in mindestens einen davon fällt."""
    if not recipe.seasons:
        return True
    today = date.today()
    return any(date_in_range(today.month, today.day, *_season_range(rs)) for rs in recipe.seasons)


def parse_recipe_seasons(form):
    """Liest die Saison-Auswahl aus dem Formular: mehrere angehakte Standard-
    Saisons und/oder ein eigener Zeitraum. Gibt eine Liste von
    (start_month, start_day, end_month, end_day)-Tupeln zurück."""
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
    RecipeSeason.query.filter_by(recipe_id=recipe_id).delete()
    for start_month, start_day, end_month, end_day in parse_recipe_seasons(form):
        db.session.add(RecipeSeason(
            recipe_id=recipe_id,
            start_month=start_month, start_day=start_day,
            end_month=end_month, end_day=end_day
        ))


def describe_recipe_seasons(recipe):
    """Für die Bearbeiten-Ansicht: welche Standard-Saison-Checkboxen sollen
    angehakt sein, und gibt es einen (ersten) eigenen Zeitraum zum Vorbefüllen?"""
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
    """Kurze, menschenlesbare Labels aller Zeiträume eines Rezepts, für die Badge-Anzeige."""
    labels = []
    for rs in recipe.seasons:
        preset_name = SEASON_PRESET_BY_RANGE.get(_season_range(rs))
        if preset_name:
            labels.append(preset_name)
        else:
            labels.append(f"{rs.start_day}.{rs.start_month}.–{rs.end_day}.{rs.end_month}.")
    return labels
