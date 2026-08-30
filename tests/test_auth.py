"""Tests für Login/Registrierung/Logout und den globalen Login-Zwang
(routes/auth.py, app.py: require_login()). Nutzt bewusst NICHT die
client-Fixture aus conftest.py (die ist bereits eingeloggt, siehe
dortiger Kommentar) - diese Tests prüfen ja gerade den nicht/nicht-mehr
eingeloggten Zustand."""


def test_login_page_reachable_without_login(app):
    resp = app.test_client().get("/login")
    assert resp.status_code == 200
    assert b'name="email"' in resp.data
    # Registrieren-Button (siehe templates/login.html).
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

    # Session trägt jetzt eine gültige user_id - eine geschützte Route ist
    # ohne weiteren Login erreichbar.
    resp = test_client.get("/manage")
    assert resp.status_code == 200


def test_login_wrong_password_shows_error(app):
    from services.auth import hash_password
    from models import User, db

    with app.app_context():
        db.session.add(User(name="Bob", email="bob@test.local", password_hash=hash_password("richtig")))
        db.session.commit()

    resp = app.test_client().post("/login", data={"email": "bob@test.local", "password": "falsch"})
    assert resp.status_code == 200  # kein Redirect, Formular wird mit Fehler erneut gezeigt
    assert "E-Mail-Adresse oder Passwort falsch".encode() in resp.data


def test_login_unknown_email_shows_error(app):
    resp = app.test_client().post("/login", data={"email": "niemand@test.local", "password": "x"})
    assert resp.status_code == 200
    assert "E-Mail-Adresse oder Passwort falsch".encode() in resp.data


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
    """app.py: init_db() legt beim allerersten Start Jonas/Jonas und
    Elo/Elo mit Platzhalter-E-Mails (<name>@example.com) an - hier wird nur
    die Login-FUNKTION geprüft (eigener, frisch angelegter Nutzer mit
    denselben Anmeldedaten), nicht die Migration selbst (die läuft nur
    einmalig gegen eine echte, dauerhafte Datenbank, nicht gegen die pro
    Testlauf frische SQLite-Datei - siehe tests/conftest.py: app_module).
    Login mit der example.com-Platzhalteradresse ist im Testbetrieb
    ausdrücklich erlaubt (siehe models.py: User-Docstring)."""
    from services.auth import hash_password
    from models import User, db

    with app.app_context():
        db.session.add(User(name="Jonas", email="jonas@example.com", password_hash=hash_password("Jonas")))
        db.session.commit()

    resp = app.test_client().post("/login", data={"email": "jonas@example.com", "password": "Jonas"})
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
    """Ein next-Wert, der nicht mit genau einem "/" beginnt (offenes
    Redirect-Ziel wie "https://böse-seite.example" oder "//böse-seite"),
    wird ignoriert - sonst könnte ein präparierter Login-Link Nutzer nach
    dem echten Login unbemerkt auf eine fremde Seite weiterleiten."""
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

    # Sofort eingeloggt - ohne Plan-Mitgliedschaft (keine Einladung) landet
    # eine geschützte Route wie /manage über das Zero-Plan-Gate (app.py:
    # require_login()) auf der Wochenplan-Startseite statt direkt dort.
    resp = test_client.get("/manage", follow_redirects=True)
    assert resp.status_code == 200
    assert "noch in keinem Plan Mitglied".encode("utf-8") in resp.data


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
    assert "existiert bereits ein Konto".encode("utf-8") in resp.data


def test_register_rejects_missing_fields(app):
    resp = app.test_client().post("/register", data={"name": "", "email": "", "password": ""})
    assert resp.status_code == 200
    assert "Bitte Name, E-Mail-Adresse und Passwort angeben".encode("utf-8") in resp.data


def test_register_rejects_malformed_email(app):
    resp = app.test_client().post("/register", data={
        "name": "Fehler", "email": "keine-email", "password": "geheim123",
    })
    assert resp.status_code == 200
    assert "gültige E-Mail-Adresse".encode("utf-8") in resp.data

    from models import User
    with app.app_context():
        assert User.query.filter_by(name="Fehler").first() is None
