"""Rezept-Import von externen Kochseiten - aktuell ausschließlich
chefkoch.de (siehe ALLOWED_HOSTS unten).

Funktionsweise: fetch_recipe_from_url() lädt die Seite server-seitig
(requests) und liest daraus NICHT das sichtbare HTML aus, sondern die
eingebetteten strukturierten Daten im schema.org/Recipe-Format
(https://schema.org/Recipe), die chefkoch.de wie die meisten Rezeptseiten
als <script type="application/ld+json">-Block einbettet - dafür crawlen
Suchmaschinen sie u.a. mit "Portionsrechner"-Vorschau in den Suchergebnissen.
Das macht den Import robust gegenüber Layout-/Design-Änderungen der Seite,
die ein Parsen des sichtbaren HTML (CSS-Selektoren etc.) sofort brechen
würden - das JSON-LD-Format ändert sich praktisch nie, weil es fester
Google-/Suchmaschinen-Standard ist.

Das Ergebnis ist bewusst nur eine VORSCHAU, kein direkt gespeichertes
Rezept: routes/recipes.py: import_recipe_preview() liefert das geparste
Dict als JSON an die Erstellen-Seite, die damit das normale Formular
vorbefüllt (siehe recipe_create.html) - der Nutzer sieht und bearbeitet
alles (insbesondere die Kategorie, die sich nicht zuverlässig auf unsere
eigenen Kategorien abbilden lässt) BEVOR irgendetwas gespeichert wird.
Kein Automatismus dieser Datei schreibt selbst in die Datenbank.
"""

import json
import re
from urllib.parse import urlparse

import requests

# Nur chefkoch.de wird aktuell unterstützt (explizite Vorgabe) - auch aus
# Sicherheitsgründen: fetch_recipe_from_url() lässt die App server-seitig
# eine vom Nutzer eingegebene URL abrufen (ein Server-Side-Request-Forgery-
# Risiko, wenn beliebige URLs erlaubt wären, z.B. Adressen im eigenen
# Heimnetz). Die Domain-Prüfung unten VOR jedem Request schließt das
# zuverlässig - ein Erweitern auf weitere schema.org/Recipe-kompatible
# Seiten (die meisten großen Kochseiten unterstützen dasselbe Format) wäre
# später einfach ein Hinzufügen weiterer Domains hier.
ALLOWED_HOSTS = {'chefkoch.de', 'www.chefkoch.de'}

# Eigener User-Agent statt des python-requests-Standards, den manche Seiten
# blockieren - ein plausibler Browser-artiger String reicht dafür.
REQUEST_HEADERS = {'User-Agent': 'Mozilla/5.0 (compatible; SpeiseplanImport/1.0)'}
REQUEST_TIMEOUT_SECONDS = 10

# Erkannte Mengeneinheiten (klein geschrieben, mit denen der jeweils erste
# Wortteil nach der erkannten Menge verglichen wird - siehe
# _parse_ingredient_line). Nicht erschöpfend, deckt aber die auf chefkoch.de
# gebräuchlichen Angaben ab; ein unbekanntes Wort landet einfach als Teil
# des Zutatennamens statt als eigene Einheit - der Import bleibt dadurch
# immer noch benutzbar, nur die Spalten-Aufteilung ungenauer.
KNOWN_UNITS = {
    'g', 'kg', 'mg', 'ml', 'l', 'cl',
    'el', 'tl', 'msp', 'msp.', 'prise', 'prisen',
    'stk', 'stk.', 'stück', 'stange', 'stangen', 'bund', 'bünde',
    'dose', 'dosen', 'päckchen', 'zehe', 'zehen', 'scheibe', 'scheiben',
    'blatt', 'blätter', 'tasse', 'tassen', 'glas', 'gläser', 'würfel',
    'kugel', 'kugeln', 'packung', 'packungen', 'becher',
}


class RecipeImportError(Exception):
    """Wird mit einer bereits deutschen, direkt an den Nutzer anzeigbaren
    Fehlermeldung ausgelöst (siehe routes/recipes.py:
    import_recipe_preview, die genau diese Message 1:1 als JSON-Fehler
    zurückgibt) - kein technischer Exception-Text, der übersetzt werden
    müsste."""
    pass


