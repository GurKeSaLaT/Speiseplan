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


# --- follow-up links brought in line with the recipe tree rules (ADR 0001) ---

def _link(app, source_id, follow_up_id):
    """Inserts a RecipeFollowUp row directly (bypassing the form rules);
    returns its id."""
    from models import RecipeFollowUp, db
    with app.app_context():
        link = RecipeFollowUp(recipe_id=source_id, follow_up_recipe_id=follow_up_id)
        db.session.add(link)
        db.session.commit()
        return link.id


def _links(app):
    """Remaining links as sorted (source, follow-up) pairs."""
    from models import RecipeFollowUp
    with app.app_context():
        return sorted((l.recipe_id, l.follow_up_recipe_id) for l in RecipeFollowUp.query)


def _share(app, recipe_id, plan_id):
    from models import RecipePlanLink, db
    with app.app_context():
        db.session.add(RecipePlanLink(recipe_id=recipe_id, plan_id=plan_id))
        db.session.commit()


def _shared_into(app, plan_id):
    from models import RecipePlanLink
    with app.app_context():
        return sorted(l.recipe_id for l in RecipePlanLink.query.filter_by(plan_id=plan_id))


def _migrate_tree_rules(app):
    from migrations import _migrate_follow_up_links_to_tree_rules
    with app.app_context():
        _migrate_follow_up_links_to_tree_rules()


def test_second_source_keeps_only_the_oldest_link(app, make_recipe, caplog):
    braten = make_recipe("Braten")
    huhn = make_recipe("Huhn")
    ragout = make_recipe("Ragout")
    _link(app, huhn, ragout)
    _link(app, braten, ragout)

    _migrate_tree_rules(app)

    assert _links(app) == [(huhn, ragout)]
    assert "Braten" in caplog.text and "Ragout" in caplog.text


def test_link_closing_a_cycle_is_removed_later_one_by_id(app, make_recipe, caplog):
    braten = make_recipe("Braten")
    ragout = make_recipe("Ragout")
    lasagne = make_recipe("Lasagne")
    _link(app, braten, ragout)
    _link(app, ragout, lasagne)
    _link(app, lasagne, braten)

    _migrate_tree_rules(app)

    assert _links(app) == sorted([(braten, ragout), (ragout, lasagne)])
    assert "Lasagne" in caplog.text and "Braten" in caplog.text


def test_self_link_is_removed(app, make_recipe):
    braten = make_recipe("Braten")
    ragout = make_recipe("Ragout")
    _link(app, braten, braten)
    _link(app, braten, ragout)

    _migrate_tree_rules(app)

    assert _links(app) == [(braten, ragout)]


def test_cycle_and_second_source_are_decided_by_link_id(app, make_recipe):
    """The earlier link always wins: here the older link is the one that
    later closes the cycle when read in creation order, so the cycle is
    broken at the newest link and the second source falls away."""
    a = make_recipe("A")
    b = make_recipe("B")
    c = make_recipe("C")
    _link(app, b, a)   # oldest: B -> A
    _link(app, a, b)   # closes a cycle with B -> A
    _link(app, c, a)   # second source for A

    _migrate_tree_rules(app)

    assert _links(app) == [(b, a)]


def test_partially_linked_tree_is_linked_completely_into_all_plans(app, make_user, make_recipe, caplog):
    _owner, other_plan = make_user("Familie")
    _owner2, third_plan = make_user("WG")
    braten = make_recipe("Braten")
    ragout = make_recipe("Ragout")
    lasagne = make_recipe("Lasagne", plan_id=third_plan)
    salat = make_recipe("Salat")
    _link(app, braten, ragout)
    _link(app, ragout, lasagne)
    _share(app, ragout, other_plan)

    _migrate_tree_rules(app)

    assert _shared_into(app, other_plan) == sorted([braten, ragout, lasagne])
    assert _shared_into(app, third_plan) == sorted([braten, ragout])
    assert salat not in _shared_into(app, other_plan)
    assert "Familie" in caplog.text


def test_tree_completion_uses_the_repaired_links(app, make_user, make_recipe):
    """A removed second-source link doesn't merge trees any more, so its
    recipes aren't linked across."""
    _owner, other_plan = make_user("Familie")
    braten = make_recipe("Braten")
    ragout = make_recipe("Ragout")
    huhn = make_recipe("Huhn", plan_id=other_plan)
    _link(app, braten, ragout)
    _link(app, huhn, ragout)

    _migrate_tree_rules(app)

    assert _shared_into(app, other_plan) == []


def test_tree_rules_migration_is_idempotent(app, make_user, make_recipe, caplog):
    _owner, other_plan = make_user("Familie")
    braten = make_recipe("Braten")
    huhn = make_recipe("Huhn")
    ragout = make_recipe("Ragout")
    _link(app, braten, ragout)
    _link(app, huhn, ragout)
    _link(app, ragout, braten)
    _share(app, braten, other_plan)

    _migrate_tree_rules(app)
    links, shared = _links(app), _shared_into(app, other_plan)
    caplog.clear()
    _migrate_tree_rules(app)

    assert _links(app) == links == [(braten, ragout)]
    assert _shared_into(app, other_plan) == shared == sorted([braten, ragout])
    assert caplog.text == ""


def test_tree_rules_migration_leaves_valid_data_alone(app, make_user, make_recipe, caplog):
    _owner, other_plan = make_user("Familie")
    braten = make_recipe("Braten")
    ragout = make_recipe("Ragout")
    sauce = make_recipe("Sauce")
    _link(app, braten, ragout)
    _link(app, braten, sauce)
    _share(app, braten, other_plan)
    _share(app, ragout, other_plan)
    _share(app, sauce, other_plan)

    _migrate_tree_rules(app)

    assert _links(app) == sorted([(braten, ragout), (braten, sauce)])
    assert _shared_into(app, other_plan) == sorted([braten, ragout, sauce])
    assert caplog.text == ""
