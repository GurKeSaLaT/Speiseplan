"""Database migrations, run once on every app startup (see app.py:
`with app.app_context(): init_db()`).

This project deliberately has no migration framework (like Alembic/
Flask-Migrate) - the app is too small and changes too infrequent for
that. Instead, init_db() checks via PRAGMA table_info on EVERY startup
which columns/tables already exist, and adds/rebuilds any that are
missing once. Every migration step is thereby idempotent: running it
again on an already up to date database does nothing more.

Broken into one named function per logical migration step (below),
called in sequence from init_db() at the bottom of this file - same SQL/
logic as before, just organized instead of one long function body. Several
of the later steps need to know the "legacy plan" (the plan that inherits
all pre-existing, not-yet-plan-scoped data) - _seed_demo_accounts() at the
top returns seeded_plans_by_username, threaded through as a parameter to
every step that needs it.
"""

from sqlalchemy import text

from models import db, Plan, PlanMembership, RecipeSeason, PlanDaySide, User
from services.auth import hash_password
from services.plans import seed_default_categories
from services.seasons import SEASON_PRESETS
from services.units import renormalize_existing_ingredients


def _legacy_plan(seeded_plans_by_username):
    """The plan that inherits all pre-existing, not-yet-plan-scoped data:
    Nutzer1's freshly seeded plan on a brand new database (see
    _seed_demo_accounts()), or otherwise the oldest existing plan on a
    database that already had data before plans existed at all."""
    return seeded_plans_by_username.get("Nutzer1") or Plan.query.first()


def _rebuild_user_table_for_email_login():
    """user.username -> user.name (no longer a login field, purely a
    display name, from now on NOT unique) + new, unique user.email column
    (login now goes through email, see routes/auth.py: login()). The old
    inline UNIQUE on username (from the original CREATE TABLE) can't be
    removed via ALTER TABLE - as with the later category/ingredient_alias
    migrations, this requires a one-time table rebuild. Placeholder email
    for each existing account follows the pattern <lowercase-name>@
    example.com (e.g. "Nutzer1" -> nutzer1@example.com) - derived
    automatically from the previous username, no special handling of
    individual names needed; logging in with these placeholders is
    explicitly allowed in test operation.
    """
    existing_user_columns = {row[1] for row in db.session.execute(text("PRAGMA table_info(user)"))}
    if 'email' in existing_user_columns:
        return
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


def _migrate_user_language_column():
    """user.language: didn't exist in an earlier version - add the missing
    column. The SQLite default ('en') applies automatically to all
    existing accounts too (see models/user.py: User.language). Must run
    here, immediately after _rebuild_user_table_for_email_login() gives
    the user table its final shape and BEFORE any ORM-level User.query
    call (e.g. the account-seeding check in _seed_demo_accounts() below) -
    SQLAlchemy includes every mapped column, including this new one, in
    every User query, so it would fail with "no such column: user.
    language" if this migration ran any later."""
    existing_user_columns = {row[1] for row in db.session.execute(text("PRAGMA table_info(user)"))}
    if 'language' not in existing_user_columns:
        db.session.execute(text("ALTER TABLE user ADD COLUMN language VARCHAR(5) NOT NULL DEFAULT 'en'"))
        db.session.commit()


def _migrate_recipe_columns():
    """Adds every recipe column that didn't exist in earlier versions of
    the app (is_side_dish, servings, is_favorite, source_url,
    instructions, nutrition_override, updated_at) - one ALTER TABLE per
    missing column, each committed separately."""
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


def _migrate_ingredient_category_column():
    """Shopping-list category of an ingredient (see services/shopping.py) -
    only added with the grouped/sorted shopping list. Existing ingredients
    stay NULL (land in the shopping list's catch-all "miscellaneous" group
    for now, until the respective recipe is saved again) - an automatic
    assignment isn't reliably possible without user input."""
    existing_ingredient_columns = {row[1] for row in db.session.execute(text("PRAGMA table_info(ingredient)"))}
    if 'category' not in existing_ingredient_columns:
        db.session.execute(text("ALTER TABLE ingredient ADD COLUMN category VARCHAR(50)"))
        db.session.commit()


