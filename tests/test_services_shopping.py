"""Tests für services/shopping.py: die feste Einkaufslisten-Kategorie-Liste."""
from services.shopping import SHOPPING_CATEGORIES, UNCATEGORIZED


def test_shopping_categories_order():
    assert SHOPPING_CATEGORIES == [
        "Obst/Gemüse",
        "Milchprodukte",
        "Gewürze",
        "Hygieneartikel",
        "Getränke",
        "Teigwaren",
        "Konserven",
        "Tiefkühlware",
    ]


def test_uncategorized_not_part_of_fixed_list():
    # Sonstiges ist die Auffangkategorie, sortiert separat ans Ende
    # (siehe categorySortIndex() in static/plan-shopping.js) - kein
    # eigener Eintrag in SHOPPING_CATEGORIES.
    assert UNCATEGORIZED not in SHOPPING_CATEGORIES


def test_shopping_categories_injected_into_templates(client):
    resp = client.get("/manage")
    assert resp.status_code == 200
    # tojson escaped Umlaute als \uXXXX statt roher UTF-8-Bytes, siehe
    # templates/base.html: window.SHOPPING_CATEGORIES.
    assert b"Gew\\u00fcrze" in resp.data
