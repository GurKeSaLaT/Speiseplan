"""Amount placeholders in recipe instructions: syntax, matching ingredient
lines, and what the plan page and the recipe form get from them."""
import json
import re

import pytest

from services.instruction_placeholders import (
    parse_factor, resolve_reference, tokenize_instructions, unresolved_placeholders,
)

NAMES = [
    "Champignons (braune)", "Olivenöl", "Olivenöl, plus mehr zum Beträufeln",
    "Butter", "Butter (zusätzlich)", "Eier (Größe M)", "Spaghetti",
]


@pytest.mark.parametrize("raw, expected", [
    (None, 1.0), ("0.5", 0.5), ("0,5", 0.5), ("1/4", 0.25), ("1,5/3", 0.5), ("2", 2.0),
    ("0", None), ("1/0", None),
])
def test_parse_factor(raw, expected):
    assert parse_factor(raw) == expected


@pytest.mark.parametrize("ref, nth, expected", [
    ("Olivenöl", 1, 1),                 # exact name beats the longer line
    ("olivenöl, plus", 1, 2),           # unique prefix
    ("Oliven", 1, None),                # ambiguous prefix
    ("Champignons", 1, 0),              # prefix of "Champignons (braune)"
    ("Größe M", 1, 5),                  # whole words inside the name
    ("Butter", 1, 3),
    ("Butter", 2, 4),                   # #2 = second line with "Butter"
    ("Butter", 3, None),
    ("Mehl", 1, None),
    ("  ", 1, None),
])
def test_resolve_reference(ref, nth, expected):
    assert resolve_reference(ref, NAMES, nth=nth) == expected


def test_resolve_reference_via_alias_but_literal_name_first():
    aliases = {"Spaghetti": "Nudeln", "Fusilli": "Nudeln"}
    names = ["Spaghetti", "Fusilli"]
    assert resolve_reference("Spaghetti", names, aliases) == 0
    assert resolve_reference("Fusilli", names, aliases) == 1
    # Both are "Nudeln" -> ambiguous unless #n picks one.
    assert resolve_reference("Nudeln", names, aliases) is None
    assert resolve_reference("Nudeln", names, aliases, nth=2) == 1


def test_tokenize_splits_text_and_placeholders():
    parts = tokenize_instructions("{Butter#2} schmelzen, {Eier*1/2} und { Butter * 0,5 } dazu.", NAMES)
    assert parts == [
        {"ing": 4, "factor": 1.0, "raw": "{Butter#2}"},
        {"text": " schmelzen, "},
        {"ing": 5, "factor": 0.5, "raw": "{Eier*1/2}"},
        {"text": " und "},
        {"ing": 3, "factor": 0.5, "raw": "{ Butter * 0,5 }"},
        {"text": " dazu."},
    ]


def test_tokenize_keeps_unknown_placeholders_as_text():
    assert tokenize_instructions("Mit {Mehl} und {Butter*0}.", NAMES) == [{"text": "Mit {Mehl} und {Butter*0}."}]
    assert tokenize_instructions("", NAMES) == []
    assert tokenize_instructions(None, NAMES) == []


def test_unresolved_placeholders_lists_unknown_ambiguous_and_broken():
    text = "{Butter} ok, {Mehl}, {Oliven}, {Butter*0}, {Eier#9}, kaputt {Eier und {}"
    assert unresolved_placeholders(text, NAMES) == [
        "{Mehl}", "{Oliven}", "{Butter*0}", "{Eier#9}", "{Eier und ", "{}",
    ]
    assert unresolved_placeholders("Nur Text.", NAMES) == []
    assert unresolved_placeholders(None, NAMES) == []


# --- plan page JSON ---

def test_jsonify_recipe_resolves_placeholders_in_ingredient_order(app, test_plan_id, make_recipe):
    from models import Recipe, db
    from services.planning import jsonify_recipe

    recipe_id = make_recipe("Kuchen", ingredients=[
        {"name": "Mehl", "amount": 400, "unit": "g"},
        {"name": "Butter", "amount": 100, "unit": "g"},
    ], instructions="{Butter} schmelzen, {Mehl*1/2} dazu.")
    with app.app_context():
        data = jsonify_recipe(db.session.get(Recipe, recipe_id), test_plan_id)

    assert [ing["name"] for ing in data["ingredients"]] == ["Mehl", "Butter"]
    assert data["instruction_parts"] == [
        {"ing": 1, "factor": 1.0, "raw": "{Butter}"},
        {"text": " schmelzen, "},
        {"ing": 0, "factor": 0.5, "raw": "{Mehl*1/2}"},
        {"text": " dazu."},
    ]


def test_jsonify_recipe_plain_instructions_are_one_text_part(app, test_plan_id, make_recipe):
    from models import Recipe, db
    from services.planning import jsonify_recipe

    plain = make_recipe("Ohne", instructions="Alles kochen.")
    empty = make_recipe("Leer")
    with app.app_context():
        assert jsonify_recipe(db.session.get(Recipe, plain), test_plan_id)["instruction_parts"] == [{"text": "Alles kochen."}]
        assert jsonify_recipe(db.session.get(Recipe, empty), test_plan_id)["instruction_parts"] == []


# --- recipe form ---

def _edit_form(**overrides):
    form = {
        "name": "Kuchen", "category_id": "", "servings": "2",
        "ing_name[]": ["Mehl", "Butter"], "ing_amount[]": ["400", "100"], "ing_unit[]": ["g", "g"],
        "ing_category[]": ["", ""], "ing_pantry[]": ["0", "0"],
        "instructions": "",
    }
    form.update(overrides)
    return form


def test_edit_view_warns_about_unresolved_placeholders(client, make_recipe):
    recipe_id = make_recipe("Kuchen", ingredients=[{"name": "Mehl", "amount": 400, "unit": "g"}],
                            instructions="{Mehl} und {Zucker}")
    html = client.get(f"/manage/recipe/edit/{recipe_id}").data.decode("utf-8")
    unresolved = json.loads(re.search(r"window\.RECIPE_UNRESOLVED_PLACEHOLDERS = (.*?);\n", html).group(1))
    assert unresolved == ["{Zucker}"]
    # The help text keeps its literal braces.
    assert "{Flour*0.5}" in html


def test_autosave_reports_unresolved_placeholders_against_new_ingredients(app, client, make_recipe, make_category):
    category_id = make_category("Kuchen")
    recipe_id = make_recipe("Kuchen", category_id=category_id)
    resp = client.post(
        f"/edit-recipe/{recipe_id}",
        data=_edit_form(category_id=str(category_id), instructions="{Butter} und {Zucker} und {Mehl*1/2}"),
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert resp.status_code == 200
    assert resp.get_json()["unresolved_placeholders"] == ["{Zucker}"]