def _migrate_recipe_season_table():
    """Column RESTRUCTURING rather than a mere addition: earlier versions
    had a single season text column directly on Recipe; that was later
    replaced by the separate recipe_season table, which allows MULTIPLE
    date ranges per recipe. Existing values are transferred once into the
    new table via SEASON_PRESETS (season name -> date-range tuple), then
    the old column is dropped."""
    existing_columns = {row[1] for row in db.session.execute(text("PRAGMA table_info(recipe)"))}
    if 'season' not in existing_columns:
        return
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


def _migrate_plan_day_side_table():
    """Any number of side dishes per day instead of exactly one: earlier
    versions had a single side_recipe_id column directly on PlanDay; that
    was replaced by the separate PlanDaySide table (see
    models/calendar.py). The new table already exists thanks to
    db.create_all() in init_db() - here only the existing single value (if
    set) is transferred once into a PlanDaySide row, then the old column
    is dropped."""
    existing_plan_day_columns = {row[1] for row in db.session.execute(text("PRAGMA table_info(plan_day)"))}
    if 'side_recipe_id' not in existing_plan_day_columns:
        return
    old_sides = db.session.execute(
        text("SELECT id, side_recipe_id FROM plan_day WHERE side_recipe_id IS NOT NULL")
    ).fetchall()
    for plan_day_id, side_recipe_id in old_sides:
        db.session.add(PlanDaySide(plan_day_id=plan_day_id, recipe_id=side_recipe_id))
    db.session.commit()

    # SQLite refuses a direct ALTER TABLE ... DROP COLUMN for
    # side_recipe_id ("unknown column ... in foreign key definition"),
    # because the column is part of a FOREIGN KEY definition of the table
    # itself - a known SQLite limitation, unlike the season migration
    # above (there the column wasn't a foreign key). Instead, the table is
    # rebuilt following the pattern recommended by the SQLite docs: create
    # a copy without the column, copy the data across (including IDs, so
    # the PlanDaySide rows just created keep pointing to the right days),
    # replace the old table with the new one.
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


def _migrate_plan_day_cooked_columns():
    """"Cooked" checkbox in the recipe detail window (see
    models/calendar.py: PlanDay.cooked/PlanDaySide.cooked) - added only
    later, for both the plan_day and plan_day_side tables."""
    existing_plan_day_columns = {row[1] for row in db.session.execute(text("PRAGMA table_info(plan_day)"))}
    if 'cooked' not in existing_plan_day_columns:
        db.session.execute(text("ALTER TABLE plan_day ADD COLUMN cooked BOOLEAN NOT NULL DEFAULT 0"))
        db.session.commit()

    existing_plan_day_side_columns = {row[1] for row in db.session.execute(text("PRAGMA table_info(plan_day_side)"))}
    if 'cooked' not in existing_plan_day_side_columns:
        db.session.execute(text("ALTER TABLE plan_day_side ADD COLUMN cooked BOOLEAN NOT NULL DEFAULT 0"))
        db.session.commit()


def _seed_demo_accounts():
    """--- User management: login + own/shared weekly plans ---
    First start (not a single user exists yet): creates two generic demo
    accounts (see models/user.py: User) so the app is directly usable
    after a fresh clone without the versioned instance/speiseplan.db (see
    README.md: Setup) - real registration normally goes through
    routes/auth.py: register(). Each one immediately gets their own plan
    (see models/plan.py: Plan/PlanMembership); ONLY Nutzer1's own plan
    gets starred right away - it becomes the "legacy_plan" used by later
    migration steps (see _legacy_plan()), to which the entire prior
    planning history is assigned, and Nutzer2 gets THEIR star there too
    (not on their own, empty plan) - this way every user consistently has
    exactly one starred plan, and both end up on the same, already
    existing plan after their very first login.

    Returns seeded_plans_by_username ({} on an already-seeded database),
    passed on to every later migration step that needs to know the legacy
    plan (see _legacy_plan())."""
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
    return seeded_plans_by_username


