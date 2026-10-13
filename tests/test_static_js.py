"""Source-level regression checks for static JS that has no browser tests."""
from pathlib import Path

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


def _read(name):
    return (STATIC_DIR / name).read_text(encoding="utf-8")


def test_other_plan_meals_escape_user_names():
    """Plan and recipe names are user input and go into innerHTML."""
    content = _read("plan.js")
    assert "${escapeHtml(meal.planName)}" in content
    assert "${escapeHtml(meal.recipeName)}" in content
    assert "${meal.planName}" not in content
    assert "${meal.recipeName}" not in content


def test_create_week_status_texts_are_translated():
    content = _read("create_week.js")
    assert '"Fill automatically"' not in content
    assert "window.I18N.day_fill_automatically" in content


def test_fuzzy_search_never_matches_across_terms():
    """Searchable text is one term per line; the old matcher ran one
    subsequence over everything joined together, so a query could pick its
    letters from several unrelated names."""
    content = _read("fuzzy_search.js")
    assert "split('\\n')" in content
    assert "isCloseSubsequence" in content


def test_shopping_checkboxes_are_saved():
    content = _read("plan-shopping.js")
    assert "/shopping-check" in content
    assert "shoppingChecks.get(item.key)" in content


def test_shopping_ticks_keep_bought_amounts():
    """Partly bought lines split into a ticked and an open row instead of
    losing the tick (source-level guard only, no JS runtime here)."""
    content = _read("plan-shopping.js")
    assert "function applyShoppingChecks(" in content
    assert "remainderOf" in content


# --- Runtime checks via Node (skipped where Node isn't installed) ---

import json
import shutil
import subprocess

import pytest

NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="node not installed")


def _run_js(filenames, expression, globals_js=""):
    """Evaluates expression after loading static/<filename> (one name or a
    list, in order) into a fresh vm context (top-level function/const
    declarations become callable) and returns its JSON-decoded result."""
    if isinstance(filenames, str):
        filenames = [filenames]
    loads = "\n".join(
        f"vm.runInContext(fs.readFileSync({json.dumps(str(STATIC_DIR / name))}, 'utf8'), ctx);"
        for name in filenames
    )
    script = f"""
const vm = require('vm');
const fs = require('fs');
const ctx = vm.createContext({{ window: {{ I18N: {{}} }}, console }});
vm.runInContext({json.dumps(globals_js)}, ctx);
{loads}
process.stdout.write(JSON.stringify(vm.runInContext({json.dumps(expression)}, ctx)));
"""
    result = subprocess.run([NODE, "-e", script], capture_output=True, text=True, timeout=30, check=True)
    return json.loads(result.stdout)


def _subtract(consolidated, leftovers):
    return _run_js(
        "plan-shopping.js",
        f"(() => {{ const c = {json.dumps(consolidated)}; subtractLeftovers(c, {json.dumps(leftovers)}); return c; }})()",
    )


def _line(name, amount, unit):
    return {f"{name}|||{unit}": {"key": f"item:{name}|||{unit}", "name": name, "amount": amount, "unit": unit}}


@needs_node
def test_subtract_leftovers_reduces_matching_line():
    result = _subtract(_line("Zucchini", 500, "g"), [{"name": "Zucchini", "amount": 300, "unit": "g"}])
    assert result["Zucchini|||g"]["amount"] == 200


@needs_node
def test_subtract_leftovers_drops_covered_line_and_ignores_other_units():
    consolidated = {**_line("Zucchini", 300, "g"), **_line("Paprika", 2, "Stück")}
    result = _subtract(consolidated, [
        {"name": "Zucchini", "amount": 400, "unit": "g"},
        {"name": "Paprika", "amount": 100, "unit": "g"},
    ])
    assert "Zucchini|||g" not in result
    assert result["Paprika|||Stück"]["amount"] == 2


