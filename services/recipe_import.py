"""Recipe import from external cooking sites - supports a fixed list of
German-language cooking sites (see ALLOWED_HOSTS below).

How it works: fetch_recipe_from_url() loads the page server-side
(requests) and does NOT read the visible HTML, but the embedded
structured data in schema.org/Recipe format (https://schema.org/Recipe),
which chefkoch.de - like most recipe sites - embeds as a
<script type="application/ld+json"> block, which is also why search
engines crawl them with a "serving-size calculator" preview in the
search results. This makes the import robust against layout/design
changes to the site, which would immediately break parsing of the
visible HTML (CSS selectors etc.) - the JSON-LD format practically never
changes, since it is a fixed Google/search-engine standard.

The result is deliberately only a PREVIEW, not a directly saved recipe:
routes/recipes.py: import_recipe_preview() delivers the parsed dict as
JSON to the create page, which uses it to pre-fill the normal form (see
recipe_form.html) - the user sees and edits everything (in particular
the category, which cannot be reliably mapped onto our own categories)
BEFORE anything is saved. No automation in this file writes to the
database itself.
"""

import json
import re
from urllib.parse import urlparse

import requests
from flask_babel import lazy_gettext as _l

from services.units import known_unit_keys, normalize_amount_unit

# Fixed allowlist instead of arbitrary URLs - also for security reasons:
# fetch_recipe_from_url() has the app fetch a user-supplied URL
# server-side (a Server-Side Request Forgery risk if arbitrary URLs were
# allowed, e.g. addresses on the local home network). The domain check
# below, performed BEFORE every request, reliably closes this off - every
# site listed here was manually checked: it embeds a schema.org/Recipe
# JSON-LD object (see module docstring) that the generic, non-site-specific
# parser below can read.
# Deliberately NOT included because no compatible data was found when
# checking: kochbar.de (loads content purely client-side via JavaScript,
# without server-side rendering in the HTML), ichkoche.at (no embedded
# JSON-LD data at all), springlane.de (marks its recipe pages as
# "Article", not "Recipe").
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

# Custom User-Agent instead of the python-requests default, which some
# sites block - a plausible browser-like string is enough for that.
REQUEST_HEADERS = {'User-Agent': 'Mozilla/5.0 (compatible; SpeiseplanImport/1.0)'}
REQUEST_TIMEOUT_SECONDS = 10

# Recognized units of measurement (lowercase, without trailing period,
# against which the first word fragment after the recognized amount is
# compared - see _parse_ingredient_line). Comes from services/units.py so
# that the same list applies here as for the actual conversion
# (normalize_amount_unit(), applied below in _parse_ingredient_line) - an
# unknown word simply ends up as part of the ingredient name instead of
# its own unit, so the import remains usable even then, just with a less
# precise column split.
KNOWN_UNITS = known_unit_keys()


class RecipeImportError(Exception):
    """Raised with an already-translatable, user-facing error message
    (see routes/recipes.py: import_recipe_preview, which returns exactly
    this message 1:1 as a JSON error) - not a technical exception text
    that would need translating."""
    pass


