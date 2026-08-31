"""Tests for services/units.py: unit normalization (mass -> grams,
volume including kitchen measures -> milliliters) and the conversion for display."""
import pytest

from services.units import (
    MASS,
    VOLUME,
    convert_for_display,
    known_unit_keys,
    normalize_amount_unit,
    renormalize_existing_ingredients,
)


# --- normalize_amount_unit: mass ---

@pytest.mark.parametrize("unit", ["g", "G", "gr", "gramm", "Gramm"])
def test_normalize_mass_gram_variants_stay_at_factor_one(unit):
    assert normalize_amount_unit(500, unit) == (500, "g")


@pytest.mark.parametrize("unit", ["kg", "Kg", "kilo", "Kilo", "kilogramm", "Kilogramm"])
def test_normalize_mass_kilogram_variants_multiply_by_1000(unit):
    assert normalize_amount_unit(1, unit) == (1000, "g")


def test_normalize_mass_milligram_divides():
    assert normalize_amount_unit(500, "mg") == (0.5, "g")


@pytest.mark.parametrize("unit", ["dkg", "deka", "dekagramm"])
def test_normalize_mass_deka_austrian_variant(unit):
    # Common in Austria: 1 dkg = 10 g.
    assert normalize_amount_unit(5, unit) == (50, "g")


# --- normalize_amount_unit: volume (including kitchen measures) ---

@pytest.mark.parametrize("unit", ["ml", "milliliter", "Milliliter"])
def test_normalize_volume_milliliter_variants_stay_at_factor_one(unit):
    assert normalize_amount_unit(200, unit) == (200, "ml")


@pytest.mark.parametrize("unit", ["l", "liter", "Liter"])
def test_normalize_volume_liter_variants_multiply_by_1000(unit):
    assert normalize_amount_unit(1.5, unit) == (1500, "ml")


def test_normalize_volume_centiliter():
    assert normalize_amount_unit(3, "cl") == (30, "ml")


@pytest.mark.parametrize("unit", ["TL", "teel", "Teelöffel", "teelöffel"])
def test_normalize_volume_teaspoon_is_5ml(unit):
    assert normalize_amount_unit(2, unit) == (10, "ml")


@pytest.mark.parametrize("unit", ["EL", "essl", "Esslöffel", "esslöffel"])
def test_normalize_volume_tablespoon_is_15ml(unit):
    assert normalize_amount_unit(2, unit) == (30, "ml")


@pytest.mark.parametrize("unit", ["Tasse", "tassen", "cup", "cups", "CUP"])
def test_normalize_volume_cup_is_250ml(unit):
    assert normalize_amount_unit(1, unit) == (250, "ml")


# --- normalize_amount_unit: 1kg == 1000g (core requirement) ---

def test_1kg_equals_1000g_after_normalization():
    assert normalize_amount_unit(1, "kg") == normalize_amount_unit(1000, "g")


def test_2el_equals_30ml_after_normalization():
    assert normalize_amount_unit(2, "EL") == normalize_amount_unit(30, "ml")


# --- normalize_amount_unit: non-convertible/unknown units ---

@pytest.mark.parametrize("unit", ["Stk", "stk", "Prise", "Bund", "Dose", "Zehe"])
def test_normalize_non_convertible_units_pass_through_unchanged(unit):
    assert normalize_amount_unit(3, unit) == (3, unit)


def test_normalize_unknown_unit_passes_through_unchanged():
    assert normalize_amount_unit(2, "Bogen") == (2, "Bogen")


def test_normalize_empty_unit_passes_through_unchanged():
    assert normalize_amount_unit(1, "") == (1, "")


def test_normalize_handles_trailing_dot_and_whitespace():
    assert normalize_amount_unit(1, " kg. ") == (1000, "g")


# --- known_unit_keys ---

def test_known_unit_keys_includes_convertible_and_non_convertible():
    keys = known_unit_keys()
    assert "gramm" in keys
    assert "esslöffel" in keys
    assert "stk" in keys
    assert "prise" in keys


# --- convert_for_display ---

def test_convert_for_display_mass_to_kg():
    assert convert_for_display(1500, "g", {MASS: "kg", VOLUME: "ml"}) == (1.5, "kg")


def test_convert_for_display_mass_stays_grams_when_display_is_g():
    assert convert_for_display(1500, "g", {MASS: "g", VOLUME: "ml"}) == (1500, "g")


def test_convert_for_display_volume_to_liter():
    assert convert_for_display(2500, "ml", {MASS: "g", VOLUME: "l"}) == (2.5, "l")


def test_convert_for_display_volume_stays_ml_when_display_is_ml():
    assert convert_for_display(250, "ml", {MASS: "g", VOLUME: "ml"}) == (250, "ml")


def test_convert_for_display_rounds_to_avoid_float_artifacts():
    amount, unit = convert_for_display(700, "g", {MASS: "kg", VOLUME: "ml"})
    assert unit == "kg"
    assert amount == 0.7


def test_convert_for_display_non_base_unit_passes_through():
    # e.g. "Stk" - not a base unit of any family, stays untouched.
    assert convert_for_display(3, "Stk", {MASS: "kg", VOLUME: "l"}) == (3, "Stk")


def test_convert_for_display_is_reversible_via_normalize():
    # Core requirement: an amount converted for display must, when saved
    # again (normalize_amount_unit), produce exactly the original
    # canonical value once more (see routes/recipes/crud.py: edit_recipe -
    # prefilled, displayed values are sent back unchanged when the user
    # doesn't change anything).
    canonical_amount, canonical_unit = 1500, "g"
    display_amount, display_unit = convert_for_display(canonical_amount, canonical_unit, {MASS: "kg", VOLUME: "ml"})
    assert normalize_amount_unit(display_amount, display_unit) == (canonical_amount, canonical_unit)


# --- renormalize_existing_ingredients: migration of existing data ---

def test_renormalize_existing_ingredients_migrates_legacy_units(app, make_recipe):
    from models import Ingredient, db

    # make_recipe creates Ingredient rows WITHOUT normalization (unlike
    # routes/recipes/crud.py) - this deliberately simulates "legacy data" from
    # before the unit unification.
    recipe_id = make_recipe("Alt", ingredients=[
        {"name": "Mehl", "amount": 1, "unit": "kg"},
        {"name": "Milch", "amount": 2, "unit": "EL"},
        {"name": "Salz", "amount": 1, "unit": "Prise"},
    ])

    with app.app_context():
        renormalize_existing_ingredients()

        by_name = {i.name: (i.amount, i.unit) for i in Ingredient.query.filter_by(recipe_id=recipe_id).all()}
        assert by_name["Mehl"] == (1000, "g")
        assert by_name["Milch"] == (30, "ml")
        # Non-convertible unit stays unchanged.
        assert by_name["Salz"] == (1, "Prise")


def test_renormalize_existing_ingredients_is_idempotent(app, make_recipe):
    from models import Ingredient, db

    recipe_id = make_recipe("Bereits kanonisch", ingredients=[{"name": "Mehl", "amount": 1000, "unit": "g"}])

    with app.app_context():
        renormalize_existing_ingredients()
        renormalize_existing_ingredients()  # second call must no longer change anything

        ing = Ingredient.query.filter_by(recipe_id=recipe_id).first()
        assert (ing.amount, ing.unit) == (1000, "g")