def _migrate_plan_membership_overview_column():
    """show_in_week_overview on PlanMembership: didn't exist in an earlier
    version - add the missing column. The SQLite default (1) applies
    automatically to all already-existing memberships too (see
    models/plan.py: PlanMembership.show_in_week_overview)."""
    existing_plan_membership_columns = {
        row[1] for row in db.session.execute(text("PRAGMA table_info(plan_membership)"))
    }
    if 'show_in_week_overview' not in existing_plan_membership_columns:
        db.session.execute(text("ALTER TABLE plan_membership ADD COLUMN show_in_week_overview BOOLEAN NOT NULL DEFAULT 1"))
        db.session.commit()


def _migrate_plan_day_plan_scoping(seeded_plans_by_username):
    """plan_id on PlanDay: didn't exist in earlier versions of the app
    (the calendar was global, a single plan shared by everyone) - if the
    column is missing, it's added and ALL existing rows (the entire prior
    planning history) are assigned to Nutzer1's newly created plan;
    Nutzer2 is additionally entered (starred) as a member of this plan -
    this way, after this one-time migration, BOTH see exactly the same,
    already existing plan, without anyone having to manually invite the
    other."""
    existing_plan_day_columns = {row[1] for row in db.session.execute(text("PRAGMA table_info(plan_day)"))}
    if 'plan_id' in existing_plan_day_columns:
        return
    legacy_plan = _legacy_plan(seeded_plans_by_username)
    if legacy_plan is None:
        return

    second_user = User.query.filter_by(name="Nutzer2").first()
    if second_user is not None and not PlanMembership.query.filter_by(plan_id=legacy_plan.id, user_id=second_user.id).first():
        db.session.add(PlanMembership(plan_id=legacy_plan.id, user_id=second_user.id, is_starred=True))
        db.session.commit()

    db.session.execute(text("ALTER TABLE plan_day ADD COLUMN plan_id INTEGER"))
    db.session.execute(
        text("UPDATE plan_day SET plan_id = :pid WHERE plan_id IS NULL"), {"pid": legacy_plan.id}
    )
    db.session.commit()

    # SQLite can neither add a NOT NULL constraint nor a composite UNIQUE
    # constraint retroactively via ALTER TABLE - as with the earlier
    # side_recipe_id migration above, the table is therefore rebuilt once
    # with the complete target schema (copy including IDs, so PlanDaySide
    # rows keep pointing to the right days).
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


def _migrate_extra_shopping_item_plan_scoping(seeded_plans_by_username):
    """plan_id on ExtraShoppingItem, analogous to
    _migrate_plan_day_plan_scoping() above (all pre-existing rows get
    assigned to the legacy plan), but without the accompanying table
    rebuild - extra_shopping_item never had a conflicting old constraint,
    so a plain ALTER TABLE ADD COLUMN is enough here."""
    existing_extra_item_columns = {
        row[1] for row in db.session.execute(text("PRAGMA table_info(extra_shopping_item)"))
    }
    if 'plan_id' in existing_extra_item_columns:
        return
    legacy_plan = _legacy_plan(seeded_plans_by_username)
    if legacy_plan is None:
        return
    db.session.execute(text("ALTER TABLE extra_shopping_item ADD COLUMN plan_id INTEGER"))
    db.session.execute(
        text("UPDATE extra_shopping_item SET plan_id = :pid WHERE plan_id IS NULL"), {"pid": legacy_plan.id}
    )
    db.session.commit()


def _add_plan_id_column(table, column, seeded_plans_by_username, unique_index_sql=None):
    """--- Recipes/categories/ingredient-alias mapping/nutrition/units:
    likewise bound to ONE plan instead of (as before) shared globally -
    each plan maintains its own cookbook and its own settings (see
    models/plan.py: Plan docstring).

    Small helper used for tables WITHOUT an old constraint that would
    collide with plan_id (recipe/app_settings previously had no unique
    condition that would get in the way of a new composite index) - add
    the column, assign existing rows to the legacy plan, optionally a
    standalone "CREATE UNIQUE INDEX" (SQLite doesn't allow a retroactive
    ALTER TABLE ... ADD CONSTRAINT, but does allow an independently
    created unique index with the same effect, without any table copy)."""
    existing_columns = {row[1] for row in db.session.execute(text(f"PRAGMA table_info({table})"))}
    if column in existing_columns:
        return
    legacy_plan = _legacy_plan(seeded_plans_by_username)
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


