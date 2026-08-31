"""Tests for routes/categories.py: category management (view, create,
delete with protection against deleting a category still in use)."""


def test_category_manage_view_lists_categories(client, make_category):
    make_category("Fleisch")
    resp = client.get("/manage/categories")
    assert resp.status_code == 200
    assert b"Fleisch" in resp.data


def test_category_manage_view_has_search_filter_when_categories_exist(client, make_category):
    make_category("Fleisch")
    resp = client.get("/manage/categories")
    assert b'id="categoryFilter"' in resp.data
    assert b"category-list-row" in resp.data
    # Must go through fuzzy_search.js/wireFuzzyFilter, NOT through
    # element.style.display directly - see static/style.css: .search-hidden
    # comment for the reason (Bootstrap's .d-flex is !important and
    # would otherwise silently override a plain inline style).
    assert b"fuzzy_search.js" in resp.data
    assert b"wireFuzzyFilter" in resp.data
    assert b"row.style.display" not in resp.data


def test_category_manage_view_no_search_filter_when_empty(client):
    resp = client.get("/manage/categories")
    assert b'id="categoryFilter"' not in resp.data


def test_add_category_creates_new_category(client, app):
    from models import Category

    resp = client.post("/add-category", data={"category_name": "Vegan"}, follow_redirects=True)
    assert resp.status_code == 200
    with app.app_context():
        assert Category.query.filter_by(name="Vegan").first() is not None


def test_add_category_ignores_empty_name(client, app):
    from models import Category

    client.post("/add-category", data={"category_name": "   "}, follow_redirects=True)
    with app.app_context():
        assert Category.query.count() == 0


def test_add_category_ignores_duplicate_name(client, app, make_category):
    from models import Category

    make_category("Fisch")
    client.post("/add-category", data={"category_name": "Fisch"}, follow_redirects=True)
    with app.app_context():
        assert Category.query.filter_by(name="Fisch").count() == 1


def test_delete_category_without_recipes_succeeds(client, app, make_category):
    from models import Category, db

    cat_id = make_category("Löschbar")
    resp = client.post(f"/delete-category/{cat_id}", follow_redirects=True)
    assert resp.status_code == 200
    with app.app_context():
        assert db.session.get(Category, cat_id) is None


def test_delete_category_with_recipes_is_rejected(client, app, make_recipe):
    from models import Category, Recipe, db

    recipe_id = make_recipe("Blockiert")
    with app.app_context():
        cat_id = db.session.get(Recipe, recipe_id).category_id

    resp = client.post(f"/delete-category/{cat_id}")
    assert resp.status_code == 400
    with app.app_context():
        assert db.session.get(Category, cat_id) is not None


def test_delete_category_unknown_id_returns_404(client):
    resp = client.post("/delete-category/999999")
    assert resp.status_code == 404
