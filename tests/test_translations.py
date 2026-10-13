"""Tests for the German catalog (translations/de): every UI string found in
the source - including module-level lazy_gettext (_l) strings - has a
German translation, and the plan page actually renders German."""
import json
import os
import re
from datetime import date

from babel.messages.extract import extract_from_dir
from babel.messages.frontend import parse_mapping_cfg
from babel.messages.pofile import read_po

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KEYWORDS = {'_': None, 'gettext': None, 'ngettext': (1, 2), 'lazy_gettext': None, '_l': None}
# mutants/ is mutmut's work copy of the source, with mutated strings.
NOT_SOURCE_DIRS = {'tests', 'mutants'}


def _is_source_dir(path):
    rel = os.path.relpath(path, ROOT)
    return not os.path.basename(path).startswith('.') and rel.split(os.sep)[0] not in NOT_SOURCE_DIRS


def _extracted_msgids():
    with open(os.path.join(ROOT, 'babel.cfg')) as f:
        method_map, options_map = parse_mapping_cfg(f)
    ids = set()
    for _filename, _lineno, message, _comments, _context in extract_from_dir(
        ROOT, method_map, options_map, keywords=KEYWORDS, directory_filter=_is_source_dir,
    ):
        ids.add(message[0] if isinstance(message, tuple) else message)
    return ids


def _catalog():
    with open(os.path.join(ROOT, 'translations/de/LC_MESSAGES/messages.po'), 'rb') as f:
        return read_po(f)


def test_every_source_string_has_a_german_translation():
    catalog = _catalog()
    translated = {m.id for m in catalog if m.id and m.string and not m.fuzzy}
    missing = sorted(_extracted_msgids() - translated)
    assert missing == [], f"Untranslated (run the pybabel steps in README.md): {missing}"


def test_lazy_weekday_names_are_in_the_catalog():
    # The regression behind this file: _l() strings fell out of the catalog
    # because pybabel extract ran without -k _l.
    catalog = _catalog()
    assert catalog.get('Friday').string == 'Freitag'
    assert catalog.get('Thursday').string == 'Donnerstag'


def _plan_data(page):
    return json.loads(re.search(r"window\.PLAN_DATA = (\{.*?\});", page, re.S).group(1))


def test_plan_page_day_labels_are_german_for_german_users(app, client):
    from models import User, db

    with app.app_context():
        db.session.get(User, client.user_id).language = 'de'
        db.session.commit()

    page = client.get("/plan/2026-06-12").get_data(as_text=True)
    labels = _plan_data(page)["dayLabels"]
    assert labels[0].startswith("Freitag, 12.06.")
    assert labels[6].startswith("Donnerstag, 18.06.")


def test_plan_page_day_labels_stay_english_for_english_users(client):
    page = client.get("/plan/2026-06-12").get_data(as_text=True)
    assert _plan_data(page)["dayLabels"][0].startswith("Friday, 12.06.")


def test_nutrition_labels_are_passed_to_js_in_german(app, client):
    from models import User, db

    with app.app_context():
        db.session.get(User, client.user_id).language = 'de'
        db.session.commit()

    page = client.get(f"/plan/{date(2026, 6, 12).isoformat()}").get_data(as_text=True)
    assert 'protein_abbr: "E"' in page
    assert 'carbs_abbr: "KH"' in page
    assert 'week_total_label: "Woche"' in page
    assert 'per_day_planned_label: "pro Tag ({count} geplant)"' in page


def test_german_strings_avoid_terms_the_glossary_rules_out():
    # CONTEXT.md: "Vorgericht" sounds like a starter (it is the Ausgangsgericht
    # / a vorgekochte Zutat), recipes shared into other plans are "verlinkt",
    # not "verknüpft" (Verknüpfung is the follow-up rule), and "Rest" only
    # means last week's leftovers, not what a follow-up dish is made from.
    catalog = _catalog()
    offending = [m.string for m in catalog if m.id and m.string and not m.fuzzy
                 and re.search(r'Vorgericht|verknüpfte[nr]? Pl[aä]n|aus dem Rest', str(m.string), re.I)]
    assert offending == []


def test_follow_up_labels_use_glossary_terms_in_german(app, client):
    from models import User, db

    with app.app_context():
        db.session.get(User, client.user_id).language = 'de'
        db.session.commit()

    page = client.get("/plan/2026-06-12").get_data(as_text=True)
    assert 'follow_up_of: "Ausgangsgericht: {name} ({day})"' in page
    assert 'from_previous_short: "vorgekocht im Ausgangsgericht"' in page
    assert 'from_previous_title: "Vorgekocht: wird nicht eingekauft' in page
