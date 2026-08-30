"""Tests für services/plans.py: Plan-Lebenszyklus (anlegen/löschen) -
seit Pläne von Accounts entkoppelt sind, der zentrale Ort, an dem ein
Nutzer sich zusätzliche, eigene Pläne anlegt bzw. wieder loswird."""


def test_create_plan_seeds_categories_and_stars_first_membership(app, make_user):
    from models import Category, Plan, PlanMembership

    with app.app_context():
        from models import User
        from services.plans import create_plan

        user_id, _ = make_user("Erstplan-Nutzer")
        user = User.query.get(user_id)
        plan = create_plan(user, "Mein neuer Plan")

        assert plan.name == "Mein neuer Plan"
        assert plan.owner_user_id == user_id
        membership = PlanMembership.query.filter_by(plan_id=plan.id, user_id=user_id).first()
        assert membership is not None
        # make_user() legt bereits eine erste, gesternte Mitgliedschaft an -
        # dieser zweite, hier neu erstellte Plan ist also NICHT die erste
        # Mitgliedschaft des Nutzers und bleibt entsprechend unbesternt.
        assert membership.is_starred is False
        assert Category.query.filter_by(plan_id=plan.id).count() == 7


def test_create_plan_stars_a_users_very_first_membership(app):
    from models import PlanMembership, User, db
    from services.auth import hash_password
    from services.plans import create_plan

    with app.app_context():
        user = User(username="Blanko", password_hash=hash_password("test"))
        db.session.add(user)
        db.session.commit()

        plan = create_plan(user, "Erster Plan")
        membership = PlanMembership.query.filter_by(plan_id=plan.id, user_id=user.id).first()
        assert membership.is_starred is True


def test_delete_plan_removes_exclusively_owned_recipe(app, make_recipe, test_plan_id):
    from models import Category, Plan, Recipe
    from services.plans import delete_plan

    recipe_id = make_recipe("Nur hier")
    with app.app_context():
        plan = Plan.query.get(test_plan_id)
        delete_plan(plan)

        assert Recipe.query.get(recipe_id) is None
        assert Plan.query.get(test_plan_id) is None
        assert Category.query.filter_by(plan_id=test_plan_id).count() == 0


def test_delete_plan_transfers_linked_recipe_to_remaining_plan(app, client, make_recipe, make_user):
    """Ein Rezept, das der gelöschte Plan besitzt, aber zusätzlich in einen
    anderen Plan eingebunden ist (RecipePlanLink), wird NICHT gelöscht,
    sondern bekommt automatisch diesen anderen Plan als neuen Eigentümer -
    inklusive einer zu seiner alten Kategorie passenden neuen Kategorie im
    Zielplan (siehe services/plans.py: delete_plan())."""
    from models import Category, Plan, PlanMembership, Recipe, RecipePlanLink, db

    recipe_id = make_recipe("Geteiltes Gericht", category_id=None)
    other_user_id, other_plan_id = make_user("Andere")
    with app.app_context():
        db.session.add(PlanMembership(plan_id=other_plan_id, user_id=client.user_id, is_starred=False))
        db.session.commit()
        old_category_name = Recipe.query.get(recipe_id).category.name
        db.session.add(RecipePlanLink(recipe_id=recipe_id, plan_id=other_plan_id))
        db.session.commit()

    with app.app_context():
        from services.plans import delete_plan
        plan = Plan.query.get(client.plan_id)
        delete_plan(plan)

        recipe = Recipe.query.get(recipe_id)
        assert recipe is not None
        assert recipe.owner_plan_id == other_plan_id
        assert recipe.category.name == old_category_name
        assert recipe.category.plan_id == other_plan_id
        # Der jetzt überflüssige Link auf den neuen Eigentümer ist weg.
        assert RecipePlanLink.query.filter_by(recipe_id=recipe_id, plan_id=other_plan_id).first() is None
        assert Plan.query.get(client.plan_id) is None


def test_delete_plan_removes_settings_and_memberships(app, client, make_category):
    from models import AppSettings, Category, Plan, PlanMembership
    from services.ingredient_aliases import set_alias
    from services.nutrition import set_nutrition
    from services.settings import update_display_units

    make_category("Wird gelöscht")
    with app.app_context():
        update_display_units(client.plan_id, "kg", "l")
        set_alias(client.plan_id, "Spaghetti", "Nudeln")
        set_nutrition(client.plan_id, "Nudeln", reference_unit="g", protein=1, carbs=1, fat=1)

    with app.app_context():
        from services.plans import delete_plan
        from models import IngredientAlias, IngredientNutrition

        plan = Plan.query.get(client.plan_id)
        delete_plan(plan)

        assert AppSettings.query.filter_by(plan_id=client.plan_id).count() == 0
        assert Category.query.filter_by(plan_id=client.plan_id).count() == 0
        assert IngredientAlias.query.filter_by(plan_id=client.plan_id).count() == 0
        assert IngredientNutrition.query.filter_by(plan_id=client.plan_id).count() == 0
        assert PlanMembership.query.filter_by(plan_id=client.plan_id).count() == 0
