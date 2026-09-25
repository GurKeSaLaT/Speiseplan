"""Tests for routes/account.py: /manage/account (change UI language,
delete account) - name/email are read-only now (synced from Authelia, see
services/auth.py: current_user()) and there's no password anymore (see
services/auth.py module docstring)."""


def test_account_view_reachable(client):
    resp = client.get("/manage/account")
    assert resp.status_code == 200
    assert b"Testnutzer" in resp.data


def test_update_language_route_shows_success(client):
    # Stays "en" here so the success message itself (rendered in the
    # NEW, just-saved language, see app.py: get_locale()) is checked in
    # English - test_update_language_route_changes_language below covers
    # an actual language change without depending on the message text.
    resp = client.post("/manage/account/language", data={"language": "en"})
    assert resp.status_code == 200
    assert "Profile updated.".encode("utf-8") in resp.data


def test_update_language_route_changes_language(app, client):
    resp = client.post("/manage/account/language", data={"language": "de"})
    assert resp.status_code == 200

    from models import User, db
    with app.app_context():
        assert db.session.get(User, client.user_id).language == "de"


def test_update_language_route_rejects_invalid_language(app, client):
    resp = client.post("/manage/account/language", data={"language": "fr"})
    assert resp.status_code == 200
    assert "Please choose a valid language.".encode("utf-8") in resp.data

    from models import User, db
    with app.app_context():
        assert db.session.get(User, client.user_id).language == "en"


def test_delete_account_removes_user(app, client):
    resp = client.post("/manage/account/delete", follow_redirects=False)
    assert resp.status_code == 302

    from models import User, db
    with app.app_context():
        assert db.session.get(User, client.user_id) is None


def test_account_reachable_without_any_plan(app, make_user, login_as):
    """The zero-plan gate (app.py: require_login) must not block the
    profile page - a user without any plan membership still has to be
    able to manage/delete their account."""
    from models import PlanMembership, db

    user_id, _ = make_user("Planlos")
    with app.app_context():
        PlanMembership.query.filter_by(user_id=user_id).delete()
        db.session.commit()

    resp = login_as(user_id).get("/manage/account")
    assert resp.status_code == 200
