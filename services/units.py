"""Einheiten-Normalisierung für Zutatenmengen (Ingredient.amount/.unit).

Fasst unterschiedliche Schreibweisen derselben Einheit zusammen (z.B.
"g"/"Gramm"/"gr" oder "kg"/"Kilogramm"/"Kilo") und wandelt Mengen aus
Familien mit einer eindeutigen Basiseinheit - Masse -> Gramm, Volumen ->
Milliliter (inkl. Küchenmaßen wie TL/EL/Tasse, siehe _CONVERSIONS unten) -
beim Speichern IMMER auf diese Basis um, unabhängig von der eingegebenen/
importierten Schreibweise oder Größenordnung ("1kg" wird zu "1000g",
"2 EL" zu "30 ml"). normalize_amount_unit() übernimmt das sowohl für die
manuelle Rezepteingabe (routes/recipes.py) als auch für den Import
(services/recipe_import.py) sowie einmalig für Bestandsdaten
(renormalize_existing_ingredients(), aufgerufen aus app.py: init_db()).

Dass ALLE Ingredient-Zeilen einer Familie in der Datenbank dieselbe
Einheit tragen, ist die Voraussetzung dafür, dass die Einkaufsliste
(static/plan-shopping.js: rebuildShoppingList) gleichnamige Zutaten über
mehrere Rezepte hinweg korrekt aufsummieren kann - sie gruppiert dort rein
nach "Name+Einheit", ohne selbst etwas umzurechnen.

Angezeigt wird trotzdem in der vom Nutzer gewählten Einheit (siehe
services/settings.py: AppSettings) - convert_for_display() rechnet dafür
NUR fürs Anzeigen zurück, ohne den gespeicherten (kanonischen) Wert zu
verändern. Da die Umrechnung (Faktor 1000 bzw. 1) exakt und ohne
Rundungsverlust umkehrbar ist, dürfen Templates diese Anzeige-Werte auch
direkt wieder in ein Formularfeld einsetzen (siehe recipe_edit_list.html)
- ein Speichern ohne Änderung liefert über normalize_amount_unit() wieder
exakt denselben kanonischen Wert.

Küchenmaße (TL/EL/Tasse) sind bewusst Teil der Volumen-Familie (feste,
in der Küche gebräuchliche Näherungswerte: 1 TL=5ml, 1 EL=15ml,
1 Tasse/cup=250ml) - exakter geht es bei diesen Maßen ohnehin nicht, da
sie je nach Zutat/Gefäß leicht variieren.
"""

from models import Ingredient, db

MASS = 'mass'
VOLUME = 'volume'

BASE_UNIT = {MASS: 'g', VOLUME: 'ml'}

# Für die Einstellungen-Seite (routes/settings.py) wählbare Anzeige-
# Einheiten je Familie - jeweils Basiseinheit zuerst (Standard).
DISPLAY_UNIT_CHOICES = {MASS: ['g', 'kg'], VOLUME: ['ml', 'l']}
DEFAULT_DISPLAY_UNIT = {MASS: 'g', VOLUME: 'ml'}

# Schlüssel: normalisierte Schreibweise (klein, ohne abschließenden Punkt -
# siehe _normalize_key). Wert: (Familie, Faktor zur Basiseinheit der
# Familie). Nicht erschöpfend, deckt aber die auf den in
# services/recipe_import.py: ALLOWED_HOSTS gelisteten Seiten sowie bei
# manueller Eingabe gebräuchlichen Schreibweisen ab.
_CONVERSIONS = {
    # Masse (Basis: Gramm)
    'g': (MASS, 1), 'gr': (MASS, 1), 'gramm': (MASS, 1),
    'mg': (MASS, 0.001), 'milligramm': (MASS, 0.001),
    'dkg': (MASS, 10), 'deka': (MASS, 10), 'dekagramm': (MASS, 10),  # in Österreich gebräuchlich
    'kg': (MASS, 1000), 'kilo': (MASS, 1000), 'kilogramm': (MASS, 1000),
    # Volumen (Basis: Milliliter) - inkl. Küchenmaßen, siehe Moduldocstring
    'ml': (VOLUME, 1), 'milliliter': (VOLUME, 1),
    'cl': (VOLUME, 10), 'zentiliter': (VOLUME, 10),
    'l': (VOLUME, 1000), 'liter': (VOLUME, 1000),
    'tl': (VOLUME, 5), 'teel': (VOLUME, 5), 'teelöffel': (VOLUME, 5),
    'el': (VOLUME, 15), 'essl': (VOLUME, 15), 'esslöffel': (VOLUME, 15),
    'tasse': (VOLUME, 250), 'tassen': (VOLUME, 250), 'cup': (VOLUME, 250), 'cups': (VOLUME, 250),
}

