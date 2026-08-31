"""Tests for services/settings.py: storage of the display unit setting
(AppSettings) - one row PER plan."""


def test_get_settings_creates_row_with_defaults(app, test_plan_id):
    from services.settings import get_settings

    with app.app_context():
        settings = get_settings(test_plan_id)
        assert settings.plan_id == test_plan_id
        assert settings.mass_unit == "g"
        assert settings.volume_unit == "ml"


def test_get_settings_returns_same_row_on_repeated_calls(app, test_plan_id):
    from models import AppSettings, db
    from services.settings import get_settings

    with app.app_context():
        first = get_settings(test_plan_id)
        first.mass_unit = "kg"
        db.session.commit()

        second = get_settings(test_plan_id)
        assert second.mass_unit == "kg"
        assert AppSettings.query.filter_by(plan_id=test_plan_id).count() == 1


def test_get_settings_is_independent_per_plan(app, test_plan_id, make_user):
    from services.settings import get_settings, update_display_units

    _, other_plan_id = make_user("Andere")
    with app.app_context():
        update_display_units(test_plan_id, "kg", "l")
        assert get_settings(other_plan_id).mass_unit == "g"
        assert get_settings(test_plan_id).mass_unit == "kg"


def test_get_display_units_returns_family_dict(app, test_plan_id):
    from services.settings import get_display_units, update_display_units

    with app.app_context():
        update_display_units(test_plan_id, "kg", "l")
        assert get_display_units(test_plan_id) == {"mass": "kg", "volume": "l"}


def test_update_display_units_rejects_invalid_mass_unit(app, test_plan_id):
    from services.settings import get_display_units, update_display_units

    with app.app_context():
        ok = update_display_units(test_plan_id, "pfund", "ml")
        assert ok is False
        # Default setting unchanged, since the value was rejected.
        assert get_display_units(test_plan_id) == {"mass": "g", "volume": "ml"}


def test_update_display_units_rejects_invalid_volume_unit(app, test_plan_id):
    from services.settings import get_display_units, update_display_units

    with app.app_context():
        ok = update_display_units(test_plan_id, "g", "gallonen")
        assert ok is False
        assert get_display_units(test_plan_id) == {"mass": "g", "volume": "ml"}


def test_update_display_units_accepts_valid_combination(app, test_plan_id):
    from services.settings import get_display_units, update_display_units

    with app.app_context():
        ok = update_display_units(test_plan_id, "kg", "ml")
        assert ok is True
        assert get_display_units(test_plan_id) == {"mass": "kg", "volume": "ml"}
