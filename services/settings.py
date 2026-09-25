"""Per-plan display units."""

from models import AppSettings, db
from services.units import DEFAULT_DISPLAY_UNIT, DISPLAY_UNIT_CHOICES, MASS, VOLUME


def get_settings(plan_id):
    """Creates the row with defaults on first access."""
    settings = AppSettings.query.filter_by(plan_id=plan_id).first()
    if not settings:
        settings = AppSettings(
            plan_id=plan_id,
            mass_unit=DEFAULT_DISPLAY_UNIT[MASS],
            volume_unit=DEFAULT_DISPLAY_UNIT[VOLUME],
        )
        db.session.add(settings)
        db.session.commit()
    return settings


def get_display_units(plan_id):
    settings = get_settings(plan_id)
    return {MASS: settings.mass_unit, VOLUME: settings.volume_unit}


def update_display_units(plan_id, mass_unit, volume_unit):
    """False (and no change) for values outside DISPLAY_UNIT_CHOICES."""
    if mass_unit not in DISPLAY_UNIT_CHOICES[MASS] or volume_unit not in DISPLAY_UNIT_CHOICES[VOLUME]:
        return False
    settings = get_settings(plan_id)
    settings.mass_unit = mass_unit
    settings.volume_unit = volume_unit
    db.session.commit()
    return True