@needs_node
def test_subtract_leftovers_without_amount_drops_every_line_of_that_name():
    consolidated = {**_line("Sahne", 200, "ml"), **_line("Sahne", 1, "Becher"), **_line("Reis", 100, "g")}
    result = _subtract(consolidated, [{"name": "Sahne", "amount": None, "unit": None}])
    assert list(result) == ["Reis|||g"]


@needs_node
def test_subtract_leftovers_unit_match_is_case_insensitive():
    result = _subtract(_line("Eier", 6, "Stück"), [{"name": "Eier", "amount": 2, "unit": "stück"}])
    assert result["Eier|||Stück"]["amount"] == 4


# A minimal escapeHtml (plan.js has the real one, which needs the DOM).
_ESCAPE_HTML_JS = """
function escapeHtml(text) {
    return String(text).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}
"""


def _render_instructions(recipe, factor):
    return _run_js(
        ["plan-shopping.js", "plan-detail.js"],
        f"renderInstructionParts({json.dumps(recipe)}, {factor})",
        _ESCAPE_HTML_JS,
    )


@needs_node
def test_instruction_placeholders_scale_with_servings_and_share():
    recipe = {
        "instructions": "x",
        "ingredients": [
            {"name": "Mehl", "amount": 400, "unit": "g"},
            {"name": "Eier", "amount": 2, "unit": "Stück"},
            {"name": "Salz", "amount": 0, "unit": ""},
        ],
        "instruction_parts": [
            {"text": "Erst "}, {"ing": 0, "factor": 1, "raw": "{Mehl}"},
            {"text": " Mehl, davon "}, {"ing": 0, "factor": 0.25, "raw": "{Mehl*1/4}"},
            {"text": " beiseite; "}, {"ing": 1, "factor": 1, "raw": "{Eier}"},
            {"text": " Eier <roh>, "}, {"ing": 2, "factor": 1, "raw": "{Salz}"}, {"text": "Salz"},
        ],
    }
    html = _render_instructions(recipe, 1.5)
    assert html == (
        'Erst <strong class="instruction-amount">600 g</strong> Mehl, davon '
        '<strong class="instruction-amount">150 g</strong> beiseite; '
        '<strong class="instruction-amount">3</strong> Eier &lt;roh&gt;, '
        'Salz'
    )


@needs_node
def test_instructions_without_parts_render_escaped_text():
    html = _render_instructions({"instructions": "a < b {Mehl}", "ingredients": []}, 2)
    assert html == "a &lt; b {Mehl}"


@needs_node
def test_literal_amount_placeholders_scale_and_keep_their_unit():
    recipe = {
        "instructions": "x", "ingredients": [],
        "instruction_parts": [
            {"amount": 500, "unit": "ml", "raw": "{500 ml}"}, {"text": " Wasser, "},
            {"amount": 12, "unit": "", "raw": "{12}"}, {"text": " Knödel, "},
            {"amount": 2, "unit": "Stück", "raw": "{2 Stück}"},
        ],
    }
    html = _render_instructions(recipe, 0.5)
    assert html == (
        '<strong class="instruction-amount">250 ml</strong> Wasser, '
        '<strong class="instruction-amount">6</strong> Knödel, '
        '<strong class="instruction-amount">1 Stück</strong>'
    )


_PLAN_PAGE_STUBS = """
var document = {
    addEventListener() {}, getElementById() { return null; },
    createElement() {
        let text = '';
        return {
            set textContent(value) { text = String(value); },
            get innerHTML() { return text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); },
        };
    },
};
"""


def _plan_js(expression, plan_data):
    stubs = _PLAN_PAGE_STUBS + f"window.PLAN_DATA = {json.dumps(plan_data)}; window.CSRF_TOKEN = '';" + _ESCAPE_HTML_JS
    return _run_js("plan.js", expression, stubs)


def _week_data(**overrides):
    data = {
        "planId": 1, "weekDates": [f"2026-06-{12 + i}" for i in range(7)], "dayLabels": [f"D{i}" for i in range(7)],
        "excludedDays": [False] * 7, "servingsList": [2, 2, 3, 2, 2, 2, 2], "cookedMain": [False] * 7,
        "plan": [None] * 7, "sidePlan": [[] for _ in range(7)],
    }
    data.update(overrides)
    return data


