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


@needs_node
def test_extra_servings_count_in_week_and_outside_follow_ups():
    data = _week_data(
        followUpOf=[None, None, {"date": "2026-06-12", "index": 0, "name": "A", "label": "D0"}, None, None, None, None],
        followUpsOut=[
            [{"date": "2026-06-14", "index": 2, "name": "B", "label": "D2", "servings": 9, "pending": False},
             {"date": "2026-06-20", "index": None, "name": "C", "label": "Sa", "servings": 4, "pending": True}],
            [], [], [], [], [], [],
        ],
    )
    # In-week follow-up: its live servings (3); outside: the stored 4.
    assert _plan_js("extraServingsFor(0)", data) == 7
    assert _plan_js("extraServingsFor(1)", data) == 0


@needs_node
def test_follow_up_notes_text():
    data = _week_data(
        followUpOf=[None, None, {"date": "2026-06-12", "index": 0, "name": "Ofengemüse", "label": "Fr"}, None, None, None, None],
        followUpsOut=[[{"date": "2026-06-14", "index": 2, "name": "Nudeln", "label": "So", "servings": 2, "pending": False}],
                      [], [], [], [], [], []],
    )
    stubs_i18n = "window.I18N = {follow_up_of: 'aus {name} ({day})', follow_up_on: '{name} am {day}', follow_up_pending: '{name} am {day} (später)'};"
    html = _run_js("plan.js", "renderFollowUpNotes(0) + '|' + renderFollowUpNotes(2)",
                   _PLAN_PAGE_STUBS + f"window.PLAN_DATA = {json.dumps(data)};" + _ESCAPE_HTML_JS + stubs_i18n)
    assert html == '<div class="follow-up-note">↪ Nudeln am So</div>|<div class="follow-up-note">↪ aus Ofengemüse (Fr)</div>'
