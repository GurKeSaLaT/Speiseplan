"""Tests für services/ingredient_aliases.py: Zutaten-Gleichsetzung für die
Einkaufsliste (z.B. "Spaghetti"/"Fusilli" -> "Nudeln")."""

from services.ingredient_aliases import (
    delete_alias,
    get_all_aliases,
    list_known_ingredient_names,
    normalize_ingredient_name,
    set_alias,
)


def test_normalize_ingredient_name_without_alias_returns_normalized_self(app):
    with app.app_context():
        assert normalize_ingredient_name("  spaghetti") == "Spaghetti"


def test_set_alias_creates_mapping(app):
    with app.app_context():
        set_alias("Spaghetti", "Nudeln")
        assert normalize_ingredient_name("Spaghetti") == "Nudeln"
        # Andere Schreibweise/Groß-Kleinschreibung muss denselben Alias treffen.
        assert normalize_ingredient_name("  spaghetti ") == "Nudeln"


def test_set_alias_groups_multiple_raw_names(app):
    with app.app_context():
        set_alias("Spaghetti", "Nudeln")
        set_alias("Fusilli", "Nudeln")
        assert normalize_ingredient_name("Spaghetti") == "Nudeln"
        assert normalize_ingredient_name("Fusilli") == "Nudeln"
        # Ein nicht zugeordneter Name bleibt unabhängig davon er selbst.
        assert normalize_ingredient_name("Reis") == "Reis"


def test_set_alias_with_same_name_as_canonical_deletes_existing_alias(app):
    with app.app_context():
        set_alias("Spaghetti", "Nudeln")
        assert normalize_ingredient_name("Spaghetti") == "Nudeln"

        set_alias("Spaghetti", "Spaghetti")
        assert normalize_ingredient_name("Spaghetti") == "Spaghetti"
        assert get_all_aliases() == {}


def test_set_alias_updates_existing_mapping(app):
    with app.app_context():
        set_alias("Spaghetti", "Nudeln")
        set_alias("Spaghetti", "Pasta")
        assert normalize_ingredient_name("Spaghetti") == "Pasta"
        assert len(get_all_aliases()) == 1


def test_delete_alias_reverts_to_self(app):
    with app.app_context():
        set_alias("Spaghetti", "Nudeln")
        delete_alias("Spaghetti")
        assert normalize_ingredient_name("Spaghetti") == "Spaghetti"


def test_delete_alias_without_existing_mapping_is_a_noop(app):
    with app.app_context():
        delete_alias("Nichtvorhanden")  # darf keine Exception werfen


def test_get_all_aliases_returns_dict(app):
    with app.app_context():
        set_alias("Olivenöl", "Öl")
        set_alias("Sonnenblumenöl", "Öl")
        assert get_all_aliases() == {"Olivenöl": "Öl", "Sonnenblumenöl": "Öl"}


def test_list_known_ingredient_names_reflects_recipes(app, make_recipe):
    make_recipe("Suppe", ingredients=[
        {"name": "  spaghetti", "amount": 500, "unit": "g"},
        {"name": "Salz", "amount": 1, "unit": "Prise"},
    ])
    with app.app_context():
        assert list_known_ingredient_names() == ["Salz", "Spaghetti"]


def test_list_known_ingredient_names_deduplicates_across_recipes(app, make_recipe):
    make_recipe("A", ingredients=[{"name": "Mehl", "amount": 500, "unit": "g"}])
    make_recipe("B", ingredients=[{"name": "mehl", "amount": 200, "unit": "g"}])
    with app.app_context():
        assert list_known_ingredient_names() == ["Mehl"]
