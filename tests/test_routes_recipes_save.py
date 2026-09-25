"""Saving recipes: add, edit (incl. autosave) and delete, plus nutrition
computed on save."""


def _base_recipe_form(category_id, **overrides):
    # nutrition_override="1" pins protein/carbs/fat so tests don't depend on
    # computed nutrition; calories then always come out as
    # (20+30)*4 + 10*9 = 290.
    form = {
        "name": "Neues Gericht",
        "category_id": str(category_id),
        "nutrition_override": "1",
        "protein": "20",
        "carbs": "30",
        "fat": "10",
        "servings": "2",
        "ing_name[]": ["Nudeln", ""],
        "ing_amount[]": ["500", ""],
        "ing_unit[]": ["g", ""],
        "ing_category[]": ["Teigwaren", ""],
    }
    form.update(overrides)
    return form


def test_add_recipe_creates_recipe_with_ingredients_and_seasons(client, app, make_category):
    from models import Recipe

    cat_id = make_category("Hauptgerichte")
    form = _base_recipe_form(cat_id, seasons=["Sommer"])

    resp = client.post("/add-recipe", data=form, follow_redirects=True)
    assert resp.status_code == 200

    with app.app_context():
        recipe = Recipe.query.filter_by(name="Neues Gericht").first()
        assert recipe is not None
        assert recipe.calories == 290
        assert recipe.servings == 2
        # The empty second row is skipped.
        assert len(recipe.ingredients) == 1
        assert recipe.ingredients[0].name == "Nudeln"
        assert len(recipe.seasons) == 1


def test_add_recipe_redirects_into_edit_view_of_the_new_recipe(client, app, make_category):
    """After the one explicit create click, editing (with autosave) starts."""
    from models import Recipe

    cat_id = make_category("Hauptgerichte")
    form = _base_recipe_form(cat_id)

    resp = client.post("/add-recipe", data=form)
    assert resp.status_code == 302

    with app.app_context():
        recipe = Recipe.query.filter_by(name="Neues Gericht").first()
    assert resp.headers["Location"] == f"/manage/recipe/edit/{recipe.id}?plan_id={client.plan_id}"


def test_add_recipe_without_explicit_plan_id_defaults_to_starred_plan(app, client, make_user, make_category):
    """Without ?plan_id= a new recipe goes to the starred plan, even when the
    user has other plans."""
    from models import PlanMembership, Recipe, db

    other_plan_id = make_user("Zweitplan-Besitzer")[1]
    with app.app_context():
        db.session.add(PlanMembership(plan_id=other_plan_id, user_id=client.user_id, is_starred=False))
        db.session.commit()

    cat_id = make_category("Hauptgerichte")
    form = _base_recipe_form(cat_id)
    client.post("/add-recipe", data=form)

    with app.app_context():
        recipe = Recipe.query.filter_by(name="Neues Gericht").first()
        assert recipe.owner_plan_id == client.plan_id


def test_add_recipe_respects_explicit_plan_id_from_selector(app, client, make_user, make_category):
    from models import PlanMembership, Recipe, db

    other_plan_id = make_user("Zweitplan-Besitzer")[1]
    with app.app_context():
        db.session.add(PlanMembership(plan_id=other_plan_id, user_id=client.user_id, is_starred=False))
        db.session.commit()

    cat_id = make_category("Hauptgerichte", plan_id=other_plan_id)
    form = _base_recipe_form(cat_id, plan_id=str(other_plan_id))
    client.post("/add-recipe", data=form)

    with app.app_context():
        recipe = Recipe.query.filter_by(name="Neues Gericht").first()
        assert recipe.owner_plan_id == other_plan_id


def test_add_recipe_sets_updated_at(client, app, make_category):
    from models import Recipe

    cat_id = make_category("Frisch")
    form = _base_recipe_form(cat_id)
    client.post("/add-recipe", data=form, follow_redirects=True)

    with app.app_context():
        recipe = Recipe.query.filter_by(name="Neues Gericht").first()
        assert recipe.updated_at is not None


def test_add_recipe_side_dish_and_favorite_flags(client, app, make_category):
    from models import Recipe

    cat_id = make_category("Beilagen")
    form = _base_recipe_form(cat_id, is_side_dish="1", is_favorite="1")

    client.post("/add-recipe", data=form, follow_redirects=True)
    with app.app_context():
        recipe = Recipe.query.filter_by(name="Neues Gericht").first()
        assert recipe.is_side_dish is True
        assert recipe.is_favorite is True


