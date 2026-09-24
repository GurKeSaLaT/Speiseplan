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

from models import db, ExtraShoppingItem, Plan, PlanMembership, RecipeSeason, PlanDaySide, User
from services.plans import seed_default_categories
from services.planning import friday_of
from services.seasons import SEASON_PRESETS
from services.units import renormalize_existing_ingredients


def _legacy_plan(seeded_plans_by_username):
    """The plan that inherits all pre-existing, not-yet-plan-scoped data.
    seeded_plans_by_username is always {} now (this app no longer seeds
    any demo accounts of its own, see init_db() below) - kept as a
    parameter purely so the plan-scoping migration steps below don't need
    to change, since they were written for it. In practice this always
    resolves to the oldest existing plan on a database that already had
    data before plans existed at all; on a genuinely fresh, empty database
    there is nothing to migrate and every caller here already bails out
    when this returns None."""
    return seeded_plans_by_username.get("Nutzer1") or Plan.query.first()


def _rebuild_user_table_for_email_login():
    """user.username -> user.name (purely a display name, from now on NOT
    unique) + new, unique user.email column (email became the identity
    key - later still true once identity moved to Authelia, see
    services/auth.py: current_user(), which matches its header against
    exactly this column). The old inline UNIQUE on username (from the
    original CREATE TABLE) can't be removed via ALTER TABLE - as with the
    later category/ingredient_alias migrations, this requires a one-time
    table rebuild. Placeholder email for each existing account follows the
    pattern <lowercase-name>@example.com (e.g. "Nutzer1" ->
    nutzer1@example.com) - derived automatically from the previous
    username, no special handling of individual names needed.
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


def _migrate_ingredient_pantry_flag():
    """Adds Ingredient.is_pantry (see services/shopping.py module
    docstring) - replaces the previous derivation of "is this a pantry
    item" from the ingredient's shopping category (the now-removed
    PANTRY_CATEGORIES = {"Gewürze", "Vorratsschrank", "Verbrauchsartikel"})
    with an explicit per-ingredient checkbox. Existing rows are backfilled
    ONCE from exactly those three categories - this must run BEFORE
    _migrate_remove_pantry_shopping_categories() below renames two of them
    away, or the backfill would no longer find them. Only runs the
    backfill the one time the column is actually created, so a user who
    later unchecks the box for a specific spice doesn't get overridden
    again on the next app start."""
    existing_ingredient_columns = {row[1] for row in db.session.execute(text("PRAGMA table_info(ingredient)"))}
    if 'is_pantry' not in existing_ingredient_columns:
        db.session.execute(text("ALTER TABLE ingredient ADD COLUMN is_pantry BOOLEAN NOT NULL DEFAULT 0"))
        db.session.execute(text(
            "UPDATE ingredient SET is_pantry = 1 "
            "WHERE category IN ('Gewürze', 'Vorratsschrank', 'Verbrauchsartikel')"
        ))
        db.session.commit()


def _migrate_remove_pantry_shopping_categories():
    """"Vorratsschrank" and "Verbrauchsartikel" were removed from
    services/shopping.py: SHOPPING_CATEGORIES once "pantry item" became
    its own checkbox (see _migrate_ingredient_pantry_flag() above, which
    must run first) instead of being implied by the category. Existing
    ingredient rows still carrying either string in their free-text
    category column are moved to "Konserven" - the closest remaining
    shelf-stable-goods category - so they don't silently fall into the
    "Sonstiges" catch-all; their is_pantry flag already preserves that
    they're pantry items regardless of this reassignment. Naturally
    idempotent (no rows left to match after the first run), so unlike the
    ALTER TABLE steps above this doesn't need a one-time guard."""
    db.session.execute(text(
        "UPDATE ingredient SET category = 'Konserven' WHERE category IN ('Vorratsschrank', 'Verbrauchsartikel')"
    ))
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


def _migrate_drop_user_password_hash_column():
    """user.password_hash removed: authentication no longer happens in
    this app at all (see services/auth.py module docstring) - Authelia,
    in front of the reverse proxy, owns the password entirely, and this
    app never sees or checks one anymore. Not a foreign key and not part
    of any constraint, so a direct DROP COLUMN works without the
    table-rebuild detour used elsewhere in this file (analogous to
    _migrate_drop_ingredient_nutrition_calories() below)."""
    existing_user_columns = {row[1] for row in db.session.execute(text("PRAGMA table_info(user)"))}
    if 'password_hash' in existing_user_columns:
        db.session.execute(text("ALTER TABLE user DROP COLUMN password_hash"))
        db.session.commit()


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


