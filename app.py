"""Entry point of the Speiseplan app: creates the Flask app, connects it
to the database, registers the four blueprints (the actual routes live in
routes/*.py resp. the routes/plan/ package) and, on startup, takes care of
database migrations for fields that didn't exist in earlier versions of
the app.

This file is deliberately kept lean: it no longer contains a single route
itself (those all live in routes/plan/ (three files: pages.py,
day_actions.py, shopping.py - all three share the ONE plan_bp
blueprint), routes/recipes.py, routes/categories.py, routes/manage.py) and
no planning/selection logic (that lives in services/planning.py and
services/seasons.py) - just application setup now.
"""

import os
import secrets

from sqlalchemy import text
from flask import Flask, has_request_context, redirect, request, session, url_for
from flask_babel import Babel
from flask_wtf import CSRFProtect

from models import db, Plan, PlanMembership, RecipeSeason, PlanDaySide, User
from services.auth import current_plan, current_user, hash_password, user_plan_memberships
from services.ingredient_aliases import get_all_aliases
from services.nutrition import get_all_nutrition_entries
from services.plans import seed_default_categories
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
from routes.plans import plans_bp
from routes.account import account_bp

app = Flask(__name__)
# The SQLite file lives in Flask's default "instance" folder
# (instance/speiseplan.db), which is mounted as a volume during
# deployment/Docker operation so the database survives container
# restarts/rebuilds. Overridable via DATABASE_URL (analogous to SECRET_KEY
# below) - used only by tests/conftest.py, so tests run against their own,
# temporary SQLite file instead of instance/speiseplan.db (there's no app
# factory pattern; the connection is set up immediately below at module
# import time).
app.config['SQLALCHEMY_DATABASE_URI'] = (
    os.environ.get('DATABASE_URL') or 'sqlite:///' + os.path.join(app.instance_path, 'speiseplan.db')
)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
# How long a session stays valid without a fresh login (see
# routes/auth.py: SESSION_LIFETIME comment).
app.config['PERMANENT_SESSION_LIFETIME'] = SESSION_LIFETIME

os.makedirs(app.instance_path, exist_ok=True)
db.init_app(app)


