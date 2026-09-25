"""Recipe import from supported cooking sites.

Reads the page's embedded schema.org/Recipe JSON-LD rather than its HTML,
which survives site redesigns. The result only pre-fills the create form;
nothing is saved here.
"""

import json
import re
from urllib.parse import urlparse

import requests
from flask_babel import lazy_gettext as _l

from services.units import known_unit_keys, normalize_amount_unit

# Allowlist, because the server fetches user-supplied URLs (SSRF). Each site
# was verified to embed Recipe JSON-LD. Not supported: kochbar.de (client-side
# rendered), ichkoche.at (no JSON-LD), springlane.de (typed as "Article").
ALLOWED_HOSTS = {
    'chefkoch.de', 'www.chefkoch.de',
    'lecker.de', 'www.lecker.de',
    'essen-und-trinken.de', 'www.essen-und-trinken.de',
    'eatsmarter.de', 'www.eatsmarter.de',
    'kuechengoetter.de', 'www.kuechengoetter.de',
    'gutekueche.de', 'www.gutekueche.de',
    'gutekueche.at', 'www.gutekueche.at',
    'daskochrezept.de', 'www.daskochrezept.de',
    'brigitte.de', 'www.brigitte.de',
    'emmikochteinfach.de', 'www.emmikochteinfach.de',
}

# Some sites block the python-requests default User-Agent.
REQUEST_HEADERS = {'User-Agent': 'Mozilla/5.0 (compatible; SpeiseplanImport/1.0)'}
REQUEST_TIMEOUT_SECONDS = 10

KNOWN_UNITS = known_unit_keys()


class RecipeImportError(Exception):
    """Carries a user-facing message, returned as-is by the import endpoint."""
    pass


def fetch_recipe_from_url(url):
    """Returns {name, servings, calories, protein, carbs, fat, instructions,
    source_url, ingredients: [{name, amount, unit}]}; raises
    RecipeImportError for every expected failure."""
    parsed_url = urlparse(url)
    if parsed_url.scheme not in ('http', 'https') or parsed_url.hostname not in ALLOWED_HOSTS:
        raise RecipeImportError(
            _l('This site is not supported by the import (see ALLOWED_HOSTS in services/recipe_import.py).')
        )

    try:
        response = requests.get(url, headers=REQUEST_HEADERS, timeout=REQUEST_TIMEOUT_SECONDS)
    except requests.RequestException:
        raise RecipeImportError(_l('The page could not be loaded.'))

    # Re-check after redirects so an allowed host can't bounce us elsewhere.
    if urlparse(response.url).hostname not in ALLOWED_HOSTS:
        raise RecipeImportError(_l('The link does not lead to a supported site.'))
    if not response.ok:
        raise RecipeImportError(_l('The page could not be loaded (status %(status)d).', status=response.status_code))

    # Without a charset in Content-Type, requests assumes ISO-8859-1 and
    # garbles umlauts. Only then guess from the bytes - an explicit charset
    # is more reliable than the guess.
    if 'charset=' not in response.headers.get('Content-Type', '').lower():
        response.encoding = response.apparent_encoding

    recipe_json = _find_recipe_json_ld(response.text)
    if recipe_json is None:
        raise RecipeImportError(_l('No recipe was found on this page.'))

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
    """First "@type": "Recipe" object in any JSON-LD block - top-level, in a
    list, or inside "@graph". None if there is none."""
    for block in re.findall(r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', html, re.S):
        try:
            data = json.loads(block.strip())
        except (json.JSONDecodeError, ValueError):
            continue

        if isinstance(data, dict):
            candidates = data['@graph'] if '@graph' in data else [data]
        elif isinstance(data, list):
            candidates = data
        else:
            candidates = [data]
        for candidate in candidates:
            if isinstance(candidate, dict) and candidate.get('@type') == 'Recipe':
                return candidate
    return None


def _clean_name(raw_name):
    """Strips chefkoch.de's trailing " von <username>"."""
    return re.sub(r'\s+von\s+\S+\s*$', '', raw_name.strip()).strip()


def _parse_servings(recipe_yield):
    """First integer in recipeYield (string, number or list), else 2."""
    if isinstance(recipe_yield, list):
        recipe_yield = recipe_yield[0] if recipe_yield else ''
    match = re.search(r'\d+', str(recipe_yield or ''))
    return int(match.group()) if match else 2


def _parse_nutrition_value(recipe_json, field_name):
    """First number of a nutrition field like "350 kcal", else 0."""
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
    """recipeInstructions (string, list of strings, HowToSteps or
    HowToSections) as one text, steps separated by blank lines."""
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
    """Best-effort split of e.g. "500 g Mehl" into {name, amount, unit}.
    No leading number: the whole line is the name. An unknown word after
    the number stays part of the name rather than guessing a unit - the user
    reviews the result before saving anyway."""
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

    amount, unit = normalize_amount_unit(amount, unit)

    return {'name': name.strip(), 'amount': amount, 'unit': unit}


def _parse_amount_value(raw):
    """Handles "1/2", ranges like "1-2" (average) and decimal commas;
    anything unreadable is 0."""
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
