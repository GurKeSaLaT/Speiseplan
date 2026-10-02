"""Tests for migrations.py: _identifier()/_identifier_list() - the
allowlist guard in front of the f-string-built SQL in
_add_plan_id_column()/_add_plan_id_with_rebuild() (see the module-level
comment there for why this exists even though every current call site
only ever passes a hardcoded literal) - plus individual schema steps."""
import pytest

from migrations import _identifier, _identifier_list


def test_identifier_accepts_plain_snake_case_name():
    assert _identifier("owner_plan_id") == "owner_plan_id"


@pytest.mark.parametrize("bad", [
    "table; DROP TABLE user;--",
    "Table",
    "table name",
    "table-name",
    "table.name",
    "",
    "1table",
])
def test_identifier_rejects_anything_not_plain_snake_case(bad):
    with pytest.raises(ValueError):
        _identifier(bad)


def test_identifier_list_accepts_comma_separated_names_with_spaces():
    assert _identifier_list("id, plan_id, name") == "id, plan_id, name"


def test_identifier_list_rejects_if_any_single_name_is_unsafe():
    with pytest.raises(ValueError):
        _identifier_list("id, plan_id, name); DROP TABLE user;--")


def test_shopping_list_check_amount_columns_are_added_to_old_tables(app):
    """Databases created by the first version of ShoppingListCheck have no
    amount/category columns; existing ticks keep amount NULL (whole line)."""
    from sqlalchemy import text

    from migrations import _migrate_shopping_list_check_amount_columns
    from models import Plan, User, db

    with app.app_context():
        user = User(name="Alt", email="alt@test.local")
        db.session.add(user)
        db.session.flush()
        plan = Plan(name="Alt", owner_user_id=user.id)
        db.session.add(plan)
        db.session.commit()

        db.session.execute(text("ALTER TABLE shopping_list_check DROP COLUMN amount"))
        db.session.execute(text("ALTER TABLE shopping_list_check DROP COLUMN category"))
        db.session.execute(text(
            "INSERT INTO shopping_list_check (plan_id, week_start, item_key) VALUES (:plan_id, '2026-06-12', 'item:Mehl|||g')"
        ), {"plan_id": plan.id})
        db.session.commit()

        _migrate_shopping_list_check_amount_columns()
        _migrate_shopping_list_check_amount_columns()  # idempotent

        columns = {row[1] for row in db.session.execute(text("PRAGMA table_info(shopping_list_check)"))}
        assert {"amount", "category"} <= columns
        row = db.session.execute(text("SELECT item_key, amount, category FROM shopping_list_check")).one()
        assert tuple(row) == ("item:Mehl|||g", None, None)