def fetch_recipe_from_url(url):
    """Loads url, looks for a schema.org/Recipe JSON-LD object in it and
    returns a normalized dict:
    {name, servings, calories, protein, carbs, fat, instructions,
     source_url, ingredients: [{name, amount, unit}, ...]}

    Raises RecipeImportError on every expected failure (unsupported
    domain, network error, no recipe found on the page) - the caller
    doesn't need to distinguish between different exception types for
    that.
    """
    parsed_url = urlparse(url)
    if parsed_url.scheme not in ('http', 'https') or parsed_url.hostname not in ALLOWED_HOSTS:
        raise RecipeImportError(
            _l('This site is not supported by the import (see ALLOWED_HOSTS in services/recipe_import.py).')
        )

    try:
        response = requests.get(url, headers=REQUEST_HEADERS, timeout=REQUEST_TIMEOUT_SECONDS)
    except requests.RequestException:
        raise RecipeImportError(_l('The page could not be loaded.'))

    # response.url is the address AFTER any redirects - checked again
    # here so that a link to an allowed domain that (for whatever reason)
    # redirects to a foreign domain doesn't silently end up there (the
    # same SSRF consideration as in the input check above).
    if urlparse(response.url).hostname not in ALLOWED_HOSTS:
        raise RecipeImportError(_l('The link does not lead to a supported site.'))
    if not response.ok:
        raise RecipeImportError(_l('The page could not be loaded (status %(status)d).', status=response.status_code))

    # requests determines response.encoding from the Content-Type header;
    # if that header lacks a charset parameter (e.g. just "text/html"
    # without ";charset=..."), requests falls back to ISO-8859-1 per the
    # HTTP spec - which is wrong for most of today's (UTF-8) sites and
    # leads to incorrectly decoded umlauts ("Ã¶" instead of "ö"). Only in
    # that case do we fall back to the encoding guessed from the raw
    # bytes (apparent_encoding): if the header explicitly states a
    # charset, it is trusted, even if apparent_encoding guesses something
    # else (which can itself be wrong for short/ambiguous pages, see
    # chefkoch.de, which correctly declares "utf-8" but is incorrectly
    # guessed by apparent_encoding as "windows-1250").
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
    """Searches all <script type="application/ld+json"> blocks on the page
    for an object with "@type": "Recipe" - either directly as a top-level
    object/list, or (the usual case on chefkoch.de) nested under an
    "@graph" key that bundles several related objects (Recipe, WebPage,
    Organization, ...) belonging to one page. Returns None if no such
    object is found (e.g. because the URL isn't a recipe page at all)
    instead of raising an exception - the caller turns this into a
    uniform RecipeImportError.
    """
    for block in re.findall(r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', html, re.S):
        try:
            data = json.loads(block.strip())
        except (json.JSONDecodeError, ValueError):
            continue

        # A dict WITHOUT an "@graph" key is itself the only candidate
        # (e.g. a page that embeds its Recipe object directly as
        # top-level JSON-LD instead of bundling it in @graph) -
        # data.get('@graph', []) would incorrectly map this case to an
        # empty candidate list, since [] is the default only for
        # "@graph is missing", not "no candidate present".
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
    """chefkoch.de consistently appends " von <username>" to the recipe
    name in the JSON-LD (e.g. "Ligurische Nudeln von laufmasche") - this
    is stripped off here, since the author's name is irrelevant for our
    recipe database. If the name happens to come without this suffix (or
    in a different format), it is left unchanged."""
    return re.sub(r'\s+von\s+\S+\s*$', '', raw_name.strip()).strip()


def _parse_servings(recipe_yield):
    """In the Recipe schema, recipeYield is either a single string
    ("4 Portionen"), a number, or (on chefkoch.de) a list whose first
    entry is the plain number as a string (e.g. ["4", "4 Portionen"]).
    Extracts the first integer found in it; if there is no match at all,
    2 is used as the default value (the same default as when manually
    creating a recipe, see recipe_form.html)."""
    if isinstance(recipe_yield, list):
        recipe_yield = recipe_yield[0] if recipe_yield else ''
    match = re.search(r'\d+', str(recipe_yield or ''))
    return int(match.group()) if match else 2


def _parse_nutrition_value(recipe_json, field_name):
    """Reads a single nutrition field from the nested "nutrition" object
    (schema.org/NutritionInformation), if present - chefkoch.de only
    supplies this field for some recipes. The values come as a string
    including the unit ("350 kcal", "12 g") - only the first number in it
    is evaluated. If the field is missing entirely or can't be read as a
    number, 0 is returned (the same default as when manually creating a
    recipe)."""
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
    """Normalizes recipeInstructions into a single text, separated by
    blank lines, for the instructions text field. In the schema.org
    format, the field comes in several possible shapes, all of which are
    supported here:
    - a single string (the whole recipe as continuous text)
    - a list of strings (one step per entry)
    - a list of HowToStep objects ({"@type": "HowToStep", "text": ...})
    - a list of HowToSection objects, which in turn contain an
      itemListElement list of HowToStep objects (the usual case on
      chefkoch.de, see module docstring)
    Each step text found is individually trimmed and separated from the
    next by a blank line, so that the instructions appear readable in
    paragraphs in the text field instead of as one long block.
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
    """Splits a single ingredient line (typically on chefkoch.de e.g.
    "500 g Mehl", "1 Zwiebel(n)", "n. B. Salz und Pfeffer") into
    {name, amount, unit} - the same shape the ingredient form expects
    when manually creating a recipe (see recipe_form.html: ing_name[]/
    ing_amount[]/ing_unit[]).

    Deliberately a simple, imperfect best-effort parser: if the line has
    no leading number (e.g. "Salz" or "n. B. Pfeffer"), the whole line is
    taken unchanged as the name, amount stays 0. If a number is found but
    the word directly following it is not a known unit (KNOWN_UNITS),
    unit stays empty and the word ends up as part of the name (e.g.
    "2 große Tortilla-Wraps" -> name "große Tortilla-Wraps") - a slightly
    imprecise name is preferred over a wrongly recognized unit. Since the
    user sees the imported lines in the form before saving anyway,
    occasional misassignments here are deliberately accepted rather than
    trying to avoid them entirely with a more elaborate heuristic.
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

    # Immediately bring a recognized unit (mass/volume) into its
    # canonical form ("1 kg" -> amount=1000, unit="g") - see
    # services/units.py. Non-convertible/unknown units (Stk, Prise,
    # "Zwiebel(n)" without any unit, ...) come back unchanged.
    amount, unit = normalize_amount_unit(amount, unit)

    return {'name': name.strip(), 'amount': amount, 'unit': unit}


def _parse_amount_value(raw):
    """Converts a recognized amount into a number - supports fraction
    notation ("1/2" -> 0.5), ranges ("1-2" -> average 1.5, since a single
    numeric value is needed for our form field anyway), and the German
    comma as a decimal separator ("1,5" -> 1.5). Inputs that can't be
    interpreted yield 0 instead of an error - the import shouldn't fail
    completely over a single unclear amount."""
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
