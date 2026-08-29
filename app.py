"""Einstiegspunkt der Speiseplan-App: erzeugt die Flask-App, verbindet sie
mit der Datenbank, registriert die vier Blueprints (die eigentlichen Routen
liegen in routes/*.py bzw. im routes/plan/-Paket) und kümmert sich beim
Start um Datenbank-Migrationen für Felder, die in früheren Versionen der
App noch nicht existierten.

Diese Datei bewusst schlank gehalten: sie enthält selbst keine einzige
Route mehr (die liegen alle in routes/plan/ (drei Dateien: pages.py,
day_actions.py, shopping.py - alle drei teilen sich den EINEN plan_bp-
Blueprint), routes/recipes.py, routes/categories.py, routes/manage.py) und
keine Planungs-/Auswahllogik (die liegt in services/planning.py und
services/seasons.py) - nur noch Anwendungs-Setup.
"""

import os
import secrets

from sqlalchemy import text
from flask import Flask
from flask_wtf import CSRFProtect

from models import db, Category, RecipeSeason, PlanDaySide
from services.ingredient_aliases import get_all_aliases
from services.nutrition import get_all_nutrition_entries
from services.seasons import SEASON_PRESETS
from services.shopping import SHOPPING_CATEGORIES, UNCATEGORIZED
from services.units import renormalize_existing_ingredients
from routes.plan import plan_bp
from routes.manage import manage_bp
from routes.recipes import recipes_bp
from routes.categories import categories_bp
from routes.settings import settings_bp

app = Flask(__name__)
# SQLite-Datei liegt in Flasks Standard-"instance"-Ordner (instance/speiseplan.db),
# der beim Deployment/Docker-Betrieb als Volume gemountet wird, damit die
# Datenbank Neustarts/Neubauten des Containers übersteht. Per DATABASE_URL
# überschreibbar (analog zu SECRET_KEY unten) - einzig genutzt von
# tests/conftest.py, damit Tests gegen eine eigene, temporäre SQLite-Datei
# laufen statt gegen instance/speiseplan.db (kein App-Factory-Pattern
# vorhanden, die Verbindung wird unten beim Modul-Import sofort aufgebaut).
app.config['SQLALCHEMY_DATABASE_URI'] = (
    os.environ.get('DATABASE_URL') or 'sqlite:///' + os.path.join(app.instance_path, 'speiseplan.db')
)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

os.makedirs(app.instance_path, exist_ok=True)
db.init_app(app)


def load_or_create_secret_key():
    """Liefert den geheimen Schlüssel, mit dem Flask Sessions und
    CSRF-Tokens signiert (siehe CSRFProtect unten - Flask-WTF speichert den
    CSRF-Token serverseitig in der signierten Session-Cookie, OHNE dass die
    App dafür ein eigenes Login/eine eigene Session-Verwaltung braucht).

    Kann über die Umgebungsvariable SECRET_KEY fest vorgegeben werden
    (sinnvoll, falls mehrere Container-Instanzen denselben Schlüssel
    brauchen); ist sie nicht gesetzt, wird EINMALIG ein zufälliger
    Schlüssel erzeugt und in instance/secret_key abgelegt - im selben,
    dauerhaft gemounteten Ordner wie die Datenbank, damit der Schlüssel
    (und damit die Gültigkeit ausgestellter CSRF-Tokens/Sessions) einen
    Container-Neustart übersteht. Ein bei jedem Neustart neu gewürfelter
    Schlüssel würde sonst alle gerade offenen Formulare im Browser
    ungültig machen.
    """
    env_key = os.environ.get('SECRET_KEY')
    if env_key:
        return env_key

    key_path = os.path.join(app.instance_path, 'secret_key')
    if os.path.exists(key_path):
        with open(key_path, 'r') as f:
            return f.read().strip()

    new_key = secrets.token_hex(32)
    with open(key_path, 'w') as f:
        f.write(new_key)
    return new_key


app.config['SECRET_KEY'] = load_or_create_secret_key()
# Schützt alle POST/PUT/PATCH/DELETE-Routen automatisch vor Cross-Site-
# Request-Forgery: ein Formular-Feld bzw. ein X-CSRFToken-Header mit
# gültigem, zur Session passendem Token wird ab jetzt bei jedem
# schreibenden Request verlangt (siehe csrf_token() in den Templates und
# window.CSRF_TOKEN in base.html für die fetch()-Aufrufe in plan.js) - ohne
# das würde jede fremde Webseite, die im selben Browser geöffnet ist,
# unbemerkt Schreibaktionen (Rezept löschen o.ä.) auslösen können.
CSRFProtect(app)

