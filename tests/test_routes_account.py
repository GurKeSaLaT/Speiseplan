"""Tests for routes/account.py: /manage/account (change profile/password,
delete account)."""


def test_account_view_reachable(client):
    resp = client.get("/manage/account")
    assert resp.status_code == 200
    assert b"Testnutzer" in resp.data


def test_update_profile_shows_success(app, client):
    resp = client.post(
        "/manage/account/profile", data={"name": "Neuer Name", "email": "neu@test.local", "language": "en"}
    )
    assert resp.status_code == 200
    assert "Profile updated.".encode("utf-8") in resp.data

    from models import User
    with app.app_context():
        assert User.query.get(client.user_id).name == "Neuer Name"


def test_update_profile_shows_error_on_duplicate_email(app, client, make_user):
    from models import User

    _, _ = make_user("Andere")
    with app.app_context():
        other_email = User.query.filter_by(name="Andere").first().email

    resp = client.post(
        "/manage/account/profile", data={"name": "X", "email": other_email, "language": "en"}
    )
    assert resp.status_code == 200
    assert "already exists".encode("utf-8") in resp.data


def test_update_profile_route_changes_language(app, client):
    resp = client.post(
        "/manage/account/profile", data={"name": "X", "email": "x@test.local", "language": "de"}
    )
    assert resp.status_code == 200
    from models import User
    with app.app_context():
        assert User.query.get(client.user_id).language == "de"


def test_update_password_shows_success(client):
    resp = client.post("/manage/account/password", data={"current_password": "test", "new_password": "neuespw123", "confirm_new_password": "neuespw123"})
    assert resp.status_code == 200
    assert "Password changed.".encode("utf-8") in resp.data


def test_update_password_rejects_mismatched_confirmation(app, client):
    resp = client.post("/manage/account/password", data={"current_password": "test", "new_password": "neuespw123", "confirm_new_password": "andereswort"})
    assert resp.status_code == 200
    assert "Passwords do not match.".encode("utf-8") in resp.data

    from models import User
    from services.auth import verify_password
    with app.app_context():
        # Unchanged - the old password still verifies.
        assert verify_password(User.query.get(client.user_id), "test")


def test_update_password_shows_error_on_wrong_current(client):
    resp = client.post("/manage/account/password", data={"current_password": "falsch", "new_password": "neuespw123", "confirm_new_password": "neuespw123"})
    assert resp.status_code == 200
    assert "Current password is incorrect.".encode("utf-8") in resp.data


def test_delete_account_requires_correct_password(app, client):
    resp = client.post("/manage/account/delete", data={"password": "falsch"})
    assert resp.status_code == 200
    assert "Password is incorrect.".encode("utf-8") in resp.data

    from models import User
    with app.app_context():
        assert User.query.get(client.user_id) is not None


def test_delete_account_with_correct_password_logs_out(app, client):
    resp = client.post("/manage/account/delete", data={"password": "test"}, follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/login")

    from models import User
    with app.app_context():
        assert User.query.get(client.user_id) is None

    # Session is cleared - a protected route redirects to /login again.
    resp = client.get("/manage")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_account_reachable_without_any_plan(app, make_user):
    """The zero-plan gate (app.py: require_login) must not block the
    profile page - a user without any plan membership still has to be
    able to manage/delete their account."""
    from models import PlanMembership, db

    user_id, _ = make_user("Planlos")
    with app.app_context():
        PlanMembership.query.filter_by(user_id=user_id).delete()
        db.session.commit()

    test_client = app.test_client()
    with test_client.session_transaction() as sess:
        sess['user_id'] = user_id
    resp = test_client.get("/manage/account")
    assert resp.status_code == 200
