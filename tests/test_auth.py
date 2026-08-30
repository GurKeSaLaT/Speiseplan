"""Tests für Login/Logout und den globalen Login-Zwang (routes/auth.py,
app.py: require_login()). Nutzt bewusst NICHT die client-Fixture aus
conftest.py (die ist bereits eingeloggt, siehe dortiger Kommentar) -
diese Tests prüfen ja gerade den nicht/nicht-mehr eingeloggten Zustand."""


def test_login_page_reachable_without_login(app):
    resp = app.test_client().get("/login")
    assert resp.status_code == 200
    assert b'name="username"' in resp.data


def test_protected_route_redirects_to_login_without_session(app):
    resp = app.test_client().get("/manage")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_login_success_redirects_to_plan(app, make_user):
    make_user("Anna", "geheim")

    test_client = app.test_client()
    resp = test_client.post("/login", data={"username": "Anna", "password": "geheim"})
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
        db.session.add(User(username="Bob", password_hash=hash_password("richtig")))
        db.session.commit()

    resp = app.test_client().post("/login", data={"username": "Bob", "password": "falsch"})
    assert resp.status_code == 200  # kein Redirect, Formular wird mit Fehler erneut gezeigt
    assert "falsch".encode() not in resp.data or b"Name oder Passwort falsch" in resp.data
    assert b"Name oder Passwort falsch" in resp.data


def test_login_unknown_username_shows_error(app):
    resp = app.test_client().post("/login", data={"username": "Niemand", "password": "x"})
    assert resp.status_code == 200
    assert b"Name oder Passwort falsch" in resp.data


def test_seeded_users_can_log_in(app):
    """app.py: init_db() legt beim allerersten Start Jonas/Jonas und
    Elo/Elo an - hier wird nur die Login-FUNKTION geprüft (eigener,
    frisch angelegter Nutzer mit denselben Anmeldedaten), nicht die
    Migration selbst (die läuft nur einmalig gegen eine echte, dauerhafte
    Datenbank, nicht gegen die pro Testlauf frische SQLite-Datei - siehe
    tests/conftest.py: app_module)."""
    from services.auth import hash_password
    from models import User, db

    with app.app_context():
        db.session.add(User(username="Jonas", password_hash=hash_password("Jonas")))
        db.session.commit()

    resp = app.test_client().post("/login", data={"username": "Jonas", "password": "Jonas"})
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
        db.session.add(User(username="Clara", password_hash=hash_password("pw")))
        db.session.commit()

    test_client = app.test_client()
    resp = test_client.post("/login", data={"username": "Clara", "password": "pw", "next": "/manage"})
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
        db.session.add(User(username="Dana", password_hash=hash_password("pw")))
        db.session.commit()

    test_client = app.test_client()
    resp = test_client.post(
        "/login", data={"username": "Dana", "password": "pw", "next": "https://evil.example/"}
    )
    assert resp.status_code == 302
    assert "evil.example" not in resp.headers["Location"]
