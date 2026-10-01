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
    assert "checkedShoppingKeys.has(item.key)" in content
