"""Tests for Authelia-header-based identity (services/auth.py:
current_user()) and the global authentication requirement
(app.py: require_login()). Deliberately does NOT use the client fixture
from conftest.py (which already presents a valid header, see the comment
there) for the "no/bad header" cases - these tests are specifically
checking the not-authenticated state."""


def test_protected_route_returns_401_without_identity_header(app):
    resp = app.test_client().get("/manage")
    assert resp.status_code == 401


def test_malformed_email_header_is_treated_as_not_authenticated(app):
    resp = app.test_client().get("/manage", headers={"Remote-Email": "not-an-email"})
    assert resp.status_code == 401


def test_missing_email_header_with_other_headers_present_is_401(app):
    resp = app.test_client().get("/manage", headers={"Remote-Name": "Someone"})
    assert resp.status_code == 401


def test_static_files_reachable_without_identity_header(app):
    resp = app.test_client().get("/static/style.css")
    assert resp.status_code == 200


def test_first_request_with_new_email_auto_provisions_a_user(app):
    from models import User

    # zero-plan gate lands on the "no plan yet" page - follow_redirects
    # since whether that's a direct 200 or one 302 hop first depends on
    # whether today happens to already be a Friday (routes/plan/pages.py:
    # index() -> week_view(), which redirects to the canonical Friday URL
    # only when date.today() isn't already one).
    resp = app.test_client().get(
        "/", headers={"Remote-Email": "neu@test.local", "Remote-Name": "Neu"}, follow_redirects=True
    )
    assert resp.status_code == 200

    with app.app_context():
        user = User.query.filter_by(email="neu@test.local").first()
        assert user is not None
        assert user.name == "Neu"


def test_auto_provisioned_user_falls_back_to_email_local_part_without_name_header(app):
    from models import User

    app.test_client().get("/", headers={"Remote-Email": "onlyemail@test.local"})
    with app.app_context():
        assert User.query.filter_by(email="onlyemail@test.local").first().name == "onlyemail"


def test_email_header_is_normalized_to_lowercase(app):
    from models import User

    app.test_client().get("/", headers={"Remote-Email": "MixedCase@Test.Local"})
    with app.app_context():
        assert User.query.filter_by(email="mixedcase@test.local").first() is not None


def test_existing_user_is_reused_not_duplicated(app, make_user, login_as):
    user_id, _ = make_user("Bestehend")
    from models import User, db

    with app.app_context():
        email = db.session.get(User, user_id).email

    test_client = login_as(user_id)
    test_client.get("/manage")

    with app.app_context():
        assert User.query.filter_by(email=email).count() == 1


def test_display_name_resyncs_from_header_on_later_requests(app):
    from models import User

    test_client = app.test_client()
    test_client.get("/", headers={"Remote-Email": "rename@test.local", "Remote-Name": "Alt"})
    test_client.get("/", headers={"Remote-Email": "rename@test.local", "Remote-Name": "Neu"})

    with app.app_context():
        assert User.query.filter_by(email="rename@test.local").first().name == "Neu"


def test_pending_invite_is_accepted_on_first_authentication(app, client):
    """A plan invite to a not-yet-seen email (routes/sharing.py:
    invite_member()) is applied the moment that email first authenticates
    - previously done in routes/auth.py: register(), now the natural
    place for it is current_user()'s auto-provisioning path (see
    services/auth.py)."""
    from models import PlanMembership, User

    client.post("/manage/sharing/invite", data={"email": "invited@test.local"})

    app.test_client().get("/", headers={"Remote-Email": "invited@test.local"})

    with app.app_context():
        user = User.query.filter_by(email="invited@test.local").first()
        assert user is not None
        assert PlanMembership.query.filter_by(plan_id=client.plan_id, user_id=user.id).first() is not None
