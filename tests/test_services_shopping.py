"""Tests für services/shopping.py: die feste Einkaufslisten-Kategorie-Liste."""
from services.shopping import PANTRY_CATEGORIES, SHOPPING_CATEGORIES, UNCATEGORIZED, infer_category


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


def test_infer_category_returns_none_without_existing_rows(app):
    with app.app_context():
        assert infer_category("Nudeln") is None


def test_infer_category_returns_existing_category(app, make_recipe):
    make_recipe("Nudelgericht", ingredients=[
        {"name": "Spaghetti", "amount": 500, "unit": "g", "category": "Teigwaren"},
    ])
    with app.app_context():
        assert infer_category("Spaghetti") == "Teigwaren"


def test_infer_category_resolves_via_alias(app, make_recipe):
    """Eine Zutat-Zeile bleibt in der DB unter ihrem ursprünglichen Namen
    ("Spaghetti") gespeichert - infer_category muss sie trotzdem finden,
    wenn nach der ALIAS-ZIEL-Kategorie ("Nudeln") gefragt wird, da es
    intern jede Zeile über normalize_ingredient_name() auflöst."""
    from services.ingredient_aliases import set_alias

    make_recipe("Nudelgericht", ingredients=[
        {"name": "Spaghetti", "amount": 500, "unit": "g", "category": "Teigwaren"},
    ])
    with app.app_context():
        set_alias("Spaghetti", "Nudeln")
        assert infer_category("Nudeln") == "Teigwaren"


def test_infer_category_ignores_uncategorized_rows(app, make_recipe):
    make_recipe("Nudelgericht", ingredients=[
        {"name": "Fusilli", "amount": 300, "unit": "g", "category": None},
    ])
    with app.app_context():
        assert infer_category("Fusilli") is None


def test_infer_category_majority_wins(app, make_recipe):
    make_recipe("Erstes Gericht", ingredients=[
        {"name": "Nudeln", "amount": 200, "unit": "g", "category": "Teigwaren"},
    ])
    make_recipe("Zweites Gericht", ingredients=[
        {"name": "Nudeln", "amount": 300, "unit": "g", "category": "Teigwaren"},
    ])
    make_recipe("Drittes Gericht", ingredients=[
        {"name": "Nudeln", "amount": 100, "unit": "g", "category": "Konserven"},
    ])
    with app.app_context():
        assert infer_category("Nudeln") == "Teigwaren"