def test_add_recipe_normalizes_ingredient_units(client, app, make_category):
    from models import Recipe

    cat_id = make_category("Normalisierung")
    form = _base_recipe_form(cat_id, **{
        "ing_name[]": ["Mehl", "Öl", ""],
        "ing_amount[]": ["1", "2", ""],
        "ing_unit[]": ["kg", "EL", ""],
        "ing_category[]": ["", "", ""],
    })

    client.post("/add-recipe", data=form, follow_redirects=True)
    with app.app_context():
        recipe = Recipe.query.filter_by(name="Neues Gericht").first()
        by_name = {i.name: (i.amount, i.unit) for i in recipe.ingredients}
        assert by_name["Mehl"] == (1000, "g")
        assert by_name["Öl"] == (30, "ml")


def test_add_recipe_sets_ingredient_pantry_flags(client, app, make_category):
    """ing_pantry[] has one "0"/"1" per row (a hidden mirror input)."""
    from models import Recipe

    cat_id = make_category("Pantry-Test")
    form = _base_recipe_form(cat_id, **{
        "ing_name[]": ["Salz", "Zwiebel", ""],
        "ing_amount[]": ["5", "1", ""],
        "ing_unit[]": ["g", "Stk", ""],
        "ing_category[]": ["Gewürze", "", ""],
        "ing_pantry[]": ["1", "0", "0"],
    })

    client.post("/add-recipe", data=form, follow_redirects=True)
    with app.app_context():
        recipe = Recipe.query.filter_by(name="Neues Gericht").first()
        by_name = {i.name: i.is_pantry for i in recipe.ingredients}
        assert by_name["Salz"] is True
        assert by_name["Zwiebel"] is False


def test_add_recipe_without_ing_pantry_field_defaults_to_false(client, app, make_category):
    from models import Recipe

    cat_id = make_category("Ohne Pantry-Feld")
    form = _base_recipe_form(cat_id)

    client.post("/add-recipe", data=form, follow_redirects=True)
    with app.app_context():
        recipe = Recipe.query.filter_by(name="Neues Gericht").first()
        assert recipe.ingredients[0].is_pantry is False


def test_edit_recipe_replaces_ingredients_and_fields(client, app, make_recipe):
    from models import Recipe, db

    recipe_id = make_recipe("Altes Gericht", ingredients=[{"name": "Alt", "amount": 1, "unit": "Stk"}])
    with app.app_context():
        cat_id = db.session.get(Recipe, recipe_id).category_id

    form = _base_recipe_form(cat_id, name="Geändertes Gericht", **{
        "ing_name[]": ["Neu"], "ing_amount[]": ["2"], "ing_unit[]": ["Stk"], "ing_category[]": [""],
    })

    resp = client.post(f"/edit-recipe/{recipe_id}", data=form, follow_redirects=True)
    assert resp.status_code == 200

    with app.app_context():
        recipe = db.session.get(Recipe, recipe_id)
        assert recipe.name == "Geändertes Gericht"
        assert [i.name for i in recipe.ingredients] == ["Neu"]


def test_edit_recipe_returns_json_for_autosave_requests(client, app, make_recipe):
    """Autosave requests get JSON instead of a redirect."""
    from models import Recipe, db

    recipe_id = make_recipe("Altes Gericht", ingredients=[{"name": "Alt", "amount": 1, "unit": "Stk"}])
    with app.app_context():
        cat_id = db.session.get(Recipe, recipe_id).category_id

    form = _base_recipe_form(cat_id, name="Geändertes Gericht")
    resp = client.post(f"/edit-recipe/{recipe_id}", data=form, headers={"X-Requested-With": "XMLHttpRequest"})

    assert resp.status_code == 200
    assert resp.get_json() == {"ok": True, "calories": 290, "protein": 20.0, "carbs": 30.0, "fat": 10.0}

    with app.app_context():
        assert db.session.get(Recipe, recipe_id).name == "Geändertes Gericht"


def test_edit_recipe_still_redirects_for_a_traditional_submit(client, app, make_recipe):
    from models import Recipe, db

    recipe_id = make_recipe("Altes Gericht", ingredients=[{"name": "Alt", "amount": 1, "unit": "Stk"}])
    with app.app_context():
        cat_id = db.session.get(Recipe, recipe_id).category_id

    form = _base_recipe_form(cat_id, name="Geändertes Gericht")
    resp = client.post(f"/edit-recipe/{recipe_id}", data=form)

    assert resp.status_code == 302
    assert resp.headers["Location"] == f"/manage/recipe/edit-list?plan_id={client.plan_id}"


