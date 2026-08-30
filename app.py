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
from flask import Flask, redirect, request, session, url_for
from flask_wtf import CSRFProtect

from models import db, Category, Plan, PlanMembership, RecipeSeason, PlanDaySide, User
from services.auth import current_plan, current_user, hash_password, user_plan_memberships
from services.ingredient_aliases import get_all_aliases
from services.nutrition import get_all_nutrition_entries
from services.seasons import SEASON_PRESETS
from services.shopping import PANTRY_CATEGORIES, SHOPPING_CATEGORIES, UNCATEGORIZED
from services.units import renormalize_existing_ingredients
from routes.auth import auth_bp, SESSION_LIFETIME
from routes.plan import plan_bp
from routes.manage import manage_bp
from routes.recipes import recipes_bp
from routes.categories import categories_bp
from routes.settings import settings_bp
from routes.sharing import sharing_bp

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
# Wie lange eine Session ohne erneuten Login gültig bleibt (siehe
# routes/auth.py: SESSION_LIFETIME-Kommentar).
app.config['PERMANENT_SESSION_LIFETIME'] = SESSION_LIFETIME

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
app.register_blueprint(auth_bp)
app.register_blueprint(plan_bp)
app.register_blueprint(manage_bp)
app.register_blueprint(recipes_bp)
app.register_blueprint(categories_bp)
app.register_blueprint(settings_bp)
app.register_blueprint(sharing_bp)


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
    if 'updated_at' not in existing_columns:
        # SQLite verweigert "DEFAULT CURRENT_TIMESTAMP" direkt im ALTER
        # TABLE ("Cannot add a column with non-constant default") - Spalte
        # daher ohne Default anlegen und bestehende Zeilen per separatem
        # UPDATE auf den Migrationszeitpunkt setzen (ein sinnvoller
        # Startwert für die "Zuletzt bearbeitet"-Liste in routes/manage.py,
        # auch ohne echte Historie für ältere Rezepte).
        db.session.execute(text("ALTER TABLE recipe ADD COLUMN updated_at DATETIME"))
        db.session.execute(text("UPDATE recipe SET updated_at = CURRENT_TIMESTAMP WHERE updated_at IS NULL"))
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

    # --- Nutzerverwaltung: Login + eigene/geteilte Wochenpläne ---
    # Erststart (noch kein einziger Nutzer vorhanden): legt die beiden
    # aktuell vorgesehenen Konten an (siehe models.py: User) - es gibt
    # keine eigene Registrierungsseite, neue Nutzer kommen bislang nur über
    # diese Stelle hinzu. Jeder bekommt sofort einen eigenen Plan (siehe
    # models.py: Plan/PlanMembership); NUR Jonas' eigener Plan wird dabei
    # direkt gesternt - er wird gleich unten zum "legacy_plan", dem die
    # komplette bisherige Planungs-Historie zugeordnet wird, und Elo
    # bekommt IHREN Stern dort (nicht auf ihrem eigenen, leeren Plan) -
    # so hat jeder Nutzer durchgehend genau einen gesternten Plan, und
    # beide landen nach dem allerersten Login auf demselben, bereits
    # vorhandenen Plan.
    seeded_plans_by_username = {}
    if not User.query.first():
        for username in ("Jonas", "Elo"):
            user = User(username=username, password_hash=hash_password(username))
            db.session.add(user)
            db.session.flush()
            plan = Plan(name=f"{username}s Plan", owner_user_id=user.id)
            db.session.add(plan)
            db.session.flush()
            db.session.add(PlanMembership(plan_id=plan.id, user_id=user.id, is_starred=(username == "Jonas")))
            seeded_plans_by_username[username] = plan
        db.session.commit()

    # plan_id auf PlanDay/ExtraShoppingItem: existierte in früheren
    # Versionen der App noch nicht (der Kalender war global, ein einziger
    # von allen geteilter Plan) - fehlt die Spalte, wird sie ergänzt und
    # ALLE bestehenden Zeilen (die komplette bisherige Planungs-Historie)
    # werden Jonas' neu angelegtem Plan zugeordnet; Elo wird zusätzlich
    # (gesternt) als Mitglied dieses Plans eingetragen - so sehen nach
    # dieser einmaligen Migration BEIDE exakt denselben, bereits
    # vorhandenen Plan, ganz ohne dass jemand manuell etwas einladen müsste.
    existing_plan_day_columns = {row[1] for row in db.session.execute(text("PRAGMA table_info(plan_day)"))}
    if 'plan_id' not in existing_plan_day_columns:
        legacy_plan = seeded_plans_by_username.get("Jonas") or Plan.query.first()
        if legacy_plan is not None:
            elo = User.query.filter_by(username="Elo").first()
            if elo is not None and not PlanMembership.query.filter_by(plan_id=legacy_plan.id, user_id=elo.id).first():
                db.session.add(PlanMembership(plan_id=legacy_plan.id, user_id=elo.id, is_starred=True))
                db.session.commit()

            db.session.execute(text("ALTER TABLE plan_day ADD COLUMN plan_id INTEGER"))
            db.session.execute(
                text("UPDATE plan_day SET plan_id = :pid WHERE plan_id IS NULL"), {"pid": legacy_plan.id}
            )
            db.session.commit()

            # SQLite kann weder eine NOT-NULL-Bedingung noch einen
            # zusammengesetzten UNIQUE-Constraint nachträglich per ALTER
            # TABLE ergänzen - wie schon bei der früheren
            # side_recipe_id-Migration oben wird die Tabelle daher einmalig
            # mit dem kompletten Zielschema neu aufgebaut (Kopie inkl. IDs,
            # damit PlanDaySide-Zeilen weiter auf die richtigen Tage zeigen).
            db.session.execute(text("""
                CREATE TABLE plan_day_new (
                    id INTEGER NOT NULL PRIMARY KEY,
                    plan_id INTEGER NOT NULL,
                    date DATE NOT NULL,
                    excluded BOOLEAN NOT NULL,
                    servings INTEGER NOT NULL,
                    main_recipe_id INTEGER,
                    cooked BOOLEAN NOT NULL DEFAULT 0,
                    FOREIGN KEY(plan_id) REFERENCES plan (id),
                    FOREIGN KEY(main_recipe_id) REFERENCES recipe (id),
                    UNIQUE(plan_id, date)
                )
            """))
            db.session.execute(text("""
                INSERT INTO plan_day_new (id, plan_id, date, excluded, servings, main_recipe_id, cooked)
                SELECT id, plan_id, date, excluded, servings, main_recipe_id, cooked FROM plan_day
            """))
            db.session.execute(text("DROP TABLE plan_day"))
            db.session.execute(text("ALTER TABLE plan_day_new RENAME TO plan_day"))
            db.session.commit()

    existing_extra_item_columns = {
        row[1] for row in db.session.execute(text("PRAGMA table_info(extra_shopping_item)"))
    }
    if 'plan_id' not in existing_extra_item_columns:
        legacy_plan = seeded_plans_by_username.get("Jonas") or Plan.query.first()
        if legacy_plan is not None:
            db.session.execute(text("ALTER TABLE extra_shopping_item ADD COLUMN plan_id INTEGER"))
            db.session.execute(
                text("UPDATE extra_shopping_item SET plan_id = :pid WHERE plan_id IS NULL"), {"pid": legacy_plan.id}
            )
            db.session.commit()

    # --- Rezepte/Kategorien/Zutaten-Gleichsetzung/Nährwerte/Einheiten:
    # ebenfalls an EINEN Plan gebunden statt (wie bisher) global geteilt -
    # jeder Plan pflegt sein eigenes Kochbuch und seine eigenen
    # Einstellungen (siehe models.py: Plan-Docstring).
    #
    # _add_plan_id_column() ist ein kleiner, nur hier gebrauchter Helfer für
    # Tabellen OHNE mit plan_id kollidierenden Alt-Constraint (recipe/
    # app_settings hatten vorher keine unique-Bedingung, die einen neuen
    # zusammengesetzten Index behindern würde) - Spalte ergänzen,
    # bestehende Zeilen dem Legacy-Plan zuordnen, optional ein eigenständiger
    # "CREATE UNIQUE INDEX" (SQLite erlaubt zwar kein nachträgliches ALTER
    # TABLE ... ADD CONSTRAINT, wohl aber einen unabhängig erzeugten
    # Unique-Index mit derselben Wirkung, ganz ohne Tabellen-Kopie).
    def _add_plan_id_column(table, column, unique_index_sql=None):
        existing_columns = {row[1] for row in db.session.execute(text(f"PRAGMA table_info({table})"))}
        if column in existing_columns:
            return
        legacy_plan = seeded_plans_by_username.get("Jonas") or Plan.query.first()
        if legacy_plan is None:
            return
        db.session.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} INTEGER"))
        db.session.execute(
            text(f"UPDATE {table} SET {column} = :pid WHERE {column} IS NULL"), {"pid": legacy_plan.id}
        )
        db.session.commit()
        if unique_index_sql:
            db.session.execute(text(unique_index_sql))
            db.session.commit()

    _add_plan_id_column("recipe", "owner_plan_id")
    _add_plan_id_column(
        "app_settings", "plan_id",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_app_settings_plan_id ON app_settings (plan_id)"
    )

    # category/ingredient_alias/ingredient_nutrition hatten VORHER je ein
    # einzelnes globales UNIQUE auf genau die Spalte, die jetzt nur noch
    # zusammen mit plan_id eindeutig sein soll (name/raw_name/
    # canonical_name) - das alte, in der Tabelle selbst fest verdrahtete
    # Constraint ließe sich mit dem einfachen ADD-COLUMN+INDEX-Trick oben
    # NICHT los werden (ein zweiter, neuer Index ändert nichts am
    # weiterhin bestehenden alten). Wie schon bei der früheren
    # side_recipe_id-/plan_id-Migration für plan_day wird die Tabelle
    # daher jeweils einmalig mit dem kompletten Zielschema (inkl. IDs, an
    # denen z.B. recipe.category_id weiterhin hängt) neu aufgebaut.
    def _add_plan_id_with_rebuild(table, create_new_table_sql, copy_columns):
        existing_columns = {row[1] for row in db.session.execute(text(f"PRAGMA table_info({table})"))}
        if 'plan_id' in existing_columns:
            return
        legacy_plan = seeded_plans_by_username.get("Jonas") or Plan.query.first()
        if legacy_plan is None:
            return
        db.session.execute(text(f"ALTER TABLE {table} ADD COLUMN plan_id INTEGER"))
        db.session.execute(text(f"UPDATE {table} SET plan_id = :pid WHERE plan_id IS NULL"), {"pid": legacy_plan.id})
        db.session.commit()

        db.session.execute(text(create_new_table_sql))
        db.session.execute(text(f"INSERT INTO {table}_new ({copy_columns}) SELECT {copy_columns} FROM {table}"))
        db.session.execute(text(f"DROP TABLE {table}"))
        db.session.execute(text(f"ALTER TABLE {table}_new RENAME TO {table}"))
        db.session.commit()

    _add_plan_id_with_rebuild(
        "category",
        """
        CREATE TABLE category_new (
            id INTEGER NOT NULL PRIMARY KEY,
            plan_id INTEGER NOT NULL,
            name VARCHAR(50) NOT NULL,
            FOREIGN KEY(plan_id) REFERENCES plan (id),
            UNIQUE(plan_id, name)
        )
        """,
        "id, plan_id, name",
    )
    _add_plan_id_with_rebuild(
        "ingredient_alias",
        """
        CREATE TABLE ingredient_alias_new (
            id INTEGER NOT NULL PRIMARY KEY,
            plan_id INTEGER NOT NULL,
            raw_name VARCHAR(100) NOT NULL,
            canonical_name VARCHAR(100) NOT NULL,
            FOREIGN KEY(plan_id) REFERENCES plan (id),
            UNIQUE(plan_id, raw_name)
        )
        """,
        "id, plan_id, raw_name, canonical_name",
    )
    _add_plan_id_with_rebuild(
        "ingredient_nutrition",
        """
        CREATE TABLE ingredient_nutrition_new (
            id INTEGER NOT NULL PRIMARY KEY,
            plan_id INTEGER NOT NULL,
            canonical_name VARCHAR(100) NOT NULL,
            reference_amount FLOAT NOT NULL,
            reference_unit VARCHAR(20) NOT NULL,
            protein FLOAT,
            carbs FLOAT,
            fat FLOAT,
            FOREIGN KEY(plan_id) REFERENCES plan (id),
            UNIQUE(plan_id, canonical_name)
        )
        """,
        "id, plan_id, canonical_name, reference_amount, reference_unit, protein, carbs, fat",
    )

    # IngredientNutrition.calories entfernt: Kalorien sind aus Eiweiß/
    # Kohlenhydraten/Fett errechenbar (siehe services/nutrition.py:
    # compute_calories()) und wären als eigens gepflegter Wert nur
    # redundant. Anders als bei plan_day/side_recipe_id (siehe oben) ist
    # calories hier KEIN Fremdschlüssel - ein direktes DROP COLUMN
    # funktioniert deshalb ohne den dortigen Tabellen-Neuaufbau-Umweg.
    existing_ingredient_nutrition_columns = {
        row[1] for row in db.session.execute(text("PRAGMA table_info(ingredient_nutrition)"))
    }
    if 'calories' in existing_ingredient_nutrition_columns:
        db.session.execute(text("ALTER TABLE ingredient_nutrition DROP COLUMN calories"))
        db.session.commit()

    # Ein sinnvoller Grundstock an Kategorien für JEDEN Plan, der noch
    # keine einzige eigene hat, damit ein neuer Plan nicht mit einer
    # leeren Kategorie-Liste (und damit unbenutzbarer automatischer
    # Planung) startet - betrifft sowohl einen komplett frischen
    # Erststart als auch, seit Kategorien plan-gebunden sind, jeden neu
    # angelegten Plan ohne eigene Kategorien (z.B. Elos beim Seed weiter
    # oben mit angelegter, bis dahin aber leerer Plan). Eigene, später
    # hinzugefügte oder umbenannte Kategorien werden dadurch nie
    # überschrieben oder erneut angelegt - der Check ist pro Plan.
    default_categories = ["Fleisch", "Fisch", "Vegetarisch", "Vegan", "Nudeln/Pasta", "Suppe/Eintopf", "Schnelle Küche"]
    for plan in Plan.query.all():
        if not Category.query.filter_by(plan_id=plan.id).first():
            for cat_name in default_categories:
                db.session.add(Category(plan_id=plan.id, name=cat_name))
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


