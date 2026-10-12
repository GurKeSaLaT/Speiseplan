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


def _run_js(filename, expression, globals_js=""):
    """Evaluates expression after loading static/<filename> into a fresh vm
    context (top-level function/const declarations become callable) and
    returns its JSON-decoded result."""
    script = f"""
const vm = require('vm');
const fs = require('fs');
const ctx = vm.createContext({{ window: {{ I18N: {{}} }}, console }});
vm.runInContext({json.dumps(globals_js)}, ctx);
vm.runInContext(fs.readFileSync({json.dumps(str(STATIC_DIR / filename))}, 'utf8'), ctx);
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