# Jeder Blueprint bringt seinen eigenen URL-Namensraum mit (z.B. wird aus
# der Funktion week_view in plan_bp der Endpunkt "plan.week_view", wie er
# in url_for()-Aufrufen in den Templates/Redirects verwendet wird).
app.register_blueprint(plan_bp)
app.register_blueprint(manage_bp)
app.register_blueprint(recipes_bp)
app.register_blueprint(categories_bp)
app.register_blueprint(settings_bp)


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
    if 'source_url' not in existing_columns:
        db.session.execute(text("ALTER TABLE recipe ADD COLUMN source_url VARCHAR(500)"))
        db.session.commit()
    if 'instructions' not in existing_columns:
        db.session.execute(text("ALTER TABLE recipe ADD COLUMN instructions TEXT"))
        db.session.commit()
    if 'nutrition_override' not in existing_columns:
        db.session.execute(text("ALTER TABLE recipe ADD COLUMN nutrition_override BOOLEAN NOT NULL DEFAULT 0"))
        db.session.commit()

    # Einkaufslisten-Kategorie einer Zutat (siehe services/shopping.py) - erst
    # mit der gruppierten/sortierten Einkaufsliste hinzugekommen. Bestehende
    # Zutaten bleiben dabei NULL (landen in der Einkaufsliste vorerst in der
    # Sonstiges-Sammelgruppe, bis das jeweilige Rezept einmal neu gespeichert
    # wird) - eine automatische Zuordnung ist ohne Nutzereingabe nicht
    # zuverlässig möglich.
    existing_ingredient_columns = {row[1] for row in db.session.execute(text("PRAGMA table_info(ingredient)"))}
    if 'category' not in existing_ingredient_columns:
        db.session.execute(text("ALTER TABLE ingredient ADD COLUMN category VARCHAR(50)"))
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

    # Beliebig viele Beilagen pro Tag statt genau einer: frühere Versionen
    # hatten eine einzelne side_recipe_id-Spalte direkt auf PlanDay; das
    # wurde durch die separate PlanDaySide-Tabelle ersetzt (siehe models.py).
    # Die neue Tabelle existiert bereits durch db.create_all() oben - hier
    # wird nur noch der vorhandene Einzelwert (falls gesetzt) einmalig in
    # eine PlanDaySide-Zeile übertragen, dann die alte Spalte entfernt.
    existing_plan_day_columns = {row[1] for row in db.session.execute(text("PRAGMA table_info(plan_day)"))}
    if 'side_recipe_id' in existing_plan_day_columns:
        old_sides = db.session.execute(
            text("SELECT id, side_recipe_id FROM plan_day WHERE side_recipe_id IS NOT NULL")
        ).fetchall()
        for plan_day_id, side_recipe_id in old_sides:
            db.session.add(PlanDaySide(plan_day_id=plan_day_id, recipe_id=side_recipe_id))
        db.session.commit()

        # SQLite verweigert ein direktes ALTER TABLE ... DROP COLUMN für
        # side_recipe_id ("unknown column ... in foreign key definition"),
        # weil die Spalte Teil einer FOREIGN-KEY-Definition der Tabelle
        # selbst ist - eine bekannte SQLite-Einschränkung, anders als bei
        # der season-Migration oben (dort war die Spalte kein Fremdschlüssel).
        # Stattdessen wird die Tabelle nach dem von der SQLite-Doku
        # empfohlenen Muster neu aufgebaut: Kopie ohne die Spalte anlegen,
        # Daten (inkl. IDs, damit die soeben angelegten PlanDaySide-Zeilen
        # weiter auf die richtigen Tage zeigen) umkopieren, alte Tabelle
        # durch die neue ersetzen.
        db.session.execute(text("""
            CREATE TABLE plan_day_new (
                id INTEGER NOT NULL PRIMARY KEY,
                date DATE NOT NULL UNIQUE,
                excluded BOOLEAN NOT NULL,
                servings INTEGER NOT NULL,
                main_recipe_id INTEGER,
                FOREIGN KEY(main_recipe_id) REFERENCES recipe (id)
            )
        """))
        db.session.execute(text("""
            INSERT INTO plan_day_new (id, date, excluded, servings, main_recipe_id)
            SELECT id, date, excluded, servings, main_recipe_id FROM plan_day
        """))
        db.session.execute(text("DROP TABLE plan_day"))
        db.session.execute(text("ALTER TABLE plan_day_new RENAME TO plan_day"))
        db.session.commit()

    # "Gekocht"-Häkchen im Rezept-Detail-Fenster (siehe models.py: PlanDay.cooked/
    # PlanDaySide.cooked) - erst nachträglich hinzugekommen, existing_plan_day_columns
    # wurde oben bereits für die side_recipe_id-Migration ermittelt.
    existing_plan_day_columns = {row[1] for row in db.session.execute(text("PRAGMA table_info(plan_day)"))}
    if 'cooked' not in existing_plan_day_columns:
        db.session.execute(text("ALTER TABLE plan_day ADD COLUMN cooked BOOLEAN NOT NULL DEFAULT 0"))
        db.session.commit()

    existing_plan_day_side_columns = {row[1] for row in db.session.execute(text("PRAGMA table_info(plan_day_side)"))}
    if 'cooked' not in existing_plan_day_side_columns:
        db.session.execute(text("ALTER TABLE plan_day_side ADD COLUMN cooked BOOLEAN NOT NULL DEFAULT 0"))
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

    # Bestehende Zutaten-Mengen/Einheiten (z.B. "Gramm", "kg", "gr" als
    # reiner Text aus der Zeit vor der Einheiten-Vereinheitlichung) einmalig
    # auf die kanonische Form bringen (siehe services/units.py). Wie die
    # Migrationsschritte oben idempotent: auf einer bereits vollständig
    # kanonischen Datenbank ändert ein erneuter Aufruf nichts mehr.
    renormalize_existing_ingredients()


