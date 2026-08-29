"""Einheiten-Einstellungen: eine Seite, auf der sich festlegen lässt, in
welcher Einheit Zutatenmengen angezeigt werden sollen (Masse: Gramm oder
Kilogramm, Volumen: Milliliter oder Liter) - siehe services/units.py für
die eigentliche Umrechnung und services/settings.py für die Speicherung.
Ändert NICHT, wie Mengen intern gespeichert werden (immer kanonisch g/ml),
nur wie sie in Formularen/der Einkaufsliste dargestellt werden."""

from flask import Blueprint, redirect, render_template, request, url_for

from services.settings import get_settings, update_display_units
from services.units import DISPLAY_UNIT_CHOICES, MASS, VOLUME

settings_bp = Blueprint('settings', __name__)


@settings_bp.route('/manage/units')
def units_view():
    """Zeigt die aktuell gewählten Anzeige-Einheiten sowie die jeweils
    verfügbaren Optionen (DISPLAY_UNIT_CHOICES) - das Template baut daraus
    die beiden Radio-Gruppen."""
    settings = get_settings()
    return render_template(
        'units_manage.html', settings=settings,
        mass_choices=DISPLAY_UNIT_CHOICES[MASS], volume_choices=DISPLAY_UNIT_CHOICES[VOLUME],
    )


@settings_bp.route('/update-units', methods=['POST'])
def update_units():
    """Speichert die im Formular gewählten Anzeige-Einheiten. Ein
    ungültiger Wert (z.B. durch manipulierte Formulardaten) wird von
    update_display_units() abgelehnt - die Einstellung bleibt dann
    unverändert, statt einen 500er zu werfen oder einen unsinnigen Wert
    zu speichern."""
    mass_unit = request.form.get('mass_unit', '')
    volume_unit = request.form.get('volume_unit', '')
    update_display_units(mass_unit, volume_unit)
    return redirect(url_for('settings.units_view'))
