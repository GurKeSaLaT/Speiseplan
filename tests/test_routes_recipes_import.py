"""The recipe import preview endpoint (fetching itself is mocked)."""
from unittest.mock import patch

from services.recipe_import import RecipeImportError


@patch("routes.recipes.crud.fetch_recipe_from_url")
def test_import_recipe_preview_success(mock_fetch, client):
    mock_fetch.return_value = {"name": "Importiert", "servings": 4, "ingredients": []}
    resp = client.post("/manage/recipe/import-preview", json={"url": "https://chefkoch.de/x"})
    assert resp.status_code == 200
    assert resp.get_json()["name"] == "Importiert"


def test_import_recipe_preview_missing_url(client):
    resp = client.post("/manage/recipe/import-preview", json={})
    assert resp.status_code == 400
    assert "error" in resp.get_json()


@patch("routes.recipes.crud.fetch_recipe_from_url")
def test_import_recipe_preview_propagates_import_error(mock_fetch, client):
    mock_fetch.side_effect = RecipeImportError("Nicht unterstützt.")
    resp = client.post("/manage/recipe/import-preview", json={"url": "https://example.com/x"})
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "Nicht unterstützt."


@patch("routes.recipes.crud.fetch_recipe_from_url")
def test_import_recipe_preview_converts_ingredients_to_display_unit(mock_fetch, client, app):
    from services.settings import update_display_units

    with app.app_context():
        update_display_units(client.plan_id, "kg", "l")

    mock_fetch.return_value = {
        "name": "Importiert", "servings": 4,
        "ingredients": [{"name": "Mehl", "amount": 1000, "unit": "g"}, {"name": "Milch", "amount": 500, "unit": "ml"}],
    }
    resp = client.post("/manage/recipe/import-preview", json={"url": "https://chefkoch.de/x"})
    assert resp.status_code == 200
    ingredients = resp.get_json()["ingredients"]
    assert ingredients == [
        {"name": "Mehl", "amount": 1, "unit": "kg"},
        {"name": "Milch", "amount": 0.5, "unit": "l"},
    ]
