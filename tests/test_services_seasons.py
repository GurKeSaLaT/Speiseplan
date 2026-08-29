"""Tests für services/seasons.py: Verfügbarkeitszeiträume von Rezepten."""
from datetime import date
from unittest.mock import patch

from services.seasons import (
    SEASON_PRESETS,
    date_in_range,
    describe_recipe_seasons,
    format_recipe_seasons,
    parse_recipe_seasons,
    recipe_available_now,
    save_recipe_seasons,
)


class FakeForm:
    """Minimales Stand-in für ein Werkzeug ImmutableMultiDict-Formular,
    genug für parse_recipe_seasons() (nutzt nur .getlist() und .get())."""

    def __init__(self, data):
        self._data = data

    def getlist(self, key):
        value = self._data.get(key, [])
        return value if isinstance(value, list) else [value]

    def get(self, key):
        value = self._data.get(key)
        return value[0] if isinstance(value, list) else value


# --- date_in_range ---

def test_date_in_range_normal_range():
    assert date_in_range(7, 15, 6, 1, 8, 31) is True
    assert date_in_range(9, 1, 6, 1, 8, 31) is False


def test_date_in_range_boundaries_inclusive():
    assert date_in_range(6, 1, 6, 1, 8, 31) is True
    assert date_in_range(8, 31, 6, 1, 8, 31) is True


def test_date_in_range_year_wraparound_winter():
    # Winter: 1.12. - 28.2.
    assert date_in_range(1, 15, 12, 1, 2, 28) is True
    assert date_in_range(12, 15, 12, 1, 2, 28) is True
    assert date_in_range(6, 1, 12, 1, 2, 28) is False


# --- recipe_available_now ---

class FakeRecipe:
    def __init__(self, seasons):
        self.seasons = seasons


class FakeSeason:
    def __init__(self, start_month, start_day, end_month, end_day):
        self.start_month = start_month
        self.start_day = start_day
        self.end_month = end_month
        self.end_day = end_day


def test_recipe_available_now_no_seasons_means_always():
    recipe = FakeRecipe(seasons=[])
    assert recipe_available_now(recipe) is True


@patch("services.seasons.date")
def test_recipe_available_now_matches_one_of_several_seasons(mock_date):
    mock_date.today.return_value = date(2026, 7, 1)  # Sommer
    recipe = FakeRecipe(seasons=[
        FakeSeason(*SEASON_PRESETS["Winter"]),
        FakeSeason(*SEASON_PRESETS["Sommer"]),
    ])
    assert recipe_available_now(recipe) is True


@patch("services.seasons.date")
def test_recipe_available_now_false_when_outside_all_seasons(mock_date):
    mock_date.today.return_value = date(2026, 7, 1)  # Sommer
    recipe = FakeRecipe(seasons=[FakeSeason(*SEASON_PRESETS["Winter"])])
    assert recipe_available_now(recipe) is False


# --- parse_recipe_seasons ---

def test_parse_recipe_seasons_preset_only():
    form = FakeForm({"seasons": ["Sommer", "Herbst"]})
    ranges = parse_recipe_seasons(form)
    assert SEASON_PRESETS["Sommer"] in ranges
    assert SEASON_PRESETS["Herbst"] in ranges
    assert len(ranges) == 2


def test_parse_recipe_seasons_ignores_unknown_preset_name():
    form = FakeForm({"seasons": ["Nichtexistent"]})
    assert parse_recipe_seasons(form) == []


def test_parse_recipe_seasons_custom_range_ignores_year():
    form = FakeForm({"season_custom_start": "2000-05-15", "season_custom_end": "2001-06-20"})
    assert parse_recipe_seasons(form) == [(5, 15, 6, 20)]


def test_parse_recipe_seasons_custom_range_requires_both_fields():
    form = FakeForm({"season_custom_start": "2000-05-15"})
    assert parse_recipe_seasons(form) == []


def test_parse_recipe_seasons_invalid_custom_date_is_silently_ignored():
    form = FakeForm({"season_custom_start": "garbage", "season_custom_end": "2000-06-20"})
    assert parse_recipe_seasons(form) == []


def test_parse_recipe_seasons_combines_preset_and_custom():
    form = FakeForm({
        "seasons": ["Sommer"],
        "season_custom_start": "2000-05-15",
        "season_custom_end": "2000-05-20",
    })
    ranges = parse_recipe_seasons(form)
    assert SEASON_PRESETS["Sommer"] in ranges
    assert (5, 15, 5, 20) in ranges
    assert len(ranges) == 2


# --- save_recipe_seasons / describe_recipe_seasons / format_recipe_seasons ---

def test_save_and_describe_recipe_seasons_roundtrip(app, make_recipe):
    from models import db

    recipe_id = make_recipe("Sommergericht")
    form = FakeForm({"seasons": ["Sommer"]})

    with app.app_context():
        save_recipe_seasons(recipe_id, form)
        db.session.commit()

        from models import Recipe
        recipe = db.session.get(Recipe, recipe_id)
        selected_presets, custom_range = describe_recipe_seasons(recipe)
        assert selected_presets == {"Sommer"}
        assert custom_range is None
        assert format_recipe_seasons(recipe) == ["Sommer"]


def test_save_recipe_seasons_replaces_existing(app, make_recipe):
    from models import Recipe, db

    recipe_id = make_recipe("Wechselgericht")
    with app.app_context():
        save_recipe_seasons(recipe_id, FakeForm({"seasons": ["Sommer"]}))
        db.session.commit()

        save_recipe_seasons(recipe_id, FakeForm({"seasons": ["Winter"]}))
        db.session.commit()

        recipe = db.session.get(Recipe, recipe_id)
        selected_presets, _ = describe_recipe_seasons(recipe)
        assert selected_presets == {"Winter"}


def test_format_recipe_seasons_custom_range_label(app, make_recipe):
    from models import Recipe, db

    recipe_id = make_recipe("Eigenzeitraum")
    with app.app_context():
        save_recipe_seasons(recipe_id, FakeForm({
            "season_custom_start": "2000-05-15",
            "season_custom_end": "2000-06-20",
        }))
        db.session.commit()
        recipe = db.session.get(Recipe, recipe_id)
        assert format_recipe_seasons(recipe) == ["15.5.–20.6."]