def _shopping_lines(recipe, shopping):
    return _run_js("plan-shopping.js", f"dishShoppingLines({json.dumps(recipe)}, {json.dumps(shopping)})")


_PRECOOKED_RECIPE = {"servings": 2, "ingredients": [
    {"name": "Nudeln", "amount": 200, "unit": "g", "from_previous": False},
    {"name": "Ofengemüse", "amount": 300, "unit": "g", "from_previous": True},
]}


@needs_node
def test_dish_shopping_lines_multiply_by_the_given_servings():
    lines = _shopping_lines(_PRECOOKED_RECIPE, {"servings": 5, "followUpServings": 3, "skipPrecooked": False})
    assert [(line["name"], line["amount"]) for line in lines] == [("Nudeln", 500), ("Ofengemüse", 750)]


@needs_node
def test_dish_shopping_lines_skip_precooked_ingredients_when_flagged():
    lines = _shopping_lines(_PRECOOKED_RECIPE, {"servings": 2, "followUpServings": 0, "skipPrecooked": True})
    assert [(line["name"], line["amount"]) for line in lines] == [("Nudeln", 200)]


@needs_node
def test_follow_up_notes_text():
    data = _week_data(
        followUpOf=[None, None, {"date": "2026-06-12", "index": 0, "name": "Ofengemüse", "label": "Fr"}, None, None, None, None],
        followUpsOut=[[{"date": "2026-06-14", "index": 2, "name": "Nudeln", "label": "So", "pending": False}],
                      [], [], [], [], [], []],
    )
    stubs_i18n = "window.I18N = {follow_up_of: 'aus {name} ({day})', follow_up_on: '{name} am {day}', follow_up_pending: '{name} am {day} (später)'};"
    html = _run_js("plan.js", "renderFollowUpNotes(0) + '|' + renderFollowUpNotes(2)",
                   _PLAN_PAGE_STUBS + f"window.PLAN_DATA = {json.dumps(data)};" + _ESCAPE_HTML_JS + stubs_i18n)
    assert html == '<div class="follow-up-note">↪ Nudeln am So</div>|<div class="follow-up-note">↪ aus Ofengemüse (Fr)</div>'


@needs_node
def test_follow_up_notes_of_a_source_side():
    data = _week_data(sideFollowUpsOut={"7": [
        {"date": "2026-06-19", "index": None, "name": "Gebratener <Reis>", "label": "Fr", "pending": True}]})
    stubs_i18n = "window.I18N = {follow_up_on: '{name} am {day}', follow_up_pending: '{name} am {day} (später)'};"
    html = _run_js("plan.js", "renderFollowUpsOutNotes(sideFollowUpsOut[7]) + '|' + renderFollowUpsOutNotes(sideFollowUpsOut[8])",
                   _PLAN_PAGE_STUBS + f"window.PLAN_DATA = {json.dumps(data)};" + _ESCAPE_HTML_JS + stubs_i18n)
    assert html == '<div class="follow-up-note">↪ Gebratener &lt;Reis&gt; am Fr (später)</div>|'


# --- recipe_form.js: plans a merging follow-up link adds (services/recipe_trees.py) ---

def _merge_affected(selected, initial, merge_plans):
    return _run_js(
        "recipe_form.js",
        f"rformMergeAffectedPlans({json.dumps(selected)}, {json.dumps(initial)}, {json.dumps(merge_plans)})",
        "var document = { addEventListener() {} };",
    )


@needs_node
def test_merge_warning_lists_plans_of_new_follow_ups_only():
    merge_plans = {"3": ["Familie", "WG"], "4": ["Familie", "Oma"], "5": ["Arbeit"]}
    # 5 was already a follow-up when the form opened: nothing new there.
    assert _merge_affected(["3", "4", "5"], ["5"], merge_plans) == ["Familie", "Oma", "WG"]
    assert _merge_affected(["5", "7"], ["5"], merge_plans) == []