@app.before_request
def require_login():
    """Schützt global JEDE Route außer der Login-Seite selbst und
    statischen Dateien (CSS/JS/Bilder) - ein einzelner Gate-Punkt statt
    eines @login_required-Decorators an jeder der bestehenden Routen
    (siehe services/auth.py: login_required() für die Decorator-Variante,
    die aktuell nirgends im Routing eingesetzt wird), damit keine Route
    versehentlich ungeschützt bleibt.

    request.endpoint ist None für nicht auflösbare Pfade (z.B. ein
    Tippfehler in der URL) - die werden hier bewusst durchgelassen, damit
    Flask seine normale 404-Antwort liefert, statt stattdessen fälschlich
    auf /login umzuleiten."""
    if request.endpoint is None or request.endpoint in ('auth.login', 'static'):
        return None
    if current_user() is None:
        return redirect(url_for('auth.login', next=request.path))
    return None


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
def inject_current_user_and_plans():
    """Stellt allen Templates den eingeloggten Nutzer, seinen aktiven Plan
    sowie die Liste ALLER Pläne zur Verfügung, auf die er Zugriff hat
    (eigener + eingeladene, siehe models.py: PlanMembership) - genutzt von
    templates/base.html für den Nutzer-/Plan-Abschnitt in der
    Seitenleiste (Name, Abmelden, Plan-Wechsel/Stern). Gesternter Plan
    zuerst, sonst alphabetisch.

    Auf der Login-Seite selbst (kein eingeloggter Nutzer) bleiben alle drei
    Werte leer/None - das Template dort erweitert base.html ohnehin nicht,
    braucht sie also gar nicht."""
    user = current_user()
    if user is None:
        return {'nav_current_user': None, 'nav_current_plan': None, 'nav_user_plans': []}

    return {
        'nav_current_user': user,
        'nav_current_plan': current_plan(),
        'nav_user_plans': user_plan_memberships(user),
    }


