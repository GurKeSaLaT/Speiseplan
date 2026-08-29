"""Einstellungs-Seiten der App: aktuell drei thematisch getrennte
Bereiche, die sich beide dieses eine Blueprint teilen (analog zum
routes/plan/-Paket - hier aber in einer einzigen, überschaubaren Datei
statt eines eigenen Pakets, da alle drei Bereiche klein sind):

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

3. Nährwerte (ingredient_nutrition_view/update_ingredient_nutrition): die
   Nährwert-Referenz je kanonischer Zutat (siehe services/nutrition.py),
   aus der Rezept-Nährwerte automatisch berechnet werden (siehe
   routes/recipes.py: add_recipe()/edit_recipe()).
"""

from flask import Blueprint, redirect, render_template, request, url_for

from services.ingredient_aliases import (
    get_all_aliases, list_known_ingredient_names, normalize_ingredient_name, normalize_name, set_alias,
)
from services.nutrition import (
    get_all_nutrition_entries, infer_reference_unit, list_alias_canonical_names, set_nutrition,
)
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


@settings_bp.route('/api/ingredient-alias/set', methods=['POST'])
def api_set_ingredient_alias():
    """AJAX-Gegenstück zu update_ingredient_aliases() oben: setzt GENAU
    EINEN Alias sofort beim Eintragen einer Zutat in recipe_create.html/
    recipe_edit_list.html, ohne die Seite zu verlassen (siehe
    static/ingredient_alias_hint.js - der "Alias setzen"-Button dort, der
    beim Fall "weder Alias noch Grundzutat" erscheint).

    Erwartet einen JSON-Body {"raw_name": str, "canonical_name": str}.
    Gibt die NORMALISIERTEN Werte zurück, damit das Frontend seine lokale
    Kopie von window.INGREDIENT_ALIASES konsistent mit dem
    Nachschlage-Schlüssel aktualisieren kann, den auch der Server
    verwendet (siehe services/ingredient_aliases.py: normalize_name)."""
    data = request.get_json() or {}
    raw_name = (data.get('raw_name') or '').strip()
    canonical_name = (data.get('canonical_name') or '').strip()
    if not raw_name or not canonical_name:
        return {"error": "Name und Alias dürfen nicht leer sein."}, 400

    set_alias(raw_name, canonical_name)
    return {
        "ok": True,
        "raw_name": normalize_name(raw_name),
        "canonical_name": normalize_ingredient_name(raw_name),
    }


def _parse_nutrition_form_values(data):
    """Liest die sechs Nährwert-Felder aus einem JSON-Body (dict-artig,
    .get()) und wandelt sie robust in Zahlen um - ein leeres oder
    ungültiges Feld wird zu 0 statt eines Fehlers, analog zu den übrigen
    Formular-Parsern in dieser App (z.B. routes/recipes.py: add_recipe())."""
    def _num(key, cast, default=0):
        try:
            return cast(data.get(key) or default)
        except (TypeError, ValueError):
            return default

    return {
        "reference_amount": _num("reference_amount", float, 100),
        "reference_unit": (data.get("reference_unit") or "g").strip(),
        "calories": _num("calories", int),
        "protein": _num("protein", float),
        "carbs": _num("carbs", float),
        "fat": _num("fat", float),
    }


@settings_bp.route('/api/ingredient-nutrition/set', methods=['POST'])
def api_set_ingredient_nutrition():
    """AJAX-Endpunkt für den Inline-Hinweis beim Zutat-Eintragen (siehe
    static/ingredient_alias_hint.js): trägt sofort einen Nährwert für eine
    Zutat nach, ohne die Rezept-Seite zu verlassen - genau dann angeboten,
    wenn window.INGREDIENT_NUTRITION für die aufgelöste kanonische Zutat
    noch keinen Eintrag hat.

    Erwartet einen JSON-Body {"name": str, "reference_amount": Zahl,
    "reference_unit": str, "calories"/"protein"/"carbs"/"fat": Zahl}."""
    data = request.get_json() or {}
    name = (data.get('name') or '').strip()
    if not name:
        return {"error": "Zutatenname darf nicht leer sein."}, 400

    values = _parse_nutrition_form_values(data)
    entry = set_nutrition(name, **values)
    return {
        "ok": True,
        "canonical_name": entry.canonical_name,
        "reference_amount": entry.reference_amount,
        "reference_unit": entry.reference_unit,
        "calories": entry.calories,
        "protein": entry.protein,
        "carbs": entry.carbs,
        "fat": entry.fat,
    }


@settings_bp.route('/manage/ingredient-nutrition')
def ingredient_nutrition_view():
    """Zeigt NUR die tatsächlichen Alias-Zielnamen (services/nutrition.py:
    list_alias_canonical_names() - z.B. "Nudeln", "Öl", NICHT jede
    unaliasierte Einzelzutat) mit editierbaren Nährwert-Feldern, vorbefüllt
    mit dem gepflegten Eintrag oder (ohne bestehenden Eintrag) mit
    sinnvollen Standardwerten (Referenzmenge 100, Referenzeinheit anhand
    der tatsächlich verwendeten Zutat-Zeilen geraten, siehe
    infer_reference_unit()) - unaliasierte Einzelzutaten bekommen ihren
    Nährwert stattdessen direkt beim Zutat-Eintragen nachgetragen (siehe
    api_set_ingredient_nutrition oben)."""
    entries = get_all_nutrition_entries()
    rows = []
    for name in list_alias_canonical_names():
        entry = entries.get(name)
        rows.append({
            "canonical_name": name,
            "reference_amount": entry["reference_amount"] if entry else 100,
            "reference_unit": entry["reference_unit"] if entry else infer_reference_unit(name),
            "calories": entry["calories"] if entry else 0,
            "protein": entry["protein"] if entry else 0,
            "carbs": entry["carbs"] if entry else 0,
            "fat": entry["fat"] if entry else 0,
            "has_entry": entry is not None,
        })
    return render_template('ingredient_nutrition_manage.html', rows=rows)


@settings_bp.route('/update-ingredient-nutrition', methods=['POST'])
def update_ingredient_nutrition():
    """Speichert ALLE Zeilen des Formulars auf einmal (parallele Listen,
    analog zu update_ingredient_aliases() oben) statt eines Buttons pro
    Zeile."""
    names = request.form.getlist('canonical_name[]')
    reference_amounts = request.form.getlist('reference_amount[]')
    reference_units = request.form.getlist('reference_unit[]')
    calories_list = request.form.getlist('calories[]')
    protein_list = request.form.getlist('protein[]')
    carbs_list = request.form.getlist('carbs[]')
    fat_list = request.form.getlist('fat[]')

    for i, name in enumerate(names):
        values = _parse_nutrition_form_values({
            "reference_amount": reference_amounts[i] if i < len(reference_amounts) else None,
            "reference_unit": reference_units[i] if i < len(reference_units) else None,
            "calories": calories_list[i] if i < len(calories_list) else None,
            "protein": protein_list[i] if i < len(protein_list) else None,
            "carbs": carbs_list[i] if i < len(carbs_list) else None,
            "fat": fat_list[i] if i < len(fat_list) else None,
        })
        set_nutrition(name, **values)

    return redirect(url_for('settings.ingredient_nutrition_view'))
