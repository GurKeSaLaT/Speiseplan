"""Tests for services/recipe_import.py: recipe import from several
German-language cooking sites (reading schema.org/Recipe JSON-LD and
converting it into form-usable values)."""
import json
from unittest.mock import Mock, patch

import pytest

from services.recipe_import import (
    ALLOWED_HOSTS,
    KNOWN_UNITS,
    RecipeImportError,
    _clean_name,
    _find_recipe_json_ld,
    _flatten_instructions,
    _parse_amount_value,
    _parse_ingredient_line,
    _parse_nutrition_value,
    _parse_servings,
    fetch_recipe_from_url,
)


# --- ALLOWED_HOSTS ---

@pytest.mark.parametrize("host", [
    "chefkoch.de", "lecker.de", "essen-und-trinken.de", "eatsmarter.de",
    "kuechengoetter.de", "gutekueche.de", "gutekueche.at", "daskochrezept.de",
    "brigitte.de", "emmikochteinfach.de",
])
def test_allowed_hosts_covers_bare_and_www_variant(host):
    assert host in ALLOWED_HOSTS
    assert f"www.{host}" in ALLOWED_HOSTS


def test_allowed_hosts_excludes_sites_without_compatible_json_ld():
    # Manually checked and deliberately NOT supported (see the
    # ALLOWED_HOSTS comment in services/recipe_import.py for the reason per site).
    for host in ("kochbar.de", "ichkoche.at", "springlane.de"):
        assert host not in ALLOWED_HOSTS


# --- KNOWN_UNITS ---

@pytest.mark.parametrize("unit", ["gramm", "kilogramm", "milliliter", "liter", "esslöffel", "teelöffel"])
def test_known_units_includes_spelled_out_variants(unit):
    assert unit in KNOWN_UNITS


# --- _clean_name ---

def test_clean_name_strips_chefkoch_author_suffix():
    assert _clean_name("Ligurische Nudeln von laufmasche") == "Ligurische Nudeln"


def test_clean_name_leaves_name_without_suffix_unchanged():
    assert _clean_name("Einfache Suppe") == "Einfache Suppe"


def test_clean_name_strips_surrounding_whitespace():
    assert _clean_name("  Suppe  ") == "Suppe"


# --- _parse_servings ---

@pytest.mark.parametrize("raw,expected", [
    ("4 Portionen", 4),
    (4, 4),
    (["4", "4 Portionen"], 4),
    ("keine Zahl enthalten", 2),
    (None, 2),
    ([], 2),
])
def test_parse_servings(raw, expected):
    assert _parse_servings(raw) == expected


# --- _parse_nutrition_value ---

def test_parse_nutrition_value_extracts_number_with_unit():
    recipe_json = {"nutrition": {"calories": "350 kcal"}}
    assert _parse_nutrition_value(recipe_json, "calories") == 350


def test_parse_nutrition_value_german_decimal_comma():
    recipe_json = {"nutrition": {"proteinContent": "12,5 g"}}
    assert _parse_nutrition_value(recipe_json, "proteinContent") == 12.5


def test_parse_nutrition_value_missing_nutrition_returns_zero():
    assert _parse_nutrition_value({}, "calories") == 0


def test_parse_nutrition_value_missing_field_returns_zero():
    assert _parse_nutrition_value({"nutrition": {}}, "calories") == 0


# --- _flatten_instructions ---

def test_flatten_instructions_single_string():
    assert _flatten_instructions("Alles vermischen.") == "Alles vermischen."


def test_flatten_instructions_list_of_strings():
    result = _flatten_instructions(["Erst dies.", "Dann das."])
    assert result == "Erst dies.\n\nDann das."


def test_flatten_instructions_howto_steps():
    steps = [
        {"@type": "HowToStep", "text": "Schritt eins"},
        {"@type": "HowToStep", "text": "Schritt zwei"},
    ]
    assert _flatten_instructions(steps) == "Schritt eins\n\nSchritt zwei"


def test_flatten_instructions_nested_howto_sections():
    sections = [
        {
            "@type": "HowToSection",
            "itemListElement": [
                {"@type": "HowToStep", "text": "Vorbereitung"},
                {"@type": "HowToStep", "text": "Kochen"},
            ],
        }
    ]
    assert _flatten_instructions(sections) == "Vorbereitung\n\nKochen"


def test_flatten_instructions_empty_or_none():
    assert _flatten_instructions(None) == ""
    assert _flatten_instructions([]) == ""


# --- _parse_amount_value ---

@pytest.mark.parametrize("raw,expected", [
    ("1/2", 0.5),
    ("1,5", 1.5),
    ("1-2", 1.5),
    ("1–2", 1.5),
    ("500", 500),
    ("garbage", 0),
    ("1/0", 0),
])
def test_parse_amount_value(raw, expected):
    assert _parse_amount_value(raw) == expected


