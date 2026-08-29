"""Tests für routes/settings.py: die Zutaten-Gleichsetzung-Seite
(/manage/ingredient-aliases, /update-ingredient-aliases)."""


def test_ingredient_aliases_view_lists_known_names(client, make_recipe):
    make_recipe("Suppe", ingredients=[{"name": "Spaghetti", "amount": 500, "unit": "g"}])
    resp = client.get("/manage/ingredient-aliases")
    assert resp.status_code == 200
    assert b"Spaghetti" in resp.data
    assert b"fuzzy_search.js" in resp.data
    assert b"wireFuzzyFilter" in resp.data


def test_ingredient_aliases_view_empty_state(client):
    resp = client.get("/manage/ingredient-aliases")
    assert resp.status_code == 200
    assert "Noch keine Zutaten vorhanden.".encode("utf-8") in resp.data


def test_update_ingredient_aliases_creates_grouping(client, app, make_recipe):
    from services.ingredient_aliases import normalize_ingredient_name

    make_recipe("A", ingredients=[{"name": "Spaghetti", "amount": 500, "unit": "g"}])
    make_recipe("B", ingredients=[{"name": "Fusilli", "amount": 300, "unit": "g"}])

    resp = client.post("/update-ingredient-aliases", data={
        "raw_name[]": ["Spaghetti", "Fusilli"],
        "canonical_name[]": ["Nudeln", "Nudeln"],
    }, follow_redirects=False)
    assert resp.status_code == 302

    with app.app_context():
        assert normalize_ingredient_name("Spaghetti") == "Nudeln"
        assert normalize_ingredient_name("Fusilli") == "Nudeln"


def test_update_ingredient_aliases_unchanged_row_stays_unaliased(client, app, make_recipe):
    from services.ingredient_aliases import get_all_aliases

    make_recipe("A", ingredients=[{"name": "Reis", "amount": 200, "unit": "g"}])

    client.post("/update-ingredient-aliases", data={
        "raw_name[]": ["Reis"],
        "canonical_name[]": ["Reis"],
    })
    with app.app_context():
        assert get_all_aliases() == {}


def test_ingredient_aliases_view_prefills_existing_alias(client, app, make_recipe):
    from services.ingredient_aliases import set_alias

    make_recipe("A", ingredients=[{"name": "Spaghetti", "amount": 500, "unit": "g"}])
    with app.app_context():
        set_alias("Spaghetti", "Nudeln")

    resp = client.get("/manage/ingredient-aliases")
    assert b'value="Nudeln"' in resp.data


# --- AJAX-Endpunkt für die Rezept-Formulare (api_set_ingredient_alias) ---

def test_api_set_ingredient_alias_creates_mapping(client, app):
    from services.ingredient_aliases import normalize_ingredient_name

    resp = client.post("/api/ingredient-alias/set", json={"raw_name": "Olivenöl", "canonical_name": "Öl"})
    assert resp.status_code == 200
    data = resp.get_json()
    # category ist None, da "Öl" noch bei keiner bestehenden Zutat-Zeile
    # kategorisiert ist (siehe eigene Tests für infer_category unten).
    assert data == {"ok": True, "raw_name": "Olivenöl", "canonical_name": "Öl", "category": None}

    with app.app_context():
        assert normalize_ingredient_name("Olivenöl") == "Öl"


def test_api_set_ingredient_alias_normalizes_input(client, app):
    from services.ingredient_aliases import normalize_ingredient_name

    resp = client.post("/api/ingredient-alias/set", json={"raw_name": "  fusilli  ", "canonical_name": "nudeln"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data == {"ok": True, "raw_name": "Fusilli", "canonical_name": "Nudeln", "category": None}
    with app.app_context():
        assert normalize_ingredient_name("Fusilli") == "Nudeln"


def test_api_set_ingredient_alias_returns_inferred_category(client, app, make_recipe):
    """Existiert bereits eine kategorisierte Zutat-Zeile für die kanonische
    Zutat (z.B. "Nudeln" schon als "Teigwaren" einsortiert), soll das
    Setzen eines weiteren Alias auf denselben Namen diese Kategorie direkt
    mitliefern - static/ingredient_alias_hint.js übernimmt sie automatisch
    ins Kategorie-Feld der aktuellen Zutatenzeile (siehe
    fillCategoryFromAlias), damit alle gleichgesetzten Zutaten konsistent
    einsortiert sind."""
    make_recipe("Spaghetti-Gericht", ingredients=[
        {"name": "Nudeln", "amount": 500, "unit": "g", "category": "Teigwaren"},
    ])

    resp = client.post("/api/ingredient-alias/set", json={"raw_name": "Penne", "canonical_name": "Nudeln"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["category"] == "Teigwaren"


def test_api_set_ingredient_alias_requires_both_fields(client):
    resp = client.post("/api/ingredient-alias/set", json={"raw_name": "Reis"})
    assert resp.status_code == 400
    assert "error" in resp.get_json()

    resp2 = client.post("/api/ingredient-alias/set", json={"canonical_name": "Reis"})
    assert resp2.status_code == 400


def test_api_set_ingredient_alias_rejects_empty_body(client):
    resp = client.post("/api/ingredient-alias/set", json={})
    assert resp.status_code == 400