def fetch_recipe_from_url(url):
    """Lädt url, sucht darin ein schema.org/Recipe-JSON-LD-Objekt und gibt
    ein normalisiertes Dict zurück:
    {name, servings, calories, protein, carbs, fat, instructions,
     source_url, ingredients: [{name, amount, unit}, ...]}

    Wirft RecipeImportError bei jedem erwarteten Fehlschlag (nicht
    unterstützte Domain, Netzwerkfehler, kein Rezept auf der Seite
    gefunden) - der Aufrufer muss dafür keine verschiedenen
    Exception-Typen unterscheiden.
    """
    parsed_url = urlparse(url)
    if parsed_url.scheme not in ('http', 'https') or parsed_url.hostname not in ALLOWED_HOSTS:
        raise RecipeImportError('Der Import unterstützt aktuell nur Links von chefkoch.de.')

    try:
        response = requests.get(url, headers=REQUEST_HEADERS, timeout=REQUEST_TIMEOUT_SECONDS)
    except requests.RequestException:
        raise RecipeImportError('Die Seite konnte nicht geladen werden.')

    # response.url ist die Adresse NACH etwaigen Redirects - wird hier
    # erneut geprüft, damit ein chefkoch.de-Link, der (aus welchem Grund
    # auch immer) auf eine fremde Domain umleitet, nicht stillschweigend
    # dort landet (dieselbe SSRF-Überlegung wie beim Eingabe-Check oben).
    if urlparse(response.url).hostname not in ALLOWED_HOSTS:
        raise RecipeImportError('Der Link führt nicht zu einer Seite auf chefkoch.de.')
    if not response.ok:
        raise RecipeImportError(f'Die Seite konnte nicht geladen werden (Status {response.status_code}).')

    recipe_json = _find_recipe_json_ld(response.text)
    if recipe_json is None:
        raise RecipeImportError('Auf dieser Seite wurde kein Rezept gefunden.')

    return {
        'name': _clean_name(recipe_json.get('name') or ''),
        'servings': _parse_servings(recipe_json.get('recipeYield')),
        'calories': _parse_nutrition_value(recipe_json, 'calories'),
        'protein': _parse_nutrition_value(recipe_json, 'proteinContent'),
        'carbs': _parse_nutrition_value(recipe_json, 'carbohydrateContent'),
        'fat': _parse_nutrition_value(recipe_json, 'fatContent'),
        'instructions': _flatten_instructions(recipe_json.get('recipeInstructions')),
        'source_url': response.url,
        'ingredients': [
            _parse_ingredient_line(line) for line in (recipe_json.get('recipeIngredient') or [])
            if line and line.strip()
        ],
    }