def test_edit_recipe_sets_ingredient_pantry_flag(client, app, make_recipe):
    from models import Recipe, db

    recipe_id = make_recipe("Altes Gericht", ingredients=[{"name": "Alt", "amount": 1, "unit": "Stk"}])
    with app.app_context():
        cat_id = db.session.get(Recipe, recipe_id).category_id

    form = _base_recipe_form(cat_id, name="Geändertes Gericht", **{
        "ing_name[]": ["Pfeffer"], "ing_amount[]": ["1"], "ing_unit[]": ["g"],
        "ing_category[]": ["Gewürze"], "ing_pantry[]": ["1"],
    })

    client.post(f"/edit-recipe/{recipe_id}", data=form, follow_redirects=True)
    with app.app_context():
        recipe = db.session.get(Recipe, recipe_id)
        assert recipe.ingredients[0].is_pantry is True


def test_edit_recipe_bumps_updated_at(client, app, make_recipe):
    """Even a save that changes no column value bumps updated_at."""
    from datetime import datetime, timedelta, timezone
    from models import Recipe, db

    recipe_id = make_recipe("Alt")
    with app.app_context():
        recipe = db.session.get(Recipe, recipe_id)
        cat_id = recipe.category_id
        recipe.updated_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=5)
        db.session.commit()
        old_updated_at = recipe.updated_at

    form = _base_recipe_form(cat_id, name="Alt", **{
        "ing_name[]": [""], "ing_amount[]": [""], "ing_unit[]": [""], "ing_category[]": [""],
    })
    client.post(f"/edit-recipe/{recipe_id}", data=form, follow_redirects=True)

    with app.app_context():
        recipe = db.session.get(Recipe, recipe_id)
        assert recipe.updated_at > old_updated_at


def test_edit_recipe_normalizes_ingredient_units(client, app, make_recipe):
    from models import Recipe, db

    recipe_id = make_recipe("Mengenänderung")
    with app.app_context():
        cat_id = db.session.get(Recipe, recipe_id).category_id

    form = _base_recipe_form(cat_id, **{
        "ing_name[]": ["Milch"], "ing_amount[]": ["1"], "ing_unit[]": ["Liter"], "ing_category[]": [""],
    })
    client.post(f"/edit-recipe/{recipe_id}", data=form, follow_redirects=True)

    with app.app_context():
        recipe = db.session.get(Recipe, recipe_id)
        assert (recipe.ingredients[0].amount, recipe.ingredients[0].unit) == (1000, "ml")


def test_edit_recipe_unknown_id_returns_404(client, make_category):
    cat_id = make_category()
    resp = client.post(f"/edit-recipe/999999", data=_base_recipe_form(cat_id))
    assert resp.status_code == 404


def test_delete_recipe_removes_it(client, app, make_recipe):
    from models import Recipe, db

    recipe_id = make_recipe("Zu löschen")
    resp = client.post(f"/delete-recipe/{recipe_id}", follow_redirects=True)
    assert resp.status_code == 200
    with app.app_context():
        assert db.session.get(Recipe, recipe_id) is None


def test_delete_recipe_unknown_id_returns_404(client):
    resp = client.post("/delete-recipe/999999")
    assert resp.status_code == 404


def test_delete_recipe_clears_dangling_plan_references(client, app, make_recipe):
    """The day loses its main dish (and cooked flag); side rows are removed."""
    from datetime import date

    from models import PlanDay, PlanDaySide, db

    main_id = make_recipe("Hauptgericht")
    side_id = make_recipe("Beilage", is_side_dish=True)

    with app.app_context():
        day = PlanDay(plan_id=client.plan_id, date=date(2026, 1, 2), main_recipe_id=main_id, cooked=True)
        db.session.add(day)
        db.session.flush()
        db.session.add(PlanDaySide(plan_day_id=day.id, recipe_id=side_id))
        db.session.commit()
        day_id = day.id

    resp = client.post(f"/delete-recipe/{main_id}", follow_redirects=True)
    assert resp.status_code == 200
    resp = client.post(f"/delete-recipe/{side_id}", follow_redirects=True)
    assert resp.status_code == 200

    with app.app_context():
        day = db.session.get(PlanDay, day_id)
        assert day.main_recipe_id is None
        assert day.cooked is False
        assert PlanDaySide.query.filter_by(plan_day_id=day_id).count() == 0