def _migrate_recipe_and_settings_plan_scoping(seeded_plans_by_username):
    _add_plan_id_column("recipe", "owner_plan_id", seeded_plans_by_username)
    _add_plan_id_column(
        "app_settings", "plan_id", seeded_plans_by_username,
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_app_settings_plan_id ON app_settings (plan_id)"
    )


def _add_plan_id_with_rebuild(table, create_new_table_sql, copy_columns, seeded_plans_by_username):
    """category/ingredient_alias/ingredient_nutrition PREVIOUSLY each had a
    single global UNIQUE on exactly the column that should now only be
    unique together with plan_id (name/raw_name/canonical_name) - the old
    constraint, hard-wired into the table itself, could NOT be gotten rid
    of with the simple ADD-COLUMN+INDEX trick in _add_plan_id_column()
    above (a second, new index changes nothing about the old one, which
    would still remain). As with the earlier side_recipe_id/plan_id
    migration for plan_day, the table is therefore rebuilt once with the
    complete target schema (including IDs, which e.g. recipe.category_id
    still depends on)."""
    existing_columns = {row[1] for row in db.session.execute(text(f"PRAGMA table_info({table})"))}
    if 'plan_id' in existing_columns:
        return
    legacy_plan = _legacy_plan(seeded_plans_by_username)
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


def _migrate_category_alias_nutrition_plan_scoping(seeded_plans_by_username):
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
        seeded_plans_by_username,
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
        seeded_plans_by_username,
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
        seeded_plans_by_username,
    )


def _migrate_drop_ingredient_nutrition_calories():
    """IngredientNutrition.calories removed: calories can be computed from
    protein/carbs/fat (see services/nutrition.py: compute_calories()) and
    would only be redundant as a separately maintained value. Unlike
    plan_day/side_recipe_id (see above), calories is NOT a foreign key
    here - a direct DROP COLUMN therefore works without the table-rebuild
    detour used there."""
    existing_ingredient_nutrition_columns = {
        row[1] for row in db.session.execute(text("PRAGMA table_info(ingredient_nutrition)"))
    }
    if 'calories' in existing_ingredient_nutrition_columns:
        db.session.execute(text("ALTER TABLE ingredient_nutrition DROP COLUMN calories"))
        db.session.commit()


def _seed_default_categories_for_all_plans():
    """A sensible base set of categories for EVERY plan that doesn't yet
    have a single one of its own, so a new plan doesn't start with an
    empty category list (and thus unusable automatic planning) - this
    covers both a completely fresh first start and, since categories
    became plan-bound, every newly created plan without its own
    categories (see services/plans.py: seed_default_categories(), the
    same function is also used by routes/plans.py: create_plan() for
    plans created in the future). Custom categories added or renamed later
    are thereby never overwritten or recreated - the check is per plan."""
    for plan in Plan.query.all():
        seed_default_categories(plan.id)
    db.session.commit()


def init_db():
    """Creates missing tables on app startup (db.create_all() - covers
    e.g. a completely new, empty database or a newly added table like
    plan_day) and migrates existing databases from older app versions to
    the current schema by running each named migration step above in
    sequence. See this module's docstring for the general approach."""
    db.create_all()

    _rebuild_user_table_for_email_login()
    _migrate_user_language_column()
    _migrate_recipe_columns()
    _migrate_ingredient_category_column()
    _migrate_recipe_season_table()
    _migrate_plan_day_side_table()
    _migrate_plan_day_cooked_columns()

    seeded_plans_by_username = _seed_demo_accounts()

    _migrate_plan_membership_overview_column()
    _migrate_plan_day_plan_scoping(seeded_plans_by_username)
    _migrate_extra_shopping_item_plan_scoping(seeded_plans_by_username)
    _migrate_recipe_and_settings_plan_scoping(seeded_plans_by_username)
    _migrate_category_alias_nutrition_plan_scoping(seeded_plans_by_username)
    _migrate_drop_ingredient_nutrition_calories()
    _seed_default_categories_for_all_plans()

    # Bring existing ingredient amounts/units (e.g. "Gramm", "kg", "gr" as
    # plain text from before unit unification) once into their canonical
    # form (see services/units.py). Idempotent like the migration steps
    # above: on an already fully canonical database, calling this again
    # changes nothing further.
    renormalize_existing_ingredients()
