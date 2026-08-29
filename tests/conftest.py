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
def client(app):
    return app.test_client()


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
def make_category(app):
    """Legt eine Category an und gibt ihre id zurück (kein ORM-Objekt -
    das würde nach Ende des with-Blocks als "detached" gelten, sobald
    Flask-SQLAlchemy die Session beim Schließen des App-Kontexts entfernt)."""
    from models import Category, db

    def _make(name="Testkategorie"):
        with app.app_context():
            cat = Category(name=name)
            db.session.add(cat)
            db.session.commit()
            return cat.id

    return _make


@pytest.fixture()
def make_recipe(app, make_category):
    def _make(name="Testgericht", category_id=None, is_side_dish=False, ingredients=None, **kwargs):
        from models import Ingredient, Recipe, db

        if category_id is None:
            category_id = make_category(f"Kategorie für {name}")

        with app.app_context():
            recipe = Recipe(name=name, category_id=category_id, is_side_dish=is_side_dish, **kwargs)
            db.session.add(recipe)
            db.session.flush()
            for ing in ingredients or []:
                db.session.add(Ingredient(recipe_id=recipe.id, **ing))
            db.session.commit()
            return recipe.id

    return _make