# --- _parse_ingredient_line ---

def test_parse_ingredient_line_known_unit():
    result = _parse_ingredient_line("500 g Mehl")
    assert result == {"name": "Mehl", "amount": 500, "unit": "g"}


def test_parse_ingredient_line_spelled_out_unit_gets_normalized():
    # brigitte.de/gutekueche.de spell out units instead of abbreviating
    # them (unlike chefkoch.de) - still gets normalized to the
    # canonical form "g" (see services/units.py).
    result = _parse_ingredient_line("250 Gramm Mehl")
    assert result == {"name": "Mehl", "amount": 250, "unit": "g"}


def test_parse_ingredient_line_unknown_unit_becomes_part_of_name():
    result = _parse_ingredient_line("2 große Tortilla-Wraps")
    assert result == {"name": "große Tortilla-Wraps", "amount": 2, "unit": ""}


def test_parse_ingredient_line_no_leading_number():
    result = _parse_ingredient_line("Salz und Pfeffer")
    assert result == {"name": "Salz und Pfeffer", "amount": 0, "unit": ""}


def test_parse_ingredient_line_single_item_no_unit_word():
    result = _parse_ingredient_line("1 Zwiebel(n)")
    assert result == {"name": "Zwiebel(n)", "amount": 1, "unit": ""}


# --- _find_recipe_json_ld ---

def test_find_recipe_json_ld_direct_object():
    html = '<script type="application/ld+json">{"@type": "Recipe", "name": "Test"}</script>'
    result = _find_recipe_json_ld(html)
    assert result == {"@type": "Recipe", "name": "Test"}


def test_find_recipe_json_ld_graph_structure():
    payload = {"@graph": [{"@type": "WebPage"}, {"@type": "Recipe", "name": "Aus Graph"}]}
    html = f'<script type="application/ld+json">{json.dumps(payload)}</script>'
    result = _find_recipe_json_ld(html)
    assert result["name"] == "Aus Graph"


def test_find_recipe_json_ld_returns_none_when_absent():
    html = '<script type="application/ld+json">{"@type": "WebPage"}</script>'
    assert _find_recipe_json_ld(html) is None


def test_find_recipe_json_ld_skips_invalid_json_blocks():
    html = (
        '<script type="application/ld+json">not valid json</script>'
        '<script type="application/ld+json">{"@type": "Recipe", "name": "Gültig"}</script>'
    )
    result = _find_recipe_json_ld(html)
    assert result["name"] == "Gültig"


# --- fetch_recipe_from_url: SSRF protection + end-to-end with mocked requests ---

def test_fetch_recipe_from_url_rejects_disallowed_host():
    with pytest.raises(RecipeImportError):
        fetch_recipe_from_url("https://example.com/recipe")


def test_fetch_recipe_from_url_rejects_non_http_scheme():
    with pytest.raises(RecipeImportError):
        fetch_recipe_from_url("ftp://chefkoch.de/recipe")


@patch("services.recipe_import.requests.get")
def test_fetch_recipe_from_url_rejects_redirect_to_disallowed_host(mock_get):
    mock_response = Mock(ok=True, url="https://evil.example.com/", text="")
    mock_get.return_value = mock_response
    with pytest.raises(RecipeImportError):
        fetch_recipe_from_url("https://chefkoch.de/recipe")


@patch("services.recipe_import.requests.get")
def test_fetch_recipe_from_url_network_error(mock_get):
    import requests
    mock_get.side_effect = requests.RequestException("boom")
    with pytest.raises(RecipeImportError):
        fetch_recipe_from_url("https://chefkoch.de/recipe")


@patch("services.recipe_import.requests.get")
def test_fetch_recipe_from_url_non_ok_status(mock_get):
    mock_get.return_value = Mock(ok=False, status_code=404, url="https://chefkoch.de/recipe", text="")
    with pytest.raises(RecipeImportError):
        fetch_recipe_from_url("https://chefkoch.de/recipe")


@patch("services.recipe_import.requests.get")
def test_fetch_recipe_from_url_no_recipe_found(mock_get):
    mock_get.return_value = Mock(
        ok=True, url="https://chefkoch.de/recipe", text="<html></html>",
        headers={"Content-Type": "text/html; charset=utf-8"},
    )
    with pytest.raises(RecipeImportError):
        fetch_recipe_from_url("https://chefkoch.de/recipe")


