"""Gemeinsame Pytest-Fixtures für die ganze Suite.

app.py verbindet sich beim reinen Modul-Import bereits mit der Datenbank
(kein App-Factory-Pattern, siehe app.py: `with app.app_context(): init_db()`
läuft auf Modulebene) - die Umgebungsvariable DATABASE_URL muss deshalb
VOR dem allerersten `import app` gesetzt sein, sonst würde selbst ein
einzelner Testlauf die echte instance/speiseplan.db anfassen. Die
app_module-Fixture ist deshalb session-scoped: der erste Test, der sie
(direkt oder über app/client) anfordert, löst genau einmal den Import
gegen eine eigene, temporäre SQLite-Datei aus; alle weiteren Tests nutzen
dieselbe bereits verbundene App weiter.

Damit trotzdem jeder Test mit einer leeren Datenbank startet, unabhängig
von der Ausführungsreihenfolge, leert die autouse-Fixture _clean_tables
nach JEDEM Test alle Tabellen (nicht per Rollback, da die Routen selbst
committen) - Tests, die bestimmte Ausgangsdaten brauchen, legen sie über
die Factory-Fixtures make_category/make_recipe unten selbst an.
"""
import os

import pytest


@pytest.fixture(scope="session")
def app_module(tmp_path_factory):
    db_path = tmp_path_factory.mktemp("db") / "test.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"
    os.environ["SECRET_KEY"] = "test-secret-key"

    import app as _app_module  # noqa: PLC0415 - beabsichtigt spät, siehe Docstring oben

    _app_module.app.config["TESTING"] = True
    _app_module.app.config["WTF_CSRF_ENABLED"] = False
    return _app_module


@pytest.fixture()
def app(app_module):
    return app_module.app


@pytest.fixture()
def make_user(app):
    """Legt einen User samt eigenem, gesternten Plan an (analog zu
    make_category/make_recipe unten) und gibt (user_id, plan_id) zurück.

    Ein OHNE explizites username aufgerufenes _make() bekommt einen
    automatisch durchnummerierten Namen ("Testnutzer2", "Testnutzer3", ...)
    statt immer denselben "Testnutzer" - sonst würde ein zweiter bare
    make_user()-Aufruf im selben Test (oder einer, der zusätzlich die
    client-Fixture nutzt, die bereits intern "Testnutzer" anlegt, siehe
    default_plan) mit einer UNIQUE-Constraint-Verletzung auf User.username
    kollidieren. Bei EXPLIZIT übergebenem Namen bleibt das Verhalten
    unverändert."""
    from models import Plan, PlanMembership, User, db
    from services.auth import hash_password

    counter = {"n": 1}

    def _make(username=None, password="test"):
        if username is None:
            counter["n"] += 1
            username = f"Testnutzer{counter['n']}"
        with app.app_context():
            user = User(name=username, email=f"{username.lower()}@test.local", password_hash=hash_password(password))
            db.session.add(user)
            db.session.flush()
            plan = Plan(name=f"{username}s Plan", owner_user_id=user.id)
            db.session.add(plan)
            db.session.flush()
            db.session.add(PlanMembership(plan_id=plan.id, user_id=user.id, is_starred=True))
            db.session.commit()
            return user.id, plan.id

    return _make


@pytest.fixture()
def default_plan(make_user):
    """EIN Nutzer+Plan-Paar, lazy/einmalig pro Test von pytest zwischen-
    gespeichert (Standard-Fixture-Semantik: alle Fixtures, die
    default_plan in DEMSELBEN Test anfordern, bekommen dasselbe Ergebnis) -
    gemeinsame Grundlage für client/make_category/make_recipe unten, damit
    ein ohne explizites plan_id angelegtes Rezept/eine Kategorie
    automatisch im selben Plan landet, in den der Testclient eingeloggt
    ist (genau das erwarten die allermeisten Tests, die client UND
    make_recipe/make_category zusammen benutzen)."""
    user_id, plan_id = make_user("Testnutzer")
    return {"user_id": user_id, "plan_id": plan_id}


