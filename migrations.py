"""Schema migrations, run by init_db() on every app start.

No migration framework: each step inspects the schema via PRAGMA
table_info and only acts if its change is missing, so every step is
idempotent. SQLite can't drop constrained/foreign-key columns or add
constraints via ALTER TABLE, hence the occasional table rebuild.
"""

import re

from sqlalchemy import text

from models import db, ExtraShoppingItem, Plan, PlanMembership, RecipeSeason, PlanDaySide, User
from services.plans import seed_default_categories
from services.planning import friday_of
from services.seasons import SEASON_PRESETS
from services.units import renormalize_existing_ingredients

# SQLite DDL can't bind identifiers, so the helpers below interpolate
# table/column names into SQL - only ever allow plain snake_case names.
_VALID_IDENTIFIER = re.compile(r'^[a-z_][a-z0-9_]*$')


def _identifier(name):
    if not _VALID_IDENTIFIER.match(name):
        raise ValueError(f"Refusing to build SQL with unsafe identifier: {name!r}")
    return name


def _identifier_list(csv_names):
    for part in csv_names.split(','):
        _identifier(part.strip())
    return csv_names


def _legacy_plan(seeded_plans_by_username):
    """The plan that inherits data from before plans existed: the oldest
    plan (seeded_plans_by_username is always {} now)."""
    return seeded_plans_by_username.get("Nutzer1") or Plan.query.first()


def _rebuild_user_table_for_email_login():
    """username -> name (no longer unique) plus a unique email column, the
    identity key Authelia's header is matched against. Placeholder emails
    are <lowercase-name>@example.com."""
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
    """Must run before any ORM User query - SQLAlchemy selects every mapped
    column, so a missing user.language would break it."""
    existing_user_columns = {row[1] for row in db.session.execute(text("PRAGMA table_info(user)"))}
    if 'language' not in existing_user_columns:
        db.session.execute(text("ALTER TABLE user ADD COLUMN language VARCHAR(5) NOT NULL DEFAULT 'en'"))
        db.session.commit()


def _migrate_recipe_columns():
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
        # SQLite rejects a non-constant DEFAULT in ALTER TABLE, so backfill separately.
        db.session.execute(text("ALTER TABLE recipe ADD COLUMN updated_at DATETIME"))
        db.session.execute(text("UPDATE recipe SET updated_at = CURRENT_TIMESTAMP WHERE updated_at IS NULL"))
        db.session.commit()


def _migrate_ingredient_category_column():
    existing_ingredient_columns = {row[1] for row in db.session.execute(text("PRAGMA table_info(ingredient)"))}
    if 'category' not in existing_ingredient_columns:
        db.session.execute(text("ALTER TABLE ingredient ADD COLUMN category VARCHAR(50)"))
        db.session.commit()


def _migrate_ingredient_pantry_flag():
    """Adds Ingredient.is_pantry, backfilled once from the former pantry
    categories. Must run before _migrate_remove_pantry_shopping_categories()
    renames those categories away; the backfill only runs when the column is
    created, so later manual unchecks stick."""
    existing_ingredient_columns = {row[1] for row in db.session.execute(text("PRAGMA table_info(ingredient)"))}
    if 'is_pantry' not in existing_ingredient_columns:
        db.session.execute(text("ALTER TABLE ingredient ADD COLUMN is_pantry BOOLEAN NOT NULL DEFAULT 0"))
        db.session.execute(text(
            "UPDATE ingredient SET is_pantry = 1 "
            "WHERE category IN ('Gewürze', 'Vorratsschrank', 'Verbrauchsartikel')"
        ))
        db.session.commit()


def _migrate_remove_pantry_shopping_categories():
    """Moves ingredients from the removed pantry categories to "Konserven"."""
    db.session.execute(text(
        "UPDATE ingredient SET category = 'Konserven' WHERE category IN ('Vorratsschrank', 'Verbrauchsartikel')"
    ))
    db.session.commit()


