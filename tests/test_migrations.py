"""Tests for migrations.py: _identifier()/_identifier_list() - the
allowlist guard in front of the f-string-built SQL in
_add_plan_id_column()/_add_plan_id_with_rebuild() (see the module-level
comment there for why this exists even though every current call site
only ever passes a hardcoded literal)."""
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