@pytest.fixture()
def test_plan_id(default_plan):
    """Kurzform für Tests, die nur die plan_id brauchen (z.B. direkte
    Unit-Tests von services/*.py-Funktionen, die jetzt ein plan_id-
    Argument verlangen) - dasselbe zwischengespeicherte Ergebnis wie
    default_plan, nur ohne das Dict drumherum."""
    return default_plan['plan_id']


@pytest.fixture()
def client(app, default_plan):
    """Ein bereits eingeloggter Testclient: seit der Nutzerverwaltung
    verlangt app.py: require_login() für praktisch jede Route eine
    aktive Session, ganz unabhängig davon, was der jeweilige Test
    eigentlich prüfen will - Login ist damit einfach eine weitere
    unsichtbare Vorbedingung, wie schon _clean_tables unten. client.user_id/
    client.plan_id (siehe Attribute unten) machen den zugehörigen
    Test-Nutzer/-Plan für Tests greifbar, die z.B. einen PlanDay direkt
    per ORM anlegen müssen (PlanDay.plan_id ist NOT NULL). Tests, die
    explizit das NICHT eingeloggte Verhalten prüfen wollen (Redirect auf
    /login), bauen sich stattdessen direkt über app.test_client() einen
    eigenen, bewusst anonymen Client (siehe tests/test_auth.py)."""
    test_client = app.test_client()
    with test_client.session_transaction() as sess:
        sess['user_id'] = default_plan['user_id']
        sess['active_plan_id'] = default_plan['plan_id']
    test_client.user_id = default_plan['user_id']
    test_client.plan_id = default_plan['plan_id']
    return test_client


@pytest.fixture(autouse=True)
def _clean_tables(app_module):
    """Leert alle Tabellen VOR jedem Test (init_db() sät beim allerersten
    App-Import über init_db() Standard-Kategorien in die sonst leere
    Testdatenbank ein - ohne diesen Schritt würde ausgerechnet der erste
    Test der Session mit "Fleisch"/"Fisch"/... als bereits vorhandenen
    Kategorien kollidieren) UND danach (Sicherheitsnetz, falls ein Test
    mitten in einer Assertion abbricht, bevor er selbst aufräumt)."""
    from models import db

    def _wipe():
        with app_module.app.app_context():
            for table in reversed(db.metadata.sorted_tables):
                db.session.execute(table.delete())
            db.session.commit()

    _wipe()
    yield
    _wipe()


@pytest.fixture()
def make_category(app, default_plan):
    """Legt eine Category an und gibt ihre id zurück (kein ORM-Objekt -
    das würde nach Ende des with-Blocks als "detached" gelten, sobald
    Flask-SQLAlchemy die Session beim Schließen des App-Kontexts entfernt).
    Landet ohne explizites plan_id im selben Plan wie die client-Fixture
    (siehe default_plan) - ein Test, der eine Kategorie bewusst einem
    ANDEREN Plan zuordnen will (z.B. für Isolations-Tests), übergibt
    plan_id explizit."""
    from models import Category, db

    def _make(name="Testkategorie", plan_id=None):
        with app.app_context():
            cat = Category(plan_id=plan_id or default_plan['plan_id'], name=name)
            db.session.add(cat)
            db.session.commit()
            return cat.id

    return _make


@pytest.fixture()
def make_recipe(app, default_plan, make_category):
    """Wie make_category oben: ohne explizites plan_id landet das Rezept
    (als Eigentümer, Recipe.owner_plan_id) im selben Plan wie die
    client-Fixture."""
    def _make(name="Testgericht", category_id=None, is_side_dish=False, ingredients=None, plan_id=None, **kwargs):
        from models import Ingredient, Recipe, db

        owner_plan_id = plan_id or default_plan['plan_id']
        if category_id is None:
            category_id = make_category(f"Kategorie für {name}", plan_id=owner_plan_id)

        with app.app_context():
            recipe = Recipe(
                name=name, owner_plan_id=owner_plan_id, category_id=category_id,
                is_side_dish=is_side_dish, **kwargs
            )
            db.session.add(recipe)
            db.session.flush()
            for ing in ingredients or []:
                db.session.add(Ingredient(recipe_id=recipe.id, **ing))
            db.session.commit()
            return recipe.id

    return _make
