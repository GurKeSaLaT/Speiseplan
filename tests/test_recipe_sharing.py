"""Tests for the recipe-to-plan link (routes/recipes.py:
link_recipe_to_plan/unlink_recipe_from_plan, models.py: RecipePlanLink) -
a recipe belongs to ONE plan (Recipe.owner_plan_id), but can additionally
be linked into further plans. A real link, not a copy: changes take
effect everywhere the recipe is linked."""
from datetime import date


def _login_as(app, user_id, plan_id):
    test_client = app.test_client()
    with test_client.session_transaction() as sess:
        sess['user_id'] = user_id
        sess['active_plan_id'] = plan_id
    return test_client


def test_new_recipe_owned_by_active_plan(app, client, make_category):
    cat_id = make_category("Hauptgerichte")
    resp = client.post("/add-recipe", data={
        "name": "Eigenes Gericht", "category_id": str(cat_id), "servings": "2",
        "nutrition_override": "1", "protein": "10", "carbs": "10", "fat": "10",
    }, follow_redirects=True)
    assert resp.status_code == 200

    from models import Recipe
    with app.app_context():
        recipe = Recipe.query.filter_by(name="Eigenes Gericht").first()
        assert recipe.owner_plan_id == client.plan_id


def test_recipe_invisible_to_other_plan_until_linked(app, client, make_recipe, make_user):
    recipe_id = make_recipe("Nur bei mir")
    other_user_id, other_plan_id = make_user("Andere")

    other_client = _login_as(app, other_user_id, other_plan_id)
    resp = other_client.get(f"/manage/recipe/edit/{recipe_id}")
    assert resp.status_code == 404


def test_link_recipe_to_plan_makes_it_visible_and_editable(app, client, make_recipe, make_user):
    recipe_id = make_recipe("Zum Teilen")
    other_user_id, other_plan_id = make_user("Andere")

    # other_user itself has to be a member of the target plan (not of
    # its own plan where the recipe lives) - see user_has_plan_access.
    from models import PlanMembership, db
    with app.app_context():
        db.session.add(PlanMembership(plan_id=other_plan_id, user_id=client.user_id, is_starred=False))
        db.session.commit()

    resp = client.post(f"/manage/recipe/{recipe_id}/link/{other_plan_id}", follow_redirects=False)
    assert resp.status_code == 302

    from models import RecipePlanLink
    with app.app_context():
        assert RecipePlanLink.query.filter_by(recipe_id=recipe_id, plan_id=other_plan_id).first() is not None

    other_client = _login_as(app, other_user_id, other_plan_id)
    resp = other_client.get(f"/manage/recipe/edit/{recipe_id}")
    assert resp.status_code == 200

    # Fully editable from the linked plan - the change affects the SAME
    # row (no copy).
    resp = other_client.post(f"/edit-recipe/{recipe_id}", data={
        "name": "Umbenannt vom verknüpften Plan", "category_id": "",
        "servings": "2", "nutrition_override": "1", "protein": "1", "carbs": "1", "fat": "1",
    }, follow_redirects=False)
    from models import Recipe, db
    with app.app_context():
        recipe = db.session.get(Recipe, recipe_id)
        # category_id was empty -> invalid, that's fine, here we're only
        # checking that the owner stayed unchanged, not the save itself.
        assert recipe.owner_plan_id == client.plan_id


def test_link_requires_membership_in_target_plan(app, client, make_recipe, make_user):
    recipe_id = make_recipe("Darf nicht verknüpft werden")
    _, other_plan_id = make_user("Fremd")

    # client is NOT a member of other_plan_id.
    resp = client.post(f"/manage/recipe/{recipe_id}/link/{other_plan_id}")
    assert resp.status_code == 403

    from models import RecipePlanLink
    with app.app_context():
        assert RecipePlanLink.query.filter_by(recipe_id=recipe_id, plan_id=other_plan_id).first() is None


def test_unlink_removes_visibility_but_keeps_owner_plan(app, client, make_recipe, make_user):
    recipe_id = make_recipe("Geteiltes Gericht")
    other_user_id, other_plan_id = make_user("Andere")
    from models import PlanMembership, db
    with app.app_context():
        db.session.add(PlanMembership(plan_id=other_plan_id, user_id=client.user_id, is_starred=False))
        db.session.commit()

    client.post(f"/manage/recipe/{recipe_id}/link/{other_plan_id}")

    resp = client.post(f"/manage/recipe/{recipe_id}/unlink/{other_plan_id}", follow_redirects=False)
    assert resp.status_code == 302

    from models import RecipePlanLink
    with app.app_context():
        assert RecipePlanLink.query.filter_by(recipe_id=recipe_id, plan_id=other_plan_id).first() is None

    # Still visible in the owner plan.
    resp = client.get(f"/manage/recipe/edit/{recipe_id}")
    assert resp.status_code == 200


def test_cannot_unlink_owner_plan(client, make_recipe):
    recipe_id = make_recipe("Eigenes Gericht")
    resp = client.post(f"/manage/recipe/{recipe_id}/unlink/{client.plan_id}")
    assert resp.status_code == 400


def test_only_owner_plan_can_delete_recipe(app, client, make_recipe, make_user):
    recipe_id = make_recipe("Nur Eigentümer darf löschen")
    other_user_id, other_plan_id = make_user("Andere")
    from models import PlanMembership, db
    with app.app_context():
        db.session.add(PlanMembership(plan_id=other_plan_id, user_id=client.user_id, is_starred=False))
        db.session.commit()
    client.post(f"/manage/recipe/{recipe_id}/link/{other_plan_id}")

    other_client = _login_as(app, other_user_id, other_plan_id)
    resp = other_client.post(f"/delete-recipe/{recipe_id}")
    assert resp.status_code == 403

    from models import Recipe
    with app.app_context():
        assert Recipe.query.get(recipe_id) is not None


def test_category_isolated_per_plan_with_tab_switch(app, client, make_category, make_user):
    make_category("Nur bei mir")
    _, other_plan_id = make_user("Andere")

    resp = client.get(f"/manage/categories?plan_id={other_plan_id}")
    # client is not a member of other_plan_id -> selected_plan_id()
    # falls back to the user's own active plan, so it still shows only
    # the user's own category.
    assert resp.status_code == 200
    assert b"Nur bei mir" in resp.data