def _migrate_recipe_season_table():
    """Old single recipe.season text column -> recipe_season rows."""
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
    """Old single plan_day.side_recipe_id -> plan_day_side rows."""
    existing_plan_day_columns = {row[1] for row in db.session.execute(text("PRAGMA table_info(plan_day)"))}
    if 'side_recipe_id' not in existing_plan_day_columns:
        return
    old_sides = db.session.execute(
        text("SELECT id, side_recipe_id FROM plan_day WHERE side_recipe_id IS NOT NULL")
    ).fetchall()
    for plan_day_id, side_recipe_id in old_sides:
        db.session.add(PlanDaySide(plan_day_id=plan_day_id, recipe_id=side_recipe_id))
    db.session.commit()

    # side_recipe_id is a foreign key, which SQLite can't DROP COLUMN - rebuild,
    # keeping ids so the new plan_day_side rows still point at the right days.
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
    existing_plan_day_columns = {row[1] for row in db.session.execute(text("PRAGMA table_info(plan_day)"))}
    if 'cooked' not in existing_plan_day_columns:
        db.session.execute(text("ALTER TABLE plan_day ADD COLUMN cooked BOOLEAN NOT NULL DEFAULT 0"))
        db.session.commit()

    existing_plan_day_side_columns = {row[1] for row in db.session.execute(text("PRAGMA table_info(plan_day_side)"))}
    if 'cooked' not in existing_plan_day_side_columns:
        db.session.execute(text("ALTER TABLE plan_day_side ADD COLUMN cooked BOOLEAN NOT NULL DEFAULT 0"))
        db.session.commit()


def _migrate_drop_user_password_hash_column():
    """Passwords are Authelia's job now."""
    existing_user_columns = {row[1] for row in db.session.execute(text("PRAGMA table_info(user)"))}
    if 'password_hash' in existing_user_columns:
        db.session.execute(text("ALTER TABLE user DROP COLUMN password_hash"))
        db.session.commit()


def _migrate_plan_membership_overview_column():
    existing_plan_membership_columns = {
        row[1] for row in db.session.execute(text("PRAGMA table_info(plan_membership)"))
    }
    if 'show_in_week_overview' not in existing_plan_membership_columns:
        db.session.execute(text("ALTER TABLE plan_membership ADD COLUMN show_in_week_overview BOOLEAN NOT NULL DEFAULT 1"))
        db.session.commit()


def _migrate_plan_day_plan_scoping(seeded_plans_by_username):
    """The formerly global calendar becomes the legacy plan's; "Nutzer2" is
    made a starred member of it so both original users keep seeing it."""
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

    # NOT NULL and UNIQUE(plan_id, date) need a rebuild (ids kept for plan_day_side).
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
    """Adds a plan id column assigned to the legacy plan, for tables with no
    conflicting old constraint. A standalone unique index stands in for the
    constraint SQLite can't add retroactively."""
    table, column = _identifier(table), _identifier(column)
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
    """Like _add_plan_id_column(), for tables whose old global UNIQUE must
    become unique per plan - that needs a rebuild (ids kept, other tables
    reference them)."""
    table, copy_columns = _identifier(table), _identifier_list(copy_columns)
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
    """Calories are always computed from protein/carbs/fat now."""
    existing_ingredient_nutrition_columns = {
        row[1] for row in db.session.execute(text("PRAGMA table_info(ingredient_nutrition)"))
    }
    if 'calories' in existing_ingredient_nutrition_columns:
        db.session.execute(text("ALTER TABLE ingredient_nutrition DROP COLUMN calories"))
        db.session.commit()


def _seed_default_categories_for_all_plans():
    """Default categories for every plan that has none yet (never touches
    plans that already have their own)."""
    for plan in Plan.query.all():
        seed_default_categories(plan.id)
    db.session.commit()


def _migrate_extra_shopping_item_week_start_to_friday():
    """Re-anchors stored week starts after the switch from Monday-Sunday to
    Friday-Thursday weeks. An old Monday maps to the Friday before it (the
    new week sharing the most days); already-Friday values are unchanged."""
    changed = False
    for item in ExtraShoppingItem.query.all():
        new_week_start = friday_of(item.week_start)
        if new_week_start != item.week_start:
            item.week_start = new_week_start
            changed = True
    if changed:
        db.session.commit()


def _migrate_ensure_starred_membership():
    """Every user needs one starred plan to fall back to. Repairs users left
    without one by an old invite bug: stars their own plan, else their first
    membership."""
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

    renormalize_existing_ingredients()
