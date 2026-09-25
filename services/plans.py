"""Plan lifecycle: create, delete, and accepting pending invites."""

from models import (
    Category, ExtraShoppingItem, IngredientAlias, IngredientNutrition,
    AppSettings, PendingPlanInvite, Plan, PlanDay, PlanDaySide, PlanMembership,
    Recipe, RecipePlanLink, db,
)

DEFAULT_CATEGORIES = ["Fleisch", "Fisch", "Vegetarisch", "Vegan", "Nudeln/Pasta", "Suppe/Eintopf", "Schnelle Küche"]


def seed_default_categories(plan_id):
    """Only for plans without any category yet; the caller commits."""
    if Category.query.filter_by(plan_id=plan_id).first():
        return
    for name in DEFAULT_CATEGORIES:
        db.session.add(Category(plan_id=plan_id, name=name))


def create_plan(user, name):
    """Starred only if it's the user's first membership."""
    is_first_membership = PlanMembership.query.filter_by(user_id=user.id).first() is None

    plan = Plan(name=name, owner_user_id=user.id)
    db.session.add(plan)
    db.session.flush()

    db.session.add(PlanMembership(plan_id=plan.id, user_id=user.id, is_starred=is_first_membership))
    seed_default_categories(plan.id)
    db.session.commit()
    return plan


def delete_plan(plan):
    """Deletes the plan and everything it exclusively owns. Recipes still
    linked into another plan are handed over to that plan instead, together
    with their category (recreated there if missing). SQLite foreign keys
    aren't enforced, so the order below keeps references valid step by step.
    """
    for recipe in Recipe.query.filter_by(owner_plan_id=plan.id).all():
        links = RecipePlanLink.query.filter_by(recipe_id=recipe.id).order_by(RecipePlanLink.plan_id).all()
        if links:
            new_owner_plan_id = links[0].plan_id
            old_category_name = recipe.category.name
            new_category = Category.query.filter_by(plan_id=new_owner_plan_id, name=old_category_name).first()
            if new_category is None:
                new_category = Category(plan_id=new_owner_plan_id, name=old_category_name)
                db.session.add(new_category)
                db.session.flush()
            recipe.owner_plan_id = new_owner_plan_id
            recipe.category_id = new_category.id
            RecipePlanLink.query.filter_by(recipe_id=recipe.id, plan_id=new_owner_plan_id).delete()
        else:
            db.session.delete(recipe)

    plan_day_ids = db.session.query(PlanDay.id).filter(PlanDay.plan_id == plan.id)
    PlanDaySide.query.filter(PlanDaySide.plan_day_id.in_(plan_day_ids)).delete(synchronize_session=False)
    PlanDay.query.filter_by(plan_id=plan.id).delete()

    ExtraShoppingItem.query.filter_by(plan_id=plan.id).delete()
    AppSettings.query.filter_by(plan_id=plan.id).delete()
    IngredientAlias.query.filter_by(plan_id=plan.id).delete()
    IngredientNutrition.query.filter_by(plan_id=plan.id).delete()
    Category.query.filter_by(plan_id=plan.id).delete()

    PlanMembership.query.filter_by(plan_id=plan.id).delete()
    # Otherwise a later first login with that email would join a deleted plan.
    PendingPlanInvite.query.filter_by(plan_id=plan.id).delete()
    db.session.delete(plan)
    db.session.commit()


def accept_pending_invites(user):
    """Turns open invites for user.email into memberships (called when a new
    user is provisioned). Only a very first membership gets starred."""
    for invite in PendingPlanInvite.query.filter_by(email=user.email).all():
        if not PlanMembership.query.filter_by(plan_id=invite.plan_id, user_id=user.id).first():
            is_first = PlanMembership.query.filter_by(user_id=user.id).first() is None
            db.session.add(PlanMembership(plan_id=invite.plan_id, user_id=user.id, is_starred=is_first))
        db.session.delete(invite)
    db.session.commit()