# Migration läuft synchron beim Modul-Import, nicht erst beim ersten
# Request - so ist die Datenbank garantiert aktuell, bevor überhaupt eine
# Anfrage bearbeitet wird (wichtig z.B. für den Gunicorn-/Docker-Betrieb
# mit mehreren Workern, die sonst gleichzeitig migrieren könnten).
with app.app_context():
    init_db()


@app.after_request
def set_security_headers(response):
    """Setzt bei JEDER Antwort einen Satz grundlegender Security-Header, die
    Flask standardmäßig nicht mitschickt (per Pentest am 2026-08-28
    festgestellt). Kein HSTS, da die App bewusst nur über HTTP im Heimnetz
    läuft (kein TLS-Zertifikat vorhanden) - ein HSTS-Header ohne HTTPS wäre
    wirkungslos bzw. irreführend.

    Die Content-Security-Policy erlaubt 'unsafe-inline' für Skripte/Styles,
    weil die Templates durchgängig mit onclick-Attributen und eingebetteten
    <style>/<script>-Blöcken arbeiten (kein Nonce-/Hash-basiertes Setup) -
    verhindert aber weiterhin das Nachladen von Code/Bildern aus fremden
    Quellen, das Einbetten der Seite in ein fremdes iframe
    (frame-ancestors) und das Absenden von Formularen an fremde Ziele
    (form-action).
    """
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Referrer-Policy'] = 'same-origin'
    response.headers['Permissions-Policy'] = 'geolocation=(), camera=(), microphone=()'
    response.headers['Content-Security-Policy'] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; "
        "frame-ancestors 'none'; "
        "base-uri 'self'; "
        "form-action 'self'"
    )
    return response


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


@app.context_processor
def inject_shopping_categories():
    """Stellt allen Templates die feste Einkaufslisten-Kategorie-Reihenfolge
    zur Verfügung (siehe services/shopping.py) - gebraucht sowohl von den
    Kategorie-Dropdowns beim Zutaten-Eintragen (recipe_create.html,
    recipe_edit_list.html) als auch, über window.SHOPPING_CATEGORIES in
    base.html, von der clientseitigen Sortierung/Gruppierung der
    Einkaufsliste (static/plan.js)."""
    return {'shopping_categories': SHOPPING_CATEGORIES, 'shopping_uncategorized': UNCATEGORIZED}


@app.context_processor
def inject_ingredient_aliases():
    """Stellt allen Templates die gepflegten Zutaten-Alias-Zuordnungen zur
    Verfügung (siehe services/ingredient_aliases.py) - genutzt wird das
    aktuell nur von recipe_create.html/recipe_edit_list.html
    (window.INGREDIENT_ALIASES, siehe static/ingredient_alias_hint.js),
    global als Context Processor aber genauso einfach wie
    inject_shopping_categories() oben gehalten statt die Abfrage in jeder
    einzelnen Route zu wiederholen."""
    return {'ingredient_aliases': get_all_aliases()}


@app.context_processor
def inject_ingredient_nutrition():
    """Stellt allen Templates die gepflegten Nährwert-Referenzen je
    Alias-Zielzutat zur Verfügung (siehe services/nutrition.py) - genutzt
    von recipe_create.html/recipe_edit_list.html (window.INGREDIENT_NUTRITION,
    siehe static/ingredient_alias_hint.js), analog zu
    inject_ingredient_aliases() oben."""
    return {'ingredient_nutrition': get_all_nutrition_entries()}


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
    # host='0.0.0.0' ist im Docker-Deployment nötig: mit dem Flask-
    # Standard ('127.0.0.1') wäre die App selbst innerhalb des Containers
    # nur von localhost aus erreichbar, also von außen gar nicht. Für
    # lokale Testläufe außerhalb von Docker per HOST-Umgebungsvariable
    # überschreibbar, z.B. HOST=127.0.0.1, damit der lokale Testserver
    # bewusst NICHT über die LAN-IP der Maschine erreichbar ist, sondern
    # nur von diesem Rechner selbst.
    debug_mode = os.environ.get('FLASK_DEBUG', '1') == '1'
    port = int(os.environ.get('PORT', 5000))
    host = os.environ.get('HOST', '0.0.0.0')
    app.run(host=host, port=port, debug=debug_mode)
