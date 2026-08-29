"""Tests für services/settings.py: Singleton-Speicherung der Anzeige-
Einheiten-Einstellung (AppSettings)."""


def test_get_settings_creates_singleton_with_defaults(app):
    from services.settings import get_settings

    with app.app_context():
        settings = get_settings()
        assert settings.id == 1
        assert settings.mass_unit == "g"
        assert settings.volume_unit == "ml"


def test_get_settings_returns_same_row_on_repeated_calls(app):
    from models import AppSettings, db
    from services.settings import get_settings

    with app.app_context():
        first = get_settings()
        first.mass_unit = "kg"
        db.session.commit()

        second = get_settings()
        assert second.mass_unit == "kg"
        assert AppSettings.query.count() == 1


def test_get_display_units_returns_family_dict(app):
    from services.settings import get_display_units, update_display_units

    with app.app_context():
        update_display_units("kg", "l")
        assert get_display_units() == {"mass": "kg", "volume": "l"}


def test_update_display_units_rejects_invalid_mass_unit(app):
    from services.settings import get_display_units, update_display_units

    with app.app_context():
        ok = update_display_units("pfund", "ml")
        assert ok is False
        # Unveränderte Standardeinstellung, da der Wert abgelehnt wurde.
        assert get_display_units() == {"mass": "g", "volume": "ml"}


def test_update_display_units_rejects_invalid_volume_unit(app):
    from services.settings import get_display_units, update_display_units

    with app.app_context():
        ok = update_display_units("g", "gallonen")
        assert ok is False
        assert get_display_units() == {"mass": "g", "volume": "ml"}


def test_update_display_units_accepts_valid_combination(app):
    from services.settings import get_display_units, update_display_units

    with app.app_context():
        ok = update_display_units("kg", "ml")
        assert ok is True
        assert get_display_units() == {"mass": "kg", "volume": "ml"}
