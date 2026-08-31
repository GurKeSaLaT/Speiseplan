"""Display settings of A SINGLE plan (currently: preferred units for mass
and volume, see services/units.py and models/settings.py: AppSettings) - each plan
maintains its own row, independent of other plans."""

from models import AppSettings, db
from services.units import DEFAULT_DISPLAY_UNIT, DISPLAY_UNIT_CHOICES, MASS, VOLUME


def get_settings(plan_id):
    """Returns the AppSettings row of A SINGLE plan, lazily creating it with
    the default values (g/ml) if needed, instead of requiring a separate
    migration step for every newly created plan (see migrations.py: init_db() for
    the one-time migration of existing legacy data)."""
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
    """Returns the dict {'mass': ..., 'volume': ...} for
    services/units.py: convert_for_display()."""
    settings = get_settings(plan_id)
    return {MASS: settings.mass_unit, VOLUME: settings.volume_unit}


def update_display_units(plan_id, mass_unit, volume_unit):
    """Saves a new display-unit choice for A SINGLE plan, provided both
    values are among the allowed options (services/units.py:
    DISPLAY_UNIT_CHOICES). Returns True on success, False for an invalid
    value (the previous setting then remains unchanged) - the caller
    (routes/settings.py) decides how to report that to the user."""
    if mass_unit not in DISPLAY_UNIT_CHOICES[MASS] or volume_unit not in DISPLAY_UNIT_CHOICES[VOLUME]:
        return False
    settings = get_settings(plan_id)
    settings.mass_unit = mass_unit
    settings.volume_unit = volume_unit
    db.session.commit()
    return True