def load_or_create_secret_key():
    """Returns the secret key Flask uses to sign sessions and CSRF tokens
    (see CSRFProtect below - Flask-WTF stores the CSRF token server-side in
    the signed session cookie, WITHOUT the app needing its own login/
    session management for that).

    Can be fixed via the SECRET_KEY environment variable (useful if
    several container instances need the same key); if it's not set, a
    random key is generated ONCE and stored in instance/secret_key - in
    the same, persistently mounted folder as the database, so the key
    (and thus the validity of issued CSRF tokens/sessions) survives a
    container restart. A key freshly rolled on every restart would
    otherwise invalidate every form currently open in the browser.
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
# Automatically protects all POST/PUT/PATCH/DELETE routes against
# cross-site request forgery: from now on, every write request requires a
# form field resp. an X-CSRFToken header carrying a valid token that
# matches the session (see csrf_token() in the templates and
# window.CSRF_TOKEN in base.html for the fetch() calls in plan.js) -
# without this, any other website open in the same browser could trigger
# write actions (deleting a recipe, etc.) unnoticed.
CSRFProtect(app)


def get_locale():
    """Resolves the active UI language for this request (Flask-Babel calls
    this once per request). Logged-in users get their saved preference
    (User.language, changeable on /manage/account, see
    services/accounts.py: update_profile()); anonymous requests (login/
    register) fall back to the browser's Accept-Language header, defaulting
    to English whenever it's absent or doesn't match a supported language -
    English is this app's default language.

    has_request_context() guard: a lazy_gettext() string (used throughout
    services/*.py, see e.g. services/accounts.py) can get resolved outside
    any request - most notably in tests that call a service function
    directly via app.app_context() without going through the Flask test
    client (see tests/test_services_accounts.py). current_user()/
    request.accept_languages both need an actual request (they read
    session/headers), so outside one this falls straight back to English
    instead of raising."""
    if not has_request_context():
        return 'en'
    user = current_user()
    if user is not None:
        return user.language
    return request.accept_languages.best_match(['de', 'en']) or 'en'


# translations/ holds the German catalog (translations/de/LC_MESSAGES/
# messages.po, compiled to messages.mo) - English needs no catalog at all,
# since the source strings written directly in _('...')/{{ _('...') }}
# calls throughout the app ARE the English text (gettext falls back to
# showing the msgid as-is when no translation is loaded for the active
# locale, which for 'en' is exactly the desired behavior).
Babel(app, default_locale='en', locale_selector=get_locale)

# Each blueprint brings its own URL namespace (e.g. the function week_view
# in plan_bp becomes the endpoint "plan.week_view", as used in url_for()
# calls in the templates/redirects).
app.register_blueprint(auth_bp)
app.register_blueprint(plan_bp)
app.register_blueprint(manage_bp)
app.register_blueprint(recipes_bp)
app.register_blueprint(categories_bp)
app.register_blueprint(settings_bp)
app.register_blueprint(sharing_bp)
app.register_blueprint(plans_bp)
app.register_blueprint(account_bp)


def init_db():
    """Creates missing tables on app startup (db.create_all() - covers
    e.g. a completely new, empty database or a newly added table like
    plan_day) and migrates existing databases from older app versions to
    the current schema.

    This project deliberately has no migration framework (like
    Alembic/Flask-Migrate) - the app is too small and changes too
    infrequent for that. Instead, this code checks via PRAGMA table_info
    on EVERY startup which columns already exist in the recipe table, and
    adds any missing ones once via ALTER TABLE. Every migration step is
    thereby idempotent: running the function again on an already up to
    date database does nothing more.

    The season migration is a special case (column RESTRUCTURING rather
    than a mere addition): earlier versions had a single season text
    column directly on Recipe; that was later replaced by the separate
    recipe_season table, which allows MULTIPLE date ranges per recipe.
    Existing values are transferred once into the new table via
    SEASON_PRESETS (season name -> date-range tuple), then the old column
    is dropped.
    """
    db.create_all()

    # user.username -> user.name (no longer a login field, purely a
    # display name, from now on NOT unique) + new, unique user.email
    # column (login now goes through email, see routes/auth.py: login()).
    # The old inline UNIQUE on username (from the original CREATE TABLE)
    # can't be removed via ALTER TABLE - as with the earlier category/
    # ingredient_alias migrations, this requires a one-time table rebuild.
    # Placeholder email for each existing account follows the pattern
    # <lowercase-name>@example.com (e.g. "Nutzer1" -> nutzer1@example.com) -
    # derived automatically from the previous username, no special
    # handling of individual names needed; logging in with these
    # placeholders is explicitly allowed in test operation.
    existing_user_columns = {row[1] for row in db.session.execute(text("PRAGMA table_info(user)"))}
    if 'email' not in existing_user_columns:
        db.session.execute(text("""
            CREATE TABLE user_new (
                id INTEGER NOT NULL PRIMARY KEY,
                name VARCHAR(50) NOT NULL,
                email VARCHAR(255) NOT NULL,
                password_hash VARCHAR(255) NOT NULL,
                created_at DATETIME,
                UNIQUE(email)
            )
        """))
        db.session.execute(text("""
            INSERT INTO user_new (id, name, email, password_hash, created_at)
            SELECT id, username, LOWER(username) || '@example.com', password_hash, created_at FROM user
        """))
        db.session.execute(text("DROP TABLE user"))
        db.session.execute(text("ALTER TABLE user_new RENAME TO user"))
        db.session.commit()

    # user.language: didn't exist in an earlier version - add the missing
    # column. The SQLite default ('en') applies automatically to all
    # existing accounts too (see models.py: User.language). Must run here,
    # immediately after the user table exists with its final shape and
    # BEFORE any ORM-level User.query call below (e.g. the account-seeding
    # check further down) - SQLAlchemy includes every mapped column,
    # including this new one, in every User query, so it would fail with
    # "no such column: user.language" if this migration ran any later.
    existing_user_columns = {row[1] for row in db.session.execute(text("PRAGMA table_info(user)"))}
    if 'language' not in existing_user_columns:
        db.session.execute(text("ALTER TABLE user ADD COLUMN language VARCHAR(5) NOT NULL DEFAULT 'en'"))
        db.session.commit()

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
        # SQLite refuses "DEFAULT CURRENT_TIMESTAMP" directly in ALTER
        # TABLE ("Cannot add a column with non-constant default") - so the
        # column is created without a default and existing rows are set
        # to the migration timestamp via a separate UPDATE (a sensible
        # starting value for the "recently edited" list in
        # routes/manage.py, even without real history for older recipes).
        db.session.execute(text("ALTER TABLE recipe ADD COLUMN updated_at DATETIME"))
        db.session.execute(text("UPDATE recipe SET updated_at = CURRENT_TIMESTAMP WHERE updated_at IS NULL"))
        db.session.commit()

    # Shopping-list category of an ingredient (see services/shopping.py) -
    # only added with the grouped/sorted shopping list. Existing
    # ingredients stay NULL (land in the shopping list's catch-all
    # "miscellaneous" group for now, until the respective recipe is saved
    # again) - an automatic assignment isn't reliably possible without
    # user input.
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

    # Any number of side dishes per day instead of exactly one: earlier
    # versions had a single side_recipe_id column directly on PlanDay;
    # that was replaced by the separate PlanDaySide table (see models.py).
    # The new table already exists thanks to db.create_all() above - here
    # only the existing single value (if set) is transferred once into a
    # PlanDaySide row, then the old column is dropped.
    existing_plan_day_columns = {row[1] for row in db.session.execute(text("PRAGMA table_info(plan_day)"))}
    if 'side_recipe_id' in existing_plan_day_columns:
        old_sides = db.session.execute(
            text("SELECT id, side_recipe_id FROM plan_day WHERE side_recipe_id IS NOT NULL")
        ).fetchall()
        for plan_day_id, side_recipe_id in old_sides:
            db.session.add(PlanDaySide(plan_day_id=plan_day_id, recipe_id=side_recipe_id))
        db.session.commit()

        # SQLite refuses a direct ALTER TABLE ... DROP COLUMN for
        # side_recipe_id ("unknown column ... in foreign key definition"),
        # because the column is part of a FOREIGN KEY definition of the
        # table itself - a known SQLite limitation, unlike the season
        # migration above (there the column wasn't a foreign key).
        # Instead, the table is rebuilt following the pattern recommended
        # by the SQLite docs: create a copy without the column, copy the
        # data across (including IDs, so the PlanDaySide rows just created
        # keep pointing to the right days), replace the old table with the
        # new one.
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

    # "Cooked" checkbox in the recipe detail window (see models.py:
    # PlanDay.cooked/PlanDaySide.cooked) - added only later,
    # existing_plan_day_columns was already determined above for the
    # side_recipe_id migration.
    existing_plan_day_columns = {row[1] for row in db.session.execute(text("PRAGMA table_info(plan_day)"))}
    if 'cooked' not in existing_plan_day_columns:
        db.session.execute(text("ALTER TABLE plan_day ADD COLUMN cooked BOOLEAN NOT NULL DEFAULT 0"))
        db.session.commit()

    existing_plan_day_side_columns = {row[1] for row in db.session.execute(text("PRAGMA table_info(plan_day_side)"))}
    if 'cooked' not in existing_plan_day_side_columns:
        db.session.execute(text("ALTER TABLE plan_day_side ADD COLUMN cooked BOOLEAN NOT NULL DEFAULT 0"))
        db.session.commit()

    # --- User management: login + own/shared weekly plans ---
    # First start (not a single user exists yet): creates two generic demo
    # accounts (see models.py: User) so the app is directly usable after a
    # fresh clone without the versioned instance/speiseplan.db (see
    # README.md: Setup) - real registration normally goes through
    # routes/auth.py: register(). Each one immediately gets their own plan
    # (see models.py: Plan/PlanMembership); ONLY Nutzer1's own plan gets
    # starred right away - it becomes the "legacy_plan" further below, to
    # which the entire prior planning history is assigned, and Nutzer2
    # gets THEIR star there too (not on their own, empty plan) - this way
    # every user consistently has exactly one starred plan, and both end
    # up on the same, already existing plan after their very first login.
    seeded_plans_by_username = {}
    if not User.query.first():
        for username in ("Nutzer1", "Nutzer2"):
            user = User(name=username, email=f"{username.lower()}@example.com", password_hash=hash_password(username))
            db.session.add(user)
            db.session.flush()
            plan = Plan(name=f"{username}s Plan", owner_user_id=user.id)
            db.session.add(plan)
            db.session.flush()
            db.session.add(PlanMembership(plan_id=plan.id, user_id=user.id, is_starred=(username == "Nutzer1")))
            seeded_plans_by_username[username] = plan
        db.session.commit()

    # show_in_week_overview on PlanMembership: didn't exist in an earlier
    # version - add the missing column. The SQLite default (1) applies
    # automatically to all already-existing memberships too (see
    # models.py: PlanMembership.show_in_week_overview).
    existing_plan_membership_columns = {
        row[1] for row in db.session.execute(text("PRAGMA table_info(plan_membership)"))
    }
    if 'show_in_week_overview' not in existing_plan_membership_columns:
        db.session.execute(text("ALTER TABLE plan_membership ADD COLUMN show_in_week_overview BOOLEAN NOT NULL DEFAULT 1"))
        db.session.commit()

    # plan_id on PlanDay/ExtraShoppingItem: didn't exist in earlier
    # versions of the app (the calendar was global, a single plan shared
    # by everyone) - if the column is missing, it's added and ALL
    # existing rows (the entire prior planning history) are assigned to
    # Nutzer1's newly created plan; Nutzer2 is additionally entered
    # (starred) as a member of this plan - this way, after this one-time
    # migration, BOTH see exactly the same, already existing plan,
    # without anyone having to manually invite the other.
    existing_plan_day_columns = {row[1] for row in db.session.execute(text("PRAGMA table_info(plan_day)"))}
    if 'plan_id' not in existing_plan_day_columns:
        legacy_plan = seeded_plans_by_username.get("Nutzer1") or Plan.query.first()
        if legacy_plan is not None:
            second_user = User.query.filter_by(name="Nutzer2").first()
            if second_user is not None and not PlanMembership.query.filter_by(plan_id=legacy_plan.id, user_id=second_user.id).first():
                db.session.add(PlanMembership(plan_id=legacy_plan.id, user_id=second_user.id, is_starred=True))
                db.session.commit()

            db.session.execute(text("ALTER TABLE plan_day ADD COLUMN plan_id INTEGER"))
            db.session.execute(
                text("UPDATE plan_day SET plan_id = :pid WHERE plan_id IS NULL"), {"pid": legacy_plan.id}
            )
            db.session.commit()

            # SQLite can neither add a NOT NULL constraint nor a composite
            # UNIQUE constraint retroactively via ALTER TABLE - as with the
            # earlier side_recipe_id migration above, the table is
            # therefore rebuilt once with the complete target schema
            # (copy including IDs, so PlanDaySide rows keep pointing to
            # the right days).
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
        legacy_plan = seeded_plans_by_username.get("Nutzer1") or Plan.query.first()
        if legacy_plan is not None:
            db.session.execute(text("ALTER TABLE extra_shopping_item ADD COLUMN plan_id INTEGER"))
            db.session.execute(
                text("UPDATE extra_shopping_item SET plan_id = :pid WHERE plan_id IS NULL"), {"pid": legacy_plan.id}
            )
            db.session.commit()

    # --- Recipes/categories/ingredient-alias mapping/nutrition/units:
    # likewise bound to ONE plan instead of (as before) shared globally -
    # each plan maintains its own cookbook and its own settings (see
    # models.py: Plan docstring).
    #
    # _add_plan_id_column() is a small helper used only here for tables
    # WITHOUT an old constraint that would collide with plan_id (recipe/
    # app_settings previously had no unique condition that would get in
    # the way of a new composite index) - add the column, assign existing
    # rows to the legacy plan, optionally a standalone "CREATE UNIQUE
    # INDEX" (SQLite doesn't allow a retroactive ALTER TABLE ... ADD
    # CONSTRAINT, but does allow an independently created unique index
    # with the same effect, without any table copy).
    def _add_plan_id_column(table, column, unique_index_sql=None):
        existing_columns = {row[1] for row in db.session.execute(text(f"PRAGMA table_info({table})"))}
        if column in existing_columns:
            return
        legacy_plan = seeded_plans_by_username.get("Nutzer1") or Plan.query.first()
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

    # category/ingredient_alias/ingredient_nutrition PREVIOUSLY each had a
    # single global UNIQUE on exactly the column that should now only be
    # unique together with plan_id (name/raw_name/canonical_name) - the
    # old constraint, hard-wired into the table itself, could NOT be gotten
    # rid of with the simple ADD-COLUMN+INDEX trick above (a second, new
    # index changes nothing about the old one, which would still remain).
    # As with the earlier side_recipe_id/plan_id migration for plan_day,
    # the table is therefore rebuilt once with the complete target schema
    # (including IDs, which e.g. recipe.category_id still depends on).
    def _add_plan_id_with_rebuild(table, create_new_table_sql, copy_columns):
        existing_columns = {row[1] for row in db.session.execute(text(f"PRAGMA table_info({table})"))}
        if 'plan_id' in existing_columns:
            return
        legacy_plan = seeded_plans_by_username.get("Nutzer1") or Plan.query.first()
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

    # IngredientNutrition.calories removed: calories can be computed from
    # protein/carbs/fat (see services/nutrition.py: compute_calories())
    # and would only be redundant as a separately maintained value. Unlike
    # plan_day/side_recipe_id (see above), calories is NOT a foreign key
    # here - a direct DROP COLUMN therefore works without the table-rebuild
    # detour used there.
    existing_ingredient_nutrition_columns = {
        row[1] for row in db.session.execute(text("PRAGMA table_info(ingredient_nutrition)"))
    }
    if 'calories' in existing_ingredient_nutrition_columns:
        db.session.execute(text("ALTER TABLE ingredient_nutrition DROP COLUMN calories"))
        db.session.commit()

    # A sensible base set of categories for EVERY plan that doesn't yet
    # have a single one of its own, so a new plan doesn't start with an
    # empty category list (and thus unusable automatic planning) - this
    # covers both a completely fresh first start and, since categories
    # became plan-bound, every newly created plan without its own
    # categories (see services/plans.py: seed_default_categories(), the
    # same function is also used by routes/plans.py: create_plan() for
    # plans created in the future). Custom categories added or renamed
    # later are thereby never overwritten or recreated - the check is
    # per plan.
    for plan in Plan.query.all():
        seed_default_categories(plan.id)
    db.session.commit()

    # Bring existing ingredient amounts/units (e.g. "Gramm", "kg", "gr" as
    # plain text from before unit unification) once into their canonical
    # form (see services/units.py). Idempotent like the migration steps
    # above: on an already fully canonical database, calling this again
    # changes nothing further.
    renormalize_existing_ingredients()


# Migration runs synchronously at module import time, not only on the
# first request - this guarantees the database is up to date before any
# request is handled at all (important e.g. for Gunicorn/Docker operation
# with multiple workers, which could otherwise migrate concurrently).
with app.app_context():
    init_db()


# Endpoints that must stay reachable even entirely WITHOUT plan
# membership (see require_login() below, second gate) - plan.index/
# plan.week_view show the "no plan yet" view in that case instead of the
# normal calendar data (see routes/plan/pages.py: week_view()), BOTH must
# be on the allowlist (index() redirects to week_view() - if only index()
# were listed here, the second redirect would immediately be caught by
# this same gate again, an infinite loop). plans.create is the only way
# to get out of the zero-plan state.
ZERO_PLAN_ALLOWED_ENDPOINTS = {
    'plan.index', 'plan.week_view', 'plans.create', 'auth.logout',
    # Profile management doesn't need a plan - a user without any
    # membership must still be able to manage/delete their own account
    # (routes/account.py).
    'account.account_view', 'account.update_profile_route',
    'account.update_password_route', 'account.delete_account_route',
}


@app.before_request
def require_login():
    """Globally protects EVERY route except the login/registration page
    itself and static files (CSS/JS/images) - a single gate point instead
    of a @login_required decorator on each of the existing routes (see
    services/auth.py: login_required() for the decorator variant, which is
    currently not used anywhere in the routing), so that no route stays
    unprotected by accident.

    request.endpoint is None for paths that can't be resolved (e.g. a
    typo in the URL) - those are deliberately let through here, so Flask
    delivers its normal 404 response instead of wrongly redirecting to
    /login.

    Second gate (since plans were decoupled from accounts, see
    services/plans.py): a logged-in user WITHOUT any plan membership
    (current_plan() is then None) is redirected to the weekly-plan landing
    page, UNLESS the target is already on ZERO_PLAN_ALLOWED_ENDPOINTS -
    the same central-gate philosophy as above, so that none of the
    numerous plan-bound routes (categories/settings/recipes/sharing/
    day actions) has to individually check whether current_plan() even
    exists."""
    if request.endpoint is None or request.endpoint in ('auth.login', 'auth.register', 'static'):
        return None
    if current_user() is None:
        return redirect(url_for('auth.login', next=request.path))
    if current_plan() is None and request.endpoint not in ZERO_PLAN_ALLOWED_ENDPOINTS:
        return redirect(url_for('plan.index'))
    return None


@app.after_request
def set_security_headers(response):
    """Sets a set of basic security headers on EVERY response that Flask
    doesn't send by default (identified via a pentest on 2026-08-28). No
    HSTS, since the app deliberately runs only over HTTP on the home
    network (no TLS certificate present) - an HSTS header without HTTPS
    would be ineffective resp. misleading.

    The Content Security Policy allows 'unsafe-inline' for scripts/styles,
    because the templates consistently use onclick attributes and inline
    <style>/<script> blocks (no nonce/hash-based setup) - but still
    prevents loading code/images from external sources, embedding the page
    in a foreign iframe (frame-ancestors), and submitting forms to
    external targets (form-action).
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
    """Makes the css_version variable available to all templates (see
    templates/base.html: style.css is included with ?v={{ css_version }}).

    Uses the modification time of the style.css file itself as the version
    number: whenever the file changes, this query parameter automatically
    changes too, causing browsers to load the new version instead of
    continuing to use a stale, cached copy - all without manually bumping
    a version number on every CSS change. If the file access fails (e.g.
    because style.css is missing for some reason), 0 is used instead of
    aborting the page with an error.
    """
    css_path = os.path.join(app.static_folder, 'style.css')
    try:
        css_version = int(os.path.getmtime(css_path))
    except OSError:
        css_version = 0
    return {'css_version': css_version}


@app.context_processor
def inject_current_user_and_plans():
    """Makes the logged-in user, their active plan, and the list of ALL
    plans they have access to (own + invited-to, see models.py:
    PlanMembership) available to all templates - used by
    templates/base.html for the user/plan section in the sidebar (name,
    log out, plan switch/star). Starred plan first, otherwise
    alphabetical.

    On the login page itself (no logged-in user), all three values stay
    empty/None - the template there doesn't extend base.html anyway, so it
    doesn't need them at all."""
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
    """Makes the fixed shopping-list category order available to all
    templates (see services/shopping.py) - needed both by the category
    dropdowns when entering ingredients (recipe_form.html,
    recipe_edit_list.html) and, via window.SHOPPING_CATEGORIES in
    base.html, by the client-side sorting/grouping of the shopping list
    (static/plan.js). pantry_categories (window.PANTRY_CATEGORIES)
    additionally marks which of these categories should NOT automatically
    go onto the shopping list, but onto the separate pantry list (see
    static/plan-shopping.js: rebuildShoppingList)."""
    return {
        'shopping_categories': SHOPPING_CATEGORIES,
        'shopping_uncategorized': UNCATEGORIZED,
        'pantry_categories': sorted(PANTRY_CATEGORIES),
    }


@app.context_processor
def inject_ingredient_aliases():
    """Makes the ingredient-alias mappings maintained for the ACTIVE plan
    available to all templates (see services/ingredient_aliases.py) -
    currently used only by recipe_form.html (window.INGREDIENT_ALIASES,
    see static/ingredient_alias_hint.js), but kept as a global context
    processor just as simply as inject_shopping_categories() above instead
    of repeating the query in every single route.

    Runs for EVERY page view, including the login page (no logged-in
    user, so current_plan() is None) - simply returns an empty dict then,
    instead of aborting with an error."""
    plan = current_plan()
    return {'ingredient_aliases': get_all_aliases(plan.id) if plan else {}}


@app.context_processor
def inject_ingredient_nutrition():
    """Makes the nutrition references maintained for the ACTIVE plan, per
    alias target ingredient, available to all templates (see
    services/nutrition.py) - used by recipe_form.html
    (window.INGREDIENT_NUTRITION, see static/ingredient_alias_hint.js),
    analogous to inject_ingredient_aliases() above (including the same
    login-page special case)."""
    plan = current_plan()
    return {'ingredient_nutrition': get_all_nutrition_entries(plan.id) if plan else {}}


if __name__ == '__main__':
    # Only relevant when app.py is run directly (local development resp.
    # CMD in the Dockerfile) - under a real WSGI server (Gunicorn etc.)
    # this block wouldn't run at all.
    #
    # FLASK_DEBUG and PORT are set via the Dockerfile in the Docker
    # deployment (FLASK_DEBUG=0, PORT=80): in the container, the app thus
    # runs without the Werkzeug debugger (which would be a remote-code-
    # execution risk if reachable over the network) and on the standard
    # HTTP port. Locally, with no variables set, debug/autoreload mode
    # stays on and the port stays at 5000 (no root needed, unlike with
    # port 80).
    #
    # host='0.0.0.0' is necessary in the Docker deployment: with Flask's
    # default ('127.0.0.1'), the app would be reachable only from
    # localhost even within the container, i.e. not at all from outside.
    # Overridable for local test runs outside of Docker via the HOST
    # environment variable, e.g. HOST=127.0.0.1, so the local test server
    # is deliberately NOT reachable via the machine's LAN IP, but only
    # from this machine itself.
    debug_mode = os.environ.get('FLASK_DEBUG', '1') == '1'
    port = int(os.environ.get('PORT', 5000))
    host = os.environ.get('HOST', '0.0.0.0')
    app.run(host=host, port=port, debug=debug_mode)
