"""Tests für services/recipe_import.py: Rezept-Import von mehreren
deutschsprachigen Kochseiten (schema.org/Recipe-JSON-LD auslesen und in
Formular-taugliche Werte umwandeln)."""
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
    # Manuell geprüft und bewusst NICHT unterstützt (siehe ALLOWED_HOSTS-
    # Kommentar in services/recipe_import.py für den Grund je Seite).
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
    # brigitte.de/gutekueche.de schreiben Einheiten aus statt sie
    # abzukürzen (anders als chefkoch.de) - wird trotzdem auf die
    # kanonische Form "g" gebracht (siehe services/units.py).
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


# --- fetch_recipe_from_url: SSRF-Schutz + End-to-End mit gemocktem requests ---

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
    mock_get.return_value = Mock(ok=True, url="https://chefkoch.de/recipe", text="<html></html>")
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
    mock_get.return_value = Mock(ok=True, url="https://www.chefkoch.de/recipe", text=html)

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
def test_fetch_recipe_from_url_works_for_non_chefkoch_host(mock_get):
    """Der Parser ist bewusst NICHT chefkoch-spezifisch (siehe Moduldocstring) -
    dieser Test belegt das anhand einer zweiten, unabhängigen Domain aus
    ALLOWED_HOSTS mit ausgeschriebener statt abgekürzter Mengeneinheit."""
    recipe_json = {
        "@type": "Recipe",
        "name": "Käsekuchen",
        "recipeYield": "12 Stück",
        "recipeInstructions": [{"@type": "HowToStep", "text": "Teig kneten."}],
        "recipeIngredient": ["250 Gramm Mehl"],
    }
    html = f'<script type="application/ld+json">{json.dumps(recipe_json)}</script>'
    mock_get.return_value = Mock(ok=True, url="https://www.brigitte.de/recipe", text=html)

    result = fetch_recipe_from_url("https://brigitte.de/recipe")

    assert result["name"] == "Käsekuchen"
    assert result["servings"] == 12
    assert result["ingredients"] == [{"name": "Mehl", "amount": 250, "unit": "g"}]
