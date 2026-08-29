"""Globale Anzeige-Einstellungen (aktuell: bevorzugte Einheiten für Masse
und Volumen, siehe services/units.py und models.py: AppSettings). Eine
einzelne Singleton-Zeile statt einer generischen Key-Value-Tabelle, da es
bislang nur diese zwei Einstellungen gibt."""

from models import AppSettings, db
from services.units import DEFAULT_DISPLAY_UNIT, DISPLAY_UNIT_CHOICES, MASS, VOLUME

SETTINGS_ROW_ID = 1


def get_settings():
    """Liefert die Singleton-AppSettings-Zeile, legt sie bei Bedarf lazy
    mit den Standardwerten (g/ml - identisch zum bisherigen, ungefragten
    Verhalten der App) an, statt dafür einen eigenen Migrationsschritt in
    app.py zu brauchen."""
    settings = db.session.get(AppSettings, SETTINGS_ROW_ID)
    if not settings:
        settings = AppSettings(
            id=SETTINGS_ROW_ID,
            mass_unit=DEFAULT_DISPLAY_UNIT[MASS],
            volume_unit=DEFAULT_DISPLAY_UNIT[VOLUME],
        )
        db.session.add(settings)
        db.session.commit()
    return settings


def get_display_units():
    """Liefert das Dict {'mass': ..., 'volume': ...} für
    services/units.py: convert_for_display()."""
    settings = get_settings()
    return {MASS: settings.mass_unit, VOLUME: settings.volume_unit}


def update_display_units(mass_unit, volume_unit):
    """Speichert eine neue Anzeige-Einheiten-Wahl, sofern beide Werte zu
    den erlaubten Optionen (services/units.py: DISPLAY_UNIT_CHOICES)
    gehören. Gibt True bei Erfolg zurück, False bei einem ungültigen Wert
    (dann bleibt die bisherige Einstellung unverändert) - der Aufrufer
    (routes/settings.py) entscheidet, wie er das dem Nutzer meldet."""
    if mass_unit not in DISPLAY_UNIT_CHOICES[MASS] or volume_unit not in DISPLAY_UNIT_CHOICES[VOLUME]:
        return False
    settings = get_settings()
    settings.mass_unit = mass_unit
    settings.volume_unit = volume_unit
    db.session.commit()
    return True