def test_add_recipe_computes_nutrition_from_ingredients(client, app, make_category):
    from models import Recipe
    from services.nutrition import set_nutrition

    cat_id = make_category("Berechnet")
    with app.app_context():
        set_nutrition(client.plan_id, "Mehl", reference_unit="g", protein=10, carbs=70, fat=1)

    form = _base_recipe_form(cat_id, servings="2", **{
        "nutrition_override": "",
        "ing_name[]": ["Mehl", ""],
        "ing_amount[]": ["200", ""],
        "ing_unit[]": ["g", ""],
        "ing_category[]": ["", ""],
    })
    client.post("/add-recipe", data=form, follow_redirects=True)

    with app.app_context():
        recipe = Recipe.query.filter_by(name="Neues Gericht").first()
        assert recipe.nutrition_override is False
        # 200 g at 10/70/1 per 100 g, over 2 servings -> 10/70/1 per serving;
        # calories (10+70)*4 + 1*9 = 329.
        assert recipe.calories == 329
        assert recipe.protein == 10.0
        assert recipe.carbs == 70.0
        assert recipe.fat == 1.0


def test_add_recipe_without_nutrition_data_computes_zero(client, app, make_category):
    from models import Recipe

    cat_id = make_category("Ohne Nährwerte")
    form = _base_recipe_form(cat_id, **{"nutrition_override": ""})
    client.post("/add-recipe", data=form, follow_redirects=True)

    with app.app_context():
        recipe = Recipe.query.filter_by(name="Neues Gericht").first()
        assert recipe.calories == 0
        assert recipe.protein == 0.0


def test_add_recipe_override_ignores_computed_nutrition(client, app, make_category):
    from models import Recipe
    from services.nutrition import set_nutrition

    cat_id = make_category("Überschrieben")
    with app.app_context():
        set_nutrition(client.plan_id, "Nudeln", reference_unit="g", protein=1, carbs=1, fat=1)

    # The override values from _base_recipe_form() win over the stored reference.
    form = _base_recipe_form(cat_id)
    client.post("/add-recipe", data=form, follow_redirects=True)

    with app.app_context():
        recipe = Recipe.query.filter_by(name="Neues Gericht").first()
        assert recipe.nutrition_override is True
        assert recipe.calories == 290


def test_edit_recipe_recomputes_nutrition_when_ingredients_change(client, app, make_recipe):
    from models import Recipe, db
    from services.nutrition import set_nutrition

    recipe_id = make_recipe("Neu berechnen", ingredients=[{"name": "Alt", "amount": 1, "unit": "Stk"}])
    with app.app_context():
        cat_id = db.session.get(Recipe, recipe_id).category_id
        set_nutrition(client.plan_id, "Reis", reference_unit="g", protein=3, carbs=28, fat=0.3)

    form = _base_recipe_form(cat_id, servings="1", **{
        "nutrition_override": "",
        "ing_name[]": ["Reis"], "ing_amount[]": ["200"], "ing_unit[]": ["g"], "ing_category[]": [""],
    })
    client.post(f"/edit-recipe/{recipe_id}", data=form, follow_redirects=True)

    with app.app_context():
        recipe = db.session.get(Recipe, recipe_id)
        assert recipe.nutrition_override is False
        # 200 g at 3/28/0.3 per 100 g -> 6/56/0.6; (6+56)*4 + 0.6*9 = 253.
        assert recipe.calories == 253
        assert recipe.carbs == 56.0


def test_edit_recipe_keeps_manual_nutrition_when_override_set(client, app, make_recipe):
    from models import Recipe, db

    recipe_id = make_recipe("Manuell bleibt")
    with app.app_context():
        cat_id = db.session.get(Recipe, recipe_id).category_id

    form = _base_recipe_form(cat_id, **{
        "nutrition_override": "1", "protein": "77", "carbs": "7", "fat": "7",
        "ing_name[]": [""], "ing_amount[]": [""], "ing_unit[]": [""], "ing_category[]": [""],
    })
    client.post(f"/edit-recipe/{recipe_id}", data=form, follow_redirects=True)

    with app.app_context():
        recipe = db.session.get(Recipe, recipe_id)
        assert recipe.nutrition_override is True
        # Calories are computed even with the override: (77+7)*4 + 7*9 = 399.
        assert recipe.calories == 399
