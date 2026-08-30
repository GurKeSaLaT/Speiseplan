"""Anzeige-Einstellungen EINES Plans (aktuell: bevorzugte Einheiten für
Masse und Volumen, siehe services/units.py und models.py: AppSettings) -
jeder Plan pflegt seine eigene Zeile, unabhängig von anderen Plänen."""

from models import AppSettings, db
from services.units import DEFAULT_DISPLAY_UNIT, DISPLAY_UNIT_CHOICES, MASS, VOLUME


def get_settings(plan_id):
    """Liefert die AppSettings-Zeile EINES Plans, legt sie bei Bedarf lazy
    mit den Standardwerten (g/ml) an, statt dafür einen eigenen
    Migrationsschritt für jeden neu angelegten Plan zu brauchen (siehe
    app.py: init_db() für die einmalige Migration bestehender Bestandsdaten)."""
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
    """Liefert das Dict {'mass': ..., 'volume': ...} für
    services/units.py: convert_for_display()."""
    settings = get_settings(plan_id)
    return {MASS: settings.mass_unit, VOLUME: settings.volume_unit}


def update_display_units(plan_id, mass_unit, volume_unit):
    """Speichert eine neue Anzeige-Einheiten-Wahl für EINEN Plan, sofern
    beide Werte zu den erlaubten Optionen (services/units.py:
    DISPLAY_UNIT_CHOICES) gehören. Gibt True bei Erfolg zurück, False bei
    einem ungültigen Wert (dann bleibt die bisherige Einstellung
    unverändert) - der Aufrufer (routes/settings.py) entscheidet, wie er
    das dem Nutzer meldet."""
    if mass_unit not in DISPLAY_UNIT_CHOICES[MASS] or volume_unit not in DISPLAY_UNIT_CHOICES[VOLUME]:
        return False
    settings = get_settings(plan_id)
    settings.mass_unit = mass_unit
    settings.volume_unit = volume_unit
    db.session.commit()
    return True