def _find_recipe_json_ld(html):
    """Durchsucht alle <script type="application/ld+json">-Blöcke der
    Seite nach einem Objekt mit "@type": "Recipe" - sowohl direkt als
    Top-Level-Objekt/-Liste als auch (der bei chefkoch.de übliche Fall)
    verschachtelt unter einem "@graph"-Schlüssel, der mehrere zusammen-
    gehörige Objekte (Recipe, WebPage, Organization, ...) einer Seite
    bündelt. Gibt None zurück, wenn kein solches Objekt gefunden wird
    (z.B. weil die URL gar keine Rezeptseite ist), statt eine Exception zu
    werfen - der Aufrufer wandelt das in eine einheitliche
    RecipeImportError um.
    """
    for block in re.findall(r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', html, re.S):
        try:
            data = json.loads(block.strip())
        except (json.JSONDecodeError, ValueError):
            continue

        candidates = data.get('@graph', []) if isinstance(data, dict) else data if isinstance(data, list) else [data]
        for candidate in candidates:
            if isinstance(candidate, dict) and candidate.get('@type') == 'Recipe':
                return candidate
    return None


def _clean_name(raw_name):
    """chefkoch.de hängt an den Rezeptnamen im JSON-LD durchgängig
    " von <Nutzername>" an (z.B. "Ligurische Nudeln von laufmasche") - wird
    hier abgeschnitten, da der Autorenname für unsere Rezeptdatenbank
    irrelevant ist. Kommt der Name ausnahmsweise ohne diesen Zusatz (oder
    mit einem anderen Format), bleibt er unverändert."""
    return re.sub(r'\s+von\s+\S+\s*$', '', raw_name.strip()).strip()


def _parse_servings(recipe_yield):
    """recipeYield ist im Recipe-Schema entweder ein einzelner String
    ("4 Portionen"), eine Zahl, oder (bei chefkoch.de) eine Liste, deren
    erster Eintrag die reine Zahl als String ist (z.B. ["4", "4 Portionen"]).
    Extrahiert daraus die erste gefundene Ganzzahl; ohne einen einzigen
    Treffer wird 2 als Standardwert verwendet (derselbe Default wie beim
    manuellen Rezept-Anlegen, siehe recipe_create.html)."""
    if isinstance(recipe_yield, list):
        recipe_yield = recipe_yield[0] if recipe_yield else ''
    match = re.search(r'\d+', str(recipe_yield or ''))
    return int(match.group()) if match else 2


def _parse_nutrition_value(recipe_json, field_name):
    """Liest ein einzelnes Nährwert-Feld aus dem verschachtelten
    "nutrition"-Objekt (schema.org/NutritionInformation), falls vorhanden -
    chefkoch.de liefert dieses Feld nur bei einem Teil der Rezepte mit.
    Die Werte kommen als String samt Einheit ("350 kcal", "12 g") - nur die
    erste Zahl darin wird ausgewertet. Fehlt das Feld komplett oder lässt
    es sich nicht als Zahl lesen, wird 0 zurückgegeben (derselbe Default
    wie beim manuellen Anlegen)."""
    nutrition = recipe_json.get('nutrition')
    if not isinstance(nutrition, dict):
        return 0
    match = re.search(r'[\d.,]+', str(nutrition.get(field_name) or ''))
    if not match:
        return 0
    try:
        return float(match.group().replace(',', '.'))
    except ValueError:
        return 0


def _flatten_instructions(recipe_instructions):
    """Normalisiert recipeInstructions zu einem einzigen, mit Leerzeilen
    getrennten Text für das Anleitung-Textfeld. Das Feld kommt im
    schema.org-Format in mehreren möglichen Formen vor, die hier alle
    unterstützt werden:
    - ein einzelner String (das ganze Rezept als Fließtext)
    - eine Liste von Strings (ein Schritt pro Eintrag)
    - eine Liste von HowToStep-Objekten ({"@type": "HowToStep", "text": ...})
    - eine Liste von HowToSection-Objekten, die ihrerseits eine
      itemListElement-Liste von HowToStep-Objekten enthalten (der bei
      chefkoch.de übliche Fall, siehe Modul-Docstring)
    Jeder gefundene Schritt-Text wird einzeln getrimmt und mit einer
    Leerzeile zum nächsten getrennt, damit die Anleitung im Textfeld
    lesbar in Absätzen erscheint statt als ein einziger langer Block.
    """
    steps = []

    def collect(node):
        if isinstance(node, str):
            text = node.strip()
            if text:
                steps.append(text)
        elif isinstance(node, dict):
            if node.get('@type') == 'HowToSection' and isinstance(node.get('itemListElement'), list):
                for child in node['itemListElement']:
                    collect(child)
            elif 'text' in node:
                text = str(node['text']).strip()
                if text:
                    steps.append(text)
        elif isinstance(node, list):
            for child in node:
                collect(child)

    collect(recipe_instructions)
    return '\n\n'.join(steps)


def _parse_ingredient_line(line):
    """Zerlegt eine einzelne Zutatenzeile (chefkoch.de-typisch z.B.
    "500 g Mehl", "1 Zwiebel(n)", "n. B. Salz und Pfeffer") in
    {name, amount, unit} - dieselbe Form, die das Zutaten-Formular beim
    manuellen Anlegen erwartet (siehe recipe_create.html: ing_name[]/
    ing_amount[]/ing_unit[]).

    Bewusst ein einfacher, nicht perfekter Best-Effort-Parser: findet die
    Zeile keine führende Zahl (z.B. "Salz" oder "n. B. Pfeffer"), wird die
    komplette Zeile unverändert als Name übernommen, amount bleibt 0. Wird
    eine Zahl gefunden, aber das direkt folgende Wort ist keine bekannte
    Einheit (KNOWN_UNITS), bleibt unit leer und das Wort landet als Teil
    des Namens (z.B. "2 große Tortilla-Wraps" -> Name "große
    Tortilla-Wraps") - lieber ein etwas unpräziser Name als eine falsch
    erkannte Einheit. Da der Nutzer die importierten Zeilen vor dem
    Speichern ohnehin im Formular sieht, sind gelegentliche Fehlzuordnungen
    hier bewusst in Kauf genommen statt mit aufwendigerer Heuristik zu
    versuchen, sie ganz zu vermeiden.
    """
    line = line.strip()
    match = re.match(r'^([\d]+(?:[.,][\d]+)?(?:\s*[-–/]\s*[\d]+(?:[.,][\d]+)?)?)\s+(.*)$', line)
    if not match:
        return {'name': line, 'amount': 0, 'unit': ''}

    raw_amount, rest = match.groups()
    amount = _parse_amount_value(raw_amount)

    rest_parts = rest.split(None, 1)
    first_word = rest_parts[0].lower().strip('.') if rest_parts else ''
    if first_word in KNOWN_UNITS:
        unit = rest_parts[0]
        name = rest_parts[1] if len(rest_parts) > 1 else ''
    else:
        unit = ''
        name = rest

    return {'name': name.strip(), 'amount': amount, 'unit': unit}


def _parse_amount_value(raw):
    """Wandelt eine erkannte Mengenangabe in eine Zahl um - unterstützt
    Bruchschreibweise ("1/2" -> 0.5), Bereiche ("1-2" -> Mittelwert 1.5,
    ein einzelner Zahlenwert ist für unser Formularfeld ohnehin nötig) und
    das deutsche Komma als Dezimaltrennzeichen ("1,5" -> 1.5). Nicht
    interpretierbare Eingaben ergeben 0 statt eines Fehlers - der Import
    soll an einer einzelnen unklaren Mengenangabe nicht komplett scheitern."""
    raw = raw.replace(',', '.').strip()
    if '/' in raw:
        num, _, denom = raw.partition('/')
        try:
            return float(num) / float(denom)
        except (ValueError, ZeroDivisionError):
            return 0
    if '-' in raw or '–' in raw:
        numbers = []
        for part in re.split(r'[-–]', raw):
            part = part.strip()
            if part:
                try:
                    numbers.append(float(part))
                except ValueError:
                    pass
        return sum(numbers) / len(numbers) if numbers else 0
    try:
        return float(raw)
    except ValueError:
        return 0
