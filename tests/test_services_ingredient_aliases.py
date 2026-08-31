"""Tests for services/ingredient_aliases.py: ingredient aliasing for the
shopping list (e.g. "Spaghetti"/"Fusilli" -> "Nudeln") - maintained
separately per plan."""

from services.ingredient_aliases import (
    delete_alias,
    get_all_aliases,
    list_known_ingredient_names,
    normalize_ingredient_name,
    normalize_name,
    set_alias,
)


def test_normalize_name_strips_and_title_cases():
    assert normalize_name("  spaghetti ") == "Spaghetti"
    assert normalize_name("") == ""
    assert normalize_name(None) == ""


def test_normalize_ingredient_name_without_alias_returns_normalized_self(app, test_plan_id):
    with app.app_context():
        assert normalize_ingredient_name(test_plan_id, "  spaghetti") == "Spaghetti"


def test_set_alias_creates_mapping(app, test_plan_id):
    with app.app_context():
        set_alias(test_plan_id, "Spaghetti", "Nudeln")
        assert normalize_ingredient_name(test_plan_id, "Spaghetti") == "Nudeln"
        # A different spelling/case must hit the same alias.
        assert normalize_ingredient_name(test_plan_id, "  spaghetti ") == "Nudeln"


def test_set_alias_groups_multiple_raw_names(app, test_plan_id):
    with app.app_context():
        set_alias(test_plan_id, "Spaghetti", "Nudeln")
        set_alias(test_plan_id, "Fusilli", "Nudeln")
        assert normalize_ingredient_name(test_plan_id, "Spaghetti") == "Nudeln"
        assert normalize_ingredient_name(test_plan_id, "Fusilli") == "Nudeln"
        # An unmapped name remains itself regardless.
        assert normalize_ingredient_name(test_plan_id, "Reis") == "Reis"


def test_set_alias_with_same_name_as_canonical_deletes_existing_alias(app, test_plan_id):
    with app.app_context():
        set_alias(test_plan_id, "Spaghetti", "Nudeln")
        assert normalize_ingredient_name(test_plan_id, "Spaghetti") == "Nudeln"

        set_alias(test_plan_id, "Spaghetti", "Spaghetti")
        assert normalize_ingredient_name(test_plan_id, "Spaghetti") == "Spaghetti"
        assert get_all_aliases(test_plan_id) == {}


def test_set_alias_updates_existing_mapping(app, test_plan_id):
    with app.app_context():
        set_alias(test_plan_id, "Spaghetti", "Nudeln")
        set_alias(test_plan_id, "Spaghetti", "Pasta")
        assert normalize_ingredient_name(test_plan_id, "Spaghetti") == "Pasta"
        assert len(get_all_aliases(test_plan_id)) == 1


def test_delete_alias_reverts_to_self(app, test_plan_id):
    with app.app_context():
        set_alias(test_plan_id, "Spaghetti", "Nudeln")
        delete_alias(test_plan_id, "Spaghetti")
        assert normalize_ingredient_name(test_plan_id, "Spaghetti") == "Spaghetti"


def test_delete_alias_without_existing_mapping_is_a_noop(app, test_plan_id):
    with app.app_context():
        delete_alias(test_plan_id, "Nichtvorhanden")  # must not raise an exception


def test_get_all_aliases_returns_dict(app, test_plan_id):
    with app.app_context():
        set_alias(test_plan_id, "Olivenöl", "Öl")
        set_alias(test_plan_id, "Sonnenblumenöl", "Öl")
        assert get_all_aliases(test_plan_id) == {"Olivenöl": "Öl", "Sonnenblumenöl": "Öl"}


def test_aliases_are_isolated_per_plan(app, test_plan_id, make_user):
    with app.app_context():
        set_alias(test_plan_id, "Spaghetti", "Nudeln")

    _, other_plan_id = make_user("Andere")
    with app.app_context():
        assert normalize_ingredient_name(other_plan_id, "Spaghetti") == "Spaghetti"
        assert get_all_aliases(other_plan_id) == {}


def test_list_known_ingredient_names_reflects_recipes(app, test_plan_id, make_recipe):
    make_recipe("Suppe", ingredients=[
        {"name": "  spaghetti", "amount": 500, "unit": "g"},
        {"name": "Salz", "amount": 1, "unit": "Prise"},
    ])
    with app.app_context():
        assert list_known_ingredient_names(test_plan_id) == ["Salz", "Spaghetti"]


def test_list_known_ingredient_names_deduplicates_across_recipes(app, test_plan_id, make_recipe):
    make_recipe("A", ingredients=[{"name": "Mehl", "amount": 500, "unit": "g"}])
    make_recipe("B", ingredients=[{"name": "mehl", "amount": 200, "unit": "g"}])
    with app.app_context():
        assert list_known_ingredient_names(test_plan_id) == ["Mehl"]


def test_list_known_ingredient_names_ignores_other_plans_recipes(app, test_plan_id, make_recipe, make_user):
    _, other_plan_id = make_user("Andere")
    make_recipe("Fremdes Gericht", plan_id=other_plan_id, ingredients=[{"name": "Reis", "amount": 200, "unit": "g"}])
    with app.app_context():
        assert list_known_ingredient_names(test_plan_id) == []