def _migrate_extra_shopping_item_week_start_to_friday():
    """The calendar week now runs Friday-Thursday instead of Monday-
    Sunday (see services/planning.py: friday_of()) - ExtraShoppingItem.
    week_start (the only place a "week start" is actually STORED, see
    the model docstring) needs re-anchoring to match, or an item added
    under the old convention would silently stop showing up on the week
    it was meant for (routes/plan/pages.py: week_view() looks it up by
    exact week_start match against the now-Friday-based normalized date).

    friday_of() applied to an OLD week_start (always a Monday under the
    previous convention) lands on the Friday 3 days earlier - the new
    week that shares the most days (Mon-Thu, 4 of 7) with the old
    Monday-Sunday week, the most reasonable single choice given
    ExtraShoppingItem has no specific day of its own to disambiguate by.
    Naturally idempotent: friday_of() applied to an already-Friday
    week_start returns it unchanged, so this is safe to run on every
    startup, not just once."""
    changed = False
    for item in ExtraShoppingItem.query.all():
        new_week_start = friday_of(item.week_start)
        if new_week_start != item.week_start:
            item.week_start = new_week_start
            changed = True
    if changed:
        db.session.commit()


def _migrate_ensure_starred_membership():
    """Every user needs exactly one starred plan to fall back to
    (services/auth.py: default_plan_id()/current_plan()) - without one,
    default_plan_id() returns None, which e.g. showed up as an empty
    category dropdown when such a user tried to create a recipe without
    an explicit ?plan_id= in the URL. routes/sharing.py: invite_member()
    used to unconditionally create a new membership as NOT starred, even
    for an existing user with zero memberships of their own - fixed there
    now (mirrors the is_first check in services/plans.py: create_plan()/
    accept_pending_invites()), but this repairs any membership that
    already ended up in that broken state before the fix. For each
    affected user, stars the plan they themselves own if they have one,
    otherwise their first (lowest id) membership. Naturally idempotent:
    a user who already has a starred membership is left untouched."""
    starred_user_ids = {
        row[0] for row in db.session.execute(text("SELECT DISTINCT user_id FROM plan_membership WHERE is_starred = 1"))
    }
    all_user_ids = {row[0] for row in db.session.execute(text("SELECT DISTINCT user_id FROM plan_membership"))}
    changed = False
    for user_id in all_user_ids - starred_user_ids:
        own_membership = (
            db.session.query(PlanMembership)
            .join(Plan, Plan.id == PlanMembership.plan_id)
            .filter(PlanMembership.user_id == user_id, Plan.owner_user_id == user_id)
            .first()
        )
        membership = own_membership or (
            PlanMembership.query.filter_by(user_id=user_id).order_by(PlanMembership.id).first()
        )
        if membership:
            membership.is_starred = True
            changed = True
    if changed:
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
    _migrate_drop_user_password_hash_column()
    _migrate_recipe_columns()
    _migrate_ingredient_category_column()
    _migrate_ingredient_pantry_flag()
    _migrate_remove_pantry_shopping_categories()
    _migrate_recipe_season_table()
    _migrate_plan_day_side_table()
    _migrate_plan_day_cooked_columns()

    # No demo accounts to seed anymore (see services/auth.py module
    # docstring: identity now comes from Authelia, auto-provisioned on
    # first sight by current_user()) - {} makes _legacy_plan() below fall
    # straight back to "the oldest existing plan", which is exactly what
    # every already-deployed database (with real, pre-existing data) still
    # needs for the plan-scoping migrations that follow.
    seeded_plans_by_username = {}

    _migrate_plan_membership_overview_column()
    _migrate_plan_day_plan_scoping(seeded_plans_by_username)
    _migrate_extra_shopping_item_plan_scoping(seeded_plans_by_username)
    _migrate_recipe_and_settings_plan_scoping(seeded_plans_by_username)
    _migrate_category_alias_nutrition_plan_scoping(seeded_plans_by_username)
    _migrate_drop_ingredient_nutrition_calories()
    _seed_default_categories_for_all_plans()
    _migrate_ensure_starred_membership()
    _migrate_extra_shopping_item_week_start_to_friday()

    # Bring existing ingredient amounts/units (e.g. "Gramm", "kg", "gr" as
    # plain text from before unit unification) once into their canonical
    # form (see services/units.py). Idempotent like the migration steps
    # above: on an already fully canonical database, calling this again
    # changes nothing further.
    renormalize_existing_ingredients()