@app.context_processor
def inject_shopping_categories():
    """Stellt allen Templates die feste Einkaufslisten-Kategorie-Reihenfolge
    zur Verfügung (siehe services/shopping.py) - gebraucht sowohl von den
    Kategorie-Dropdowns beim Zutaten-Eintragen (recipe_form.html,
    recipe_edit_list.html) als auch, über window.SHOPPING_CATEGORIES in
    base.html, von der clientseitigen Sortierung/Gruppierung der
    Einkaufsliste (static/plan.js). pantry_categories (window.PANTRY_
    CATEGORIES) markiert zusätzlich, welche dieser Kategorien NICHT
    automatisch auf die Einkaufsliste sollen, sondern auf die separate
    Vorrat-Liste (siehe static/plan-shopping.js: rebuildShoppingList)."""
    return {
        'shopping_categories': SHOPPING_CATEGORIES,
        'shopping_uncategorized': UNCATEGORIZED,
        'pantry_categories': sorted(PANTRY_CATEGORIES),
    }


@app.context_processor
def inject_ingredient_aliases():
    """Stellt allen Templates die für den AKTIVEN Plan gepflegten
    Zutaten-Alias-Zuordnungen zur Verfügung (siehe
    services/ingredient_aliases.py) - genutzt wird das aktuell nur von
    recipe_form.html (window.INGREDIENT_ALIASES, siehe
    static/ingredient_alias_hint.js), global als Context Processor aber
    genauso einfach wie inject_shopping_categories() oben gehalten statt
    die Abfrage in jeder einzelnen Route zu wiederholen.

    Läuft für JEDEN Seitenaufruf, auch die Login-Seite (kein eingeloggter
    Nutzer, current_plan() also None) - liefert dann einfach ein leeres
    Dict, statt mit einem Fehler abzubrechen."""
    plan = current_plan()
    return {'ingredient_aliases': get_all_aliases(plan.id) if plan else {}}


@app.context_processor
def inject_ingredient_nutrition():
    """Stellt allen Templates die für den AKTIVEN Plan gepflegten
    Nährwert-Referenzen je Alias-Zielzutat zur Verfügung (siehe
    services/nutrition.py) - genutzt von recipe_form.html
    (window.INGREDIENT_NUTRITION, siehe static/ingredient_alias_hint.js),
    analog zu inject_ingredient_aliases() oben (inkl. desselben
    Login-Seiten-Sonderfalls)."""
    plan = current_plan()
    return {'ingredient_nutrition': get_all_nutrition_entries(plan.id) if plan else {}}


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
