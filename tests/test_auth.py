"""Tests for login/registration/logout and the global login requirement
(routes/auth.py, app.py: require_login()). Deliberately does NOT use
the client fixture from conftest.py (which is already logged in, see
the comment there) - these tests are specifically checking the
not/no-longer-logged-in state."""


def test_login_page_reachable_without_login(app):
    resp = app.test_client().get("/login")
    assert resp.status_code == 200
    assert b'name="email"' in resp.data
    # Register button (see templates/login.html).
    assert b'href="/register"' in resp.data


def test_protected_route_redirects_to_login_without_session(app):
    resp = app.test_client().get("/manage")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_login_success_redirects_to_plan(app, make_user):
    user_id, _ = make_user("Anna", "geheim")
    from models import User
    with app.app_context():
        email = User.query.get(user_id).email

    test_client = app.test_client()
    resp = test_client.post("/login", data={"email": email, "password": "geheim"})
    assert resp.status_code == 302
    assert "/login" not in resp.headers["Location"]

    # Session now carries a valid user_id - a protected route is
    # reachable without any further login.
    resp = test_client.get("/manage")
    assert resp.status_code == 200


def test_login_wrong_password_shows_error(app):
    from services.auth import hash_password
    from models import User, db

    with app.app_context():
        db.session.add(User(name="Bob", email="bob@test.local", password_hash=hash_password("richtig")))
        db.session.commit()

    resp = app.test_client().post("/login", data={"email": "bob@test.local", "password": "falsch"})
    assert resp.status_code == 200  # no redirect, form is shown again with an error
    assert "Email address or password is incorrect.".encode() in resp.data


def test_login_unknown_email_shows_error(app):
    resp = app.test_client().post("/login", data={"email": "niemand@test.local", "password": "x"})
    assert resp.status_code == 200
    assert "Email address or password is incorrect.".encode() in resp.data


def test_login_is_case_insensitive_on_email(app):
    from services.auth import hash_password
    from models import User, db

    with app.app_context():
        db.session.add(User(name="Case", email="case@test.local", password_hash=hash_password("pw")))
        db.session.commit()

    resp = app.test_client().post("/login", data={"email": "CASE@Test.Local", "password": "pw"})
    assert resp.status_code == 302
    assert "/login" not in resp.headers["Location"]


def test_seeded_users_can_log_in_with_placeholder_email(app):
    """app.py: init_db() creates Nutzer1/Nutzer1 and Nutzer2/Nutzer2 with
    placeholder emails (<name>@example.com) on the very first start -
    here only the login FUNCTION itself is checked (a separate,
    freshly-created user with the same credentials), not the migration
    itself (which only runs once against a real, persistent database,
    not against the fresh-per-test-run SQLite file - see
    tests/conftest.py: app_module). Logging in with the example.com
    placeholder address is explicitly allowed in test operation (see
    models/user.py: User docstring)."""
    from services.auth import hash_password
    from models import User, db

    with app.app_context():
        db.session.add(User(name="Nutzer1", email="nutzer1@example.com", password_hash=hash_password("Nutzer1")))
        db.session.commit()

    resp = app.test_client().post("/login", data={"email": "nutzer1@example.com", "password": "Nutzer1"})
    assert resp.status_code == 302
    assert "/login" not in resp.headers["Location"]


def test_logout_clears_session(client):
    resp = client.get("/manage")
    assert resp.status_code == 200

    resp = client.post("/logout")
    assert resp.status_code == 302

    resp = client.get("/manage")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_next_param_redirects_back_after_login(app):
    from services.auth import hash_password
    from models import User, db

    with app.app_context():
        db.session.add(User(name="Clara", email="clara@test.local", password_hash=hash_password("pw")))
        db.session.commit()

    test_client = app.test_client()
    resp = test_client.post("/login", data={"email": "clara@test.local", "password": "pw", "next": "/manage"})
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/manage")


def test_next_param_ignores_external_url(app):
    """A next value that does not start with exactly one "/" (an open
    redirect target like "https://evil-site.example" or "//evil-site")
    is ignored - otherwise a crafted login link could redirect users
    unnoticed to a foreign site after the real login."""
    from services.auth import hash_password
    from models import User, db

    with app.app_context():
        db.session.add(User(name="Dana", email="dana@test.local", password_hash=hash_password("pw")))
        db.session.commit()

    test_client = app.test_client()
    resp = test_client.post(
        "/login", data={"email": "dana@test.local", "password": "pw", "next": "https://evil.example/"}
    )
    assert resp.status_code == 302
    assert "evil.example" not in resp.headers["Location"]


# --- /register ---

def test_register_page_reachable_without_login(app):
    resp = app.test_client().get("/register")
    assert resp.status_code == 200
    assert b'name="name"' in resp.data
    assert b'name="email"' in resp.data


def test_register_page_prefills_email_from_query_param(app):
    resp = app.test_client().get("/register?email=invited@test.local")
    assert resp.status_code == 200
    assert b'value="invited@test.local"' in resp.data


def test_register_creates_account_and_logs_in(app):
    from models import User

    test_client = app.test_client()
    resp = test_client.post("/register", data={
        "name": "Neu", "email": "neu@test.local", "password": "geheim123",
    })
    assert resp.status_code == 302
    assert "/login" not in resp.headers["Location"]

    with app.app_context():
        user = User.query.filter_by(email="neu@test.local").first()
        assert user is not None
        assert user.name == "Neu"

    # Immediately logged in - without plan membership (no invitation), a
    # protected route like /manage lands on the weekly-plan landing page
    # via the zero-plan gate (app.py: require_login()) instead of going
    # there directly.
    resp = test_client.get("/manage", follow_redirects=True)
    assert resp.status_code == 200
    assert "not a member of any plan".encode("utf-8") in resp.data


def test_register_normalizes_email_to_lowercase(app):
    from models import User

    app.test_client().post("/register", data={
        "name": "Groß", "email": "GROSS@Test.Local", "password": "geheim123",
    })
    with app.app_context():
        assert User.query.filter_by(email="gross@test.local").first() is not None


def test_register_rejects_duplicate_email(app, make_user):
    user_id, _ = make_user("Bestehend")
    from models import User
    with app.app_context():
        email = User.query.get(user_id).email

    resp = app.test_client().post("/register", data={
        "name": "Zweiter", "email": email, "password": "geheim123",
    })
    assert resp.status_code == 200
    assert "An account already exists".encode("utf-8") in resp.data


def test_register_rejects_missing_fields(app):
    resp = app.test_client().post("/register", data={"name": "", "email": "", "password": ""})
    assert resp.status_code == 200
    assert "Please provide name, email address, and password.".encode("utf-8") in resp.data


def test_register_rejects_malformed_email(app):
    resp = app.test_client().post("/register", data={
        "name": "Fehler", "email": "keine-email", "password": "geheim123",
    })
    assert resp.status_code == 200
    assert "valid email address".encode("utf-8") in resp.data

    from models import User
    with app.app_context():
        assert User.query.filter_by(name="Fehler").first() is None