# Weitere, in KNOWN_UNITS (services/recipe_import.py) erkannte, aber NICHT
# umrechenbare Einheiten (stückbasiert / kein eindeutiges metrisches
# Äquivalent) - bleiben bei normalize_amount_unit() unverändert, zählen
# aber weiterhin als "bekannte Einheit" (siehe known_unit_keys()), damit
# _parse_ingredient_line() das folgende Wort korrekt als Einheit statt als
# Teil des Zutatennamens erkennt.
NON_CONVERTIBLE_UNITS = {
    'stk', 'stk.', 'stück', 'stange', 'stangen', 'bund', 'bünde',
    'dose', 'dosen', 'päckchen', 'zehe', 'zehen', 'scheibe', 'scheiben',
    'blatt', 'blätter', 'glas', 'gläser', 'würfel', 'kugel', 'kugeln',
    'packung', 'packungen', 'becher', 'msp', 'msp.', 'prise', 'prisen',
}


def _normalize_key(raw_unit):
    return (raw_unit or '').strip().lower().rstrip('.')


def known_unit_keys():
    """Alle erkannten Einheiten-Schreibweisen (klein, ohne Punkt) - Basis
    für KNOWN_UNITS in services/recipe_import.py, damit dort dieselbe
    Liste gilt wie hier bei der eigentlichen Umrechnung."""
    return set(_CONVERSIONS) | NON_CONVERTIBLE_UNITS


def normalize_amount_unit(raw_amount, raw_unit):
    """Wandelt eine eingegebene/importierte Menge+Einheit in die
    kanonische Form ihrer Familie um, z.B. (1, "kg") -> (1000, "g") oder
    (2, "EL") -> (30, "ml"). Unbekannte oder nicht umrechenbare Einheiten
    (Stk, Prise, Bund, ein frei eingetipptes Wort, ...) kommen unverändert
    zurück - nur ihre SCHREIBWEISE wird nicht vereinheitlicht ("Stk"/"stk"
    bleiben z.B. beide bestehen), das ist bewusst kein Ziel dieser
    Funktion, die sich nur um Mengen mit eindeutigem SI-Äquivalent kümmert."""
    conv = _CONVERSIONS.get(_normalize_key(raw_unit))
    if not conv:
        return raw_amount, raw_unit
    family, factor = conv
    return raw_amount * factor, BASE_UNIT[family]


def convert_for_display(amount, unit, display_units):
    """Rechnet eine KANONISCHE Menge+Einheit (siehe normalize_amount_unit)
    für die Anzeige in die vom Nutzer gewählte Einheit um (z.B. Gramm ->
    Kilogramm), OHNE den gespeicherten Wert selbst zu verändern.

    display_units ist ein Dict {'mass': 'g'|'kg', 'volume': 'ml'|'l'}
    (siehe services/settings.py: get_display_units()). Einheiten außerhalb
    der beiden Basiseinheiten g/ml (z.B. Stk, Prise) bleiben unverändert,
    ebenso wenn die gewählte Anzeige-Einheit ohnehin der Basiseinheit
    entspricht. Rundet auf 3 Nachkommastellen, um Fließkomma-Artefakte der
    Division zu vermeiden (z.B. 700g/1000 -> 0.7kg statt 0.6999999...)."""
    if unit == BASE_UNIT[MASS] and display_units.get(MASS) == 'kg':
        return round(amount / 1000, 3), 'kg'
    if unit == BASE_UNIT[VOLUME] and display_units.get(VOLUME) == 'l':
        return round(amount / 1000, 3), 'l'
    return amount, unit


def renormalize_existing_ingredients():
    """Migriert BESTEHENDE Ingredient-Zeilen einmalig auf die kanonische
    Form (siehe normalize_amount_unit) - wird aus app.py: init_db() bei
    jedem App-Start aufgerufen. Idempotent wie die übrigen dortigen
    Migrationsschritte: eine bereits kanonische Zeile (z.B. amount=1000,
    unit="g") ergibt bei erneuter Normalisierung denselben Wert und wird
    dadurch übersprungen, ein wiederholter Aufruf tut also nichts mehr.
    Committet selbst, analog zu den übrigen Migrationsschritten in
    app.py: init_db()."""
    changed = False
    for ingredient in Ingredient.query.all():
        new_amount, new_unit = normalize_amount_unit(ingredient.amount, ingredient.unit)
        if new_amount != ingredient.amount or new_unit != ingredient.unit:
            ingredient.amount = new_amount
            ingredient.unit = new_unit
            changed = True
    if changed:
        db.session.commit()
