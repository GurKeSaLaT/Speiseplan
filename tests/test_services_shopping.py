"""Tests für services/shopping.py: die feste Einkaufslisten-Kategorie-Liste."""
from services.shopping import PANTRY_CATEGORIES, SHOPPING_CATEGORIES, UNCATEGORIZED


def test_shopping_categories_order():
    assert SHOPPING_CATEGORIES == [
        "Obst/Gemüse",
        "Backwaren",
        "Milchprodukte",
        "Gewürze",
        "Vorratsschrank",
        "Hygieneartikel",
        "Verbrauchsartikel",
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


def test_pantry_categories_are_valid_shopping_categories():
    # Jede Vorrats-Kategorie muss auch eine echte Einkaufslisten-Kategorie
    # sein (sonst würde sie z.B. nicht im Kategorie-Dropdown auftauchen).
    assert PANTRY_CATEGORIES == {"Gewürze", "Vorratsschrank", "Verbrauchsartikel"}
    assert PANTRY_CATEGORIES.issubset(set(SHOPPING_CATEGORIES))
    # Backwaren ist bewusst NICHT Teil der Vorrats-Kategorien - Brot ist
    # typischerweise ein frischer wöchentlicher Einkauf.
    assert "Backwaren" not in PANTRY_CATEGORIES


def test_shopping_categories_injected_into_templates(client):
    resp = client.get("/manage")
    assert resp.status_code == 200
    # tojson escaped Umlaute als \uXXXX statt roher UTF-8-Bytes, siehe
    # templates/base.html: window.SHOPPING_CATEGORIES.
    assert b"Gew\\u00fcrze" in resp.data
    assert b"Verbrauchsartikel" in resp.data


def test_pantry_categories_injected_into_templates(client):
    resp = client.get("/manage")
    assert resp.status_code == 200
    assert b"window.PANTRY_CATEGORIES" in resp.data
    assert b"Gew\\u00fcrze" in resp.data
    assert b"Verbrauchsartikel" in resp.data
