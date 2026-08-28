"""Einstiegspunkt der Speiseplan-App: erzeugt die Flask-App, verbindet sie
mit der Datenbank, registriert die vier Blueprints (die eigentlichen Routen
liegen in routes/*.py) und kümmert sich beim Start um Datenbank-Migrationen
für Felder, die in früheren Versionen der App noch nicht existierten.

Diese Datei bewusst schlank gehalten: sie enthält selbst keine einzige
Route mehr (die liegen alle in routes/plan.py, routes/recipes.py,
routes/categories.py, routes/manage.py) und keine Planungs-/Auswahllogik
(die liegt in services/planning.py und services/seasons.py) - nur noch
Anwendungs-Setup.
"""

import os

from sqlalchemy import text
from flask import Flask

from models import db, Category, RecipeSeason
from services.seasons import SEASON_PRESETS
from routes.plan import plan_bp
from routes.manage import manage_bp
from routes.recipes import recipes_bp
from routes.categories import categories_bp

app = Flask(__name__)
# SQLite-Datei liegt in Flasks Standard-"instance"-Ordner (instance/speiseplan.db),
# der beim Deployment/Docker-Betrieb als Volume gemountet wird, damit die
# Datenbank Neustarts/Neubauten des Containers übersteht.
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(app.instance_path, 'speiseplan.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

os.makedirs(app.instance_path, exist_ok=True)
db.init_app(app)

# Jeder Blueprint bringt seinen eigenen URL-Namensraum mit (z.B. wird aus
# der Funktion week_view in plan_bp der Endpunkt "plan.week_view", wie er
# in url_for()-Aufrufen in den Templates/Redirects verwendet wird).
app.register_blueprint(plan_bp)
app.register_blueprint(manage_bp)
app.register_blueprint(recipes_bp)
app.register_blueprint(categories_bp)


def init_db():
    """Legt beim App-Start fehlende Tabellen an (db.create_all() - betrifft
    z.B. eine komplett neue, leere Datenbank oder eine neu hinzugekommene
    Tabelle wie plan_day) und migriert bestehende Datenbanken älterer
    App-Versionen auf das aktuelle Schema.

    Es gibt in diesem Projekt bewusst kein Migrations-Framework (wie
    Alembic/Flask-Migrate) - dafür ist die App zu klein und die Änderungen
    zu selten. Stattdessen prüft dieser Code bei JEDEM Start per
    PRAGMA table_info, welche Spalten in der recipe-Tabelle bereits
    existieren, und holt fehlende einmalig per ALTER TABLE nach. Jeder
    Migrationsschritt ist dadurch idempotent: läuft die Funktion erneut auf
    einer bereits aktuellen Datenbank, tut sie nichts mehr.

    Die season-Migration ist ein Sonderfall (Spalten-UMBAU statt nur
    -Ergänzung): frühere Versionen hatten eine einzelne season-Textspalte
    direkt auf Recipe; das wurde später durch die separate
    recipe_season-Tabelle ersetzt, die MEHRERE Zeiträume pro Rezept
    erlaubt. Vorhandene Werte werden dabei einmalig über SEASON_PRESETS
    (Saison-Name -> Zeitraum-Tupel) in die neue Tabelle übertragen, dann
    wird die alte Spalte entfernt.
    """
    db.create_all()

    existing_columns = {row[1] for row in db.session.execute(text("PRAGMA table_info(recipe)"))}
    if 'is_side_dish' not in existing_columns:
        db.session.execute(text("ALTER TABLE recipe ADD COLUMN is_side_dish BOOLEAN NOT NULL DEFAULT 0"))
        db.session.commit()
    if 'servings' not in existing_columns:
        db.session.execute(text("ALTER TABLE recipe ADD COLUMN servings INTEGER NOT NULL DEFAULT 2"))
        db.session.commit()
    if 'is_favorite' not in existing_columns:
        db.session.execute(text("ALTER TABLE recipe ADD COLUMN is_favorite BOOLEAN NOT NULL DEFAULT 0"))
        db.session.commit()

    if 'season' in existing_columns:
        old_seasons = db.session.execute(text("SELECT id, season FROM recipe WHERE season IS NOT NULL")).fetchall()
        for recipe_id, season_name in old_seasons:
            preset = SEASON_PRESETS.get(season_name)
            if preset:
                db.session.add(RecipeSeason(
                    recipe_id=recipe_id,
                    start_month=preset[0], start_day=preset[1],
                    end_month=preset[2], end_day=preset[3]
                ))
        db.session.commit()
        db.session.execute(text("ALTER TABLE recipe DROP COLUMN season"))
        db.session.commit()

    # Erststart mit komplett leerer Datenbank: ein sinnvoller Grundstock an
    # Kategorien, damit die App nicht mit einer leeren Kategorie-Liste
    # (und damit unbenutzbarer automatischer Planung) startet. Wird NUR
    # angelegt, wenn noch keine einzige Kategorie existiert - eigene,
    # später hinzugefügte oder umbenannte Kategorien werden dadurch nie
    # überschrieben oder erneut angelegt.
    if not Category.query.first():
        default_categories = ["Fleisch", "Fisch", "Vegetarisch", "Vegan", "Nudeln/Pasta", "Suppe/Eintopf", "Schnelle Küche"]
        for cat_name in default_categories:
            db.session.add(Category(name=cat_name))
        db.session.commit()


# Migration läuft synchron beim Modul-Import, nicht erst beim ersten
# Request - so ist die Datenbank garantiert aktuell, bevor überhaupt eine
# Anfrage bearbeitet wird (wichtig z.B. für den Gunicorn-/Docker-Betrieb
# mit mehreren Workern, die sonst gleichzeitig migrieren könnten).
with app.app_context():
    init_db()


@app.context_processor
def inject_css_version():
    """Stellt allen Templates die Variable css_version zur Verfügung (siehe
    templates/base.html: style.css wird mit ?v={{ css_version }} eingebunden).

    Nutzt die Änderungszeit der style.css-Datei selbst als Versionsnummer:
    ändert sich die Datei, ändert sich automatisch auch dieser Query-
    Parameter, wodurch Browser die neue Version laden statt eine
    veraltete, gecachte Kopie weiterzuverwenden - ganz ohne manuelles
    Hochzählen einer Versionsnummer bei jeder CSS-Änderung. Schlägt der
    Dateizugriff fehl (z.B. weil style.css aus irgendeinem Grund fehlt),
    wird 0 verwendet statt die Seite mit einem Fehler abzubrechen.
    """
    css_path = os.path.join(app.static_folder, 'style.css')
    try:
        css_version = int(os.path.getmtime(css_path))
    except OSError:
        css_version = 0
    return {'css_version': css_version}


if __name__ == '__main__':
    # Nur relevant, wenn app.py direkt ausgeführt wird (lokale Entwicklung
    # bzw. CMD im Dockerfile) - unter einem echten WSGI-Server (Gunicorn
    # o.ä.) würde dieser Block gar nicht durchlaufen.
    #
    # FLASK_DEBUG und PORT werden im Docker-Deployment über das Dockerfile
    # gesetzt (FLASK_DEBUG=0, PORT=80): im Container läuft die App damit
    # ohne Werkzeug-Debugger (der bei Netzwerk-Erreichbarkeit ein
    # Remote-Code-Execution-Risiko wäre) und auf dem Standard-HTTP-Port.
    # Lokal ohne gesetzte Variablen bleiben Debug-/Autoreload-Modus an und
    # der Port bei 5000 (kein Root nötig, anders als bei Port 80).
    #
    # host='0.0.0.0' ist in jedem Fall nötig: mit dem Flask-Standard
    # ('127.0.0.1') wäre die App selbst innerhalb des Docker-Containers nur
    # von localhost aus erreichbar, also von außen gar nicht.
    debug_mode = os.environ.get('FLASK_DEBUG', '1') == '1'
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=debug_mode)