@patch("services.recipe_import.requests.get")
def test_fetch_recipe_from_url_full_success(mock_get):
    recipe_json = {
        "@type": "Recipe",
        "name": "Ligurische Nudeln von laufmasche",
        "recipeYield": ["4", "4 Portionen"],
        "nutrition": {"calories": "350 kcal", "proteinContent": "12 g",
                      "carbohydrateContent": "40 g", "fatContent": "10 g"},
        "recipeInstructions": ["Wasser kochen.", "Nudeln kochen."],
        "recipeIngredient": ["500 g Nudeln", "1 Zwiebel(n)"],
    }
    html = f'<script type="application/ld+json">{json.dumps(recipe_json)}</script>'
    mock_get.return_value = Mock(
        ok=True, url="https://www.chefkoch.de/recipe", text=html,
        headers={"Content-Type": "text/html; charset=utf-8"},
    )

    result = fetch_recipe_from_url("https://chefkoch.de/recipe")

    assert result["name"] == "Ligurische Nudeln"
    assert result["servings"] == 4
    assert result["calories"] == 350
    assert result["protein"] == 12
    assert result["instructions"] == "Wasser kochen.\n\nNudeln kochen."
    assert result["source_url"] == "https://www.chefkoch.de/recipe"
    assert result["ingredients"] == [
        {"name": "Nudeln", "amount": 500, "unit": "g"},
        {"name": "Zwiebel(n)", "amount": 1, "unit": ""},
    ]


@patch("services.recipe_import.requests.get")
def test_fetch_recipe_from_url_fixes_missing_charset_declaration(mock_get):
    """Some sites (e.g. emmikochteinfach.de) declare no charset in the
    Content-Type header even though the page is actually UTF-8 - requests
    would otherwise fall back to ISO-8859-1 and decode umlauts
    incorrectly ("Ã¶" instead of "ö", see the comment in
    fetch_recipe_from_url). Simulates this via real UTF-8 bytes that
    requests, WITHOUT the fix, would read as ISO-8859-1."""
    recipe_json = {
        "@type": "Recipe", "name": "Bolognese-Rezept – das Original",
        "recipeIngredient": ["500 g Hackfleisch"],
    }
    html_bytes = f'<script type="application/ld+json">{json.dumps(recipe_json)}</script>'.encode("utf-8")

    mock_response = Mock(ok=True, url="https://emmikochteinfach.de/recipe", headers={"Content-Type": "text/html"})
    mock_response.apparent_encoding = "utf-8"
    # As with a real requests.Response: .text decodes content based on
    # the current .encoding value - encoding is set as a normal attribute
    # (no PropertyMock needed), .text is simulated as a property.
    mock_response.encoding = "ISO-8859-1"
    type(mock_response).text = property(lambda self: html_bytes.decode(self.encoding))
    mock_get.return_value = mock_response

    result = fetch_recipe_from_url("https://emmikochteinfach.de/recipe")
    assert result["name"] == "Bolognese-Rezept – das Original"


@patch("services.recipe_import.requests.get")
def test_fetch_recipe_from_url_trusts_declared_charset_even_if_apparent_disagrees(mock_get):
    """Reverse case: if the header explicitly states a charset, it's
    trusted even when apparent_encoding (the encoding guessed from the
    bytes) suggests something different - exactly the case observed with
    chefkoch.de (correctly declares utf-8, apparent_encoding incorrectly
    guesses windows-1250, see the comment in fetch_recipe_from_url)."""
    recipe_json = {"@type": "Recipe", "name": "Käsekuchen", "recipeIngredient": []}
    html = f'<script type="application/ld+json">{json.dumps(recipe_json)}</script>'

    mock_response = Mock(
        ok=True, url="https://chefkoch.de/recipe", text=html,
        headers={"Content-Type": "text/html; charset=utf-8"},
    )
    mock_response.apparent_encoding = "windows-1250"  # deliberately "wrong", must not be used
    mock_get.return_value = mock_response

    result = fetch_recipe_from_url("https://chefkoch.de/recipe")
    assert result["name"] == "Käsekuchen"


@patch("services.recipe_import.requests.get")
def test_fetch_recipe_from_url_works_for_non_chefkoch_host(mock_get):
    """The parser is deliberately NOT chefkoch-specific (see the module
    docstring) - this test demonstrates that with a second, independent
    domain from ALLOWED_HOSTS using a spelled-out instead of abbreviated
    unit."""
    recipe_json = {
        "@type": "Recipe",
        "name": "Käsekuchen",
        "recipeYield": "12 Stück",
        "recipeInstructions": [{"@type": "HowToStep", "text": "Teig kneten."}],
        "recipeIngredient": ["250 Gramm Mehl"],
    }
    html = f'<script type="application/ld+json">{json.dumps(recipe_json)}</script>'
    mock_get.return_value = Mock(
        ok=True, url="https://www.brigitte.de/recipe", text=html,
        headers={"Content-Type": "text/html; charset=utf-8"},
    )

    result = fetch_recipe_from_url("https://brigitte.de/recipe")

    assert result["name"] == "Käsekuchen"
    assert result["servings"] == 12
    assert result["ingredients"] == [{"name": "Mehl", "amount": 250, "unit": "g"}]
