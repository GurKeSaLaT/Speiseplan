"""Einstellungs-Seiten der App: aktuell zwei thematisch getrennte
Bereiche, die sich beide dieses eine Blueprint teilen (analog zum
routes/plan/-Paket - hier aber in einer einzigen, überschaubaren Datei
statt eines eigenen Pakets, da beide Bereiche klein sind):

1. Einheiten (units_view/update_units): in welcher Einheit Zutatenmengen
   angezeigt werden sollen (Masse: Gramm/Kilogramm, Volumen: Milliliter/
   Liter) - siehe services/units.py für die eigentliche Umrechnung und
   services/settings.py für die Speicherung. Ändert NICHT, wie Mengen
   intern gespeichert werden (immer kanonisch g/ml), nur wie sie in
   Formularen/der Einkaufsliste dargestellt werden.

2. Zutaten gleichsetzen (ingredient_aliases_view/update_ingredient_aliases):
   welche konkreten Zutatennamen (z.B. "Spaghetti", "Fusilli") für die
   Einkaufsliste als derselbe Posten gelten sollen (z.B. "Nudeln") - siehe
   services/ingredient_aliases.py. Ändert NICHT die in einem Rezept
   angezeigten Zutatennamen, nur die Gruppierung auf der Einkaufsliste.
"""

from flask import Blueprint, redirect, render_template, request, url_for

from services.ingredient_aliases import get_all_aliases, list_known_ingredient_names, set_alias
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


@settings_bp.route('/manage/ingredient-aliases')
def ingredient_aliases_view():
    """Zeigt JEDEN aktuell in irgendeinem Rezept verwendeten Zutatennamen
    als eigene Zeile mit einem editierbaren "gilt als"-Feld, vorbefüllt
    mit dem gepflegten kanonischen Namen oder (ohne bestehenden Alias) dem
    Namen selbst - so lässt sich auf einen Blick erkennen, welche Namen
    bereits einer Gruppe zugeordnet sind."""
    aliases = get_all_aliases()
    rows = [
        {"raw_name": name, "canonical_name": aliases.get(name, name)}
        for name in list_known_ingredient_names()
    ]
    return render_template('ingredient_aliases_manage.html', rows=rows)


@settings_bp.route('/update-ingredient-aliases', methods=['POST'])
def update_ingredient_aliases():
    """Speichert ALLE Zeilen des Formulars auf einmal (raw_name[]/
    canonical_name[], parallele Listen wie bei den Zutatenzeilen der
    Rezept-Formulare) statt eines Buttons pro Zeile - bei potenziell
    hunderten Zutatennamen wäre ein einzelner Rundtrip pro Zeile
    unpraktisch. set_alias() löscht einen Alias automatisch wieder, wenn
    der eingetragene Name mit dem Original übereinstimmt (siehe dort)."""
    raw_names = request.form.getlist('raw_name[]')
    canonical_names = request.form.getlist('canonical_name[]')
    for raw_name, canonical_name in zip(raw_names, canonical_names):
        set_alias(raw_name, canonical_name)
    return redirect(url_for('settings.ingredient_aliases_view'))
