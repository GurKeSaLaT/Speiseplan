"""The lifecycle of a plan itself (create/delete) - unlike services/auth.py
(login/active plan/membership lookups) or routes/sharing.py (members/star
of a plan that ALREADY exists), this module is about the plan as a whole.

Since the decoupling of accounts from plans, a user no longer automatically
gets exactly one plan - they create their own via /plan/create
(routes/plans.py), as many as they like. create_plan()/delete_plan() are
bundled here because both touch the same category logic (seeding or taking
over categories) and are reused from several places: create_plan() both
from the route and (via seed_default_categories()) from migrations.py: init_db()
for every plan that doesn't have its own categories yet.
"""

from models import (
    Category, ExtraShoppingItem, IngredientAlias, IngredientNutrition,
    AppSettings, PendingPlanInvite, Plan, PlanDay, PlanDaySide, PlanMembership,
    Recipe, RecipePlanLink, db,
)

# A sensible base set of categories, so a new plan doesn't start with an
# empty category list (and thus unusable automatic planning) - see
# seed_default_categories() below.
DEFAULT_CATEGORIES = ["Fleisch", "Fisch", "Vegetarisch", "Vegan", "Nudeln/Pasta", "Suppe/Eintopf", "Schnelle Küche"]


def seed_default_categories(plan_id):
    """Creates DEFAULT_CATEGORIES for plan_id, unless it already has ANY
    category of its own - custom categories added or renamed later are
    therefore never overwritten or recreated (the check is purely "does
    this plan already have any category at all?"). Does not commit itself -
    the caller (create_plan() or migrations.py: init_db()) decides when to
    commit."""
    if Category.query.filter_by(plan_id=plan_id).first():
        return
    for name in DEFAULT_CATEGORIES:
        db.session.add(Category(plan_id=plan_id, name=name))


def create_plan(user, name):
    """Creates a new, standalone plan for user: the plan row itself (user
    is recorded informationally as owner_user_id, see models/plan.py: Plan
    docstring - grants no special rights as a result), a PlanMembership for
    user (starred, if this is their FIRST membership ever - otherwise the
    previously starred plan stays starred, a new plan doesn't automatically
    push itself to the front), and the default categories (see
    seed_default_categories)."""
    is_first_membership = PlanMembership.query.filter_by(user_id=user.id).first() is None

    plan = Plan(name=name, owner_user_id=user.id)
    db.session.add(plan)
    db.session.flush()

    db.session.add(PlanMembership(plan_id=plan.id, user_id=user.id, is_starred=is_first_membership))
    seed_default_categories(plan.id)
    db.session.commit()
    return plan


def delete_plan(plan):
    """Deletes a plan irrevocably, along with everything it OWNS
    EXCLUSIVELY - recipes still embedded in another plan via
    RecipePlanLink are handed over to that other plan INSTEAD (new
    owner_plan_id), not deleted along with it (see Recipe docstring:
    category_id always points to a category of the owning plan - on a
    change of owner, the category must therefore also move along, otherwise
    it would be left pointing at a category that gets deleted right along
    with the plan).

    SQLite runs in this app without PRAGMA foreign_keys=ON (see
    routes/recipes/crud.py: delete_recipe() docstring) - the deletion order
    below is nonetheless deliberately chosen so that at the time of each
    individual step, no reference still needed has already vanished
    (recipes/categories BEFORE the remaining, purely plan-bound data,
    memberships, and the plan itself last of all)."""
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
    # Any still-open invitations TO this plan (models/plan.py: PendingPlanInvite)
    # would otherwise be left pointing at a plan_id that no longer exists -
    # if someone later registers with exactly that email,
    # accept_pending_invites() would otherwise create a PlanMembership for
    # an already-deleted plan.
    PendingPlanInvite.query.filter_by(plan_id=plan.id).delete()
    db.session.delete(plan)
    db.session.commit()


def accept_pending_invites(user):
    """Converts every still-open PendingPlanInvite for user.email (see the
    models/plan.py docstring there) into a real PlanMembership - called directly
    after a new account is created (routes/auth.py: register()), so that
    registering via an invite link leads immediately to plan membership,
    without the inviter having to take a second action.

    is_starred follows the same criterion as create_plan() above: starred
    if it's the user's very FIRST membership ever - with several open
    invitations, only the one processed first gets the star, the rest stay
    unstarred (analogous to a member invited manually via
    invite_member())."""
    for invite in PendingPlanInvite.query.filter_by(email=user.email).all():
        if not PlanMembership.query.filter_by(plan_id=invite.plan_id, user_id=user.id).first():
            is_first = PlanMembership.query.filter_by(user_id=user.id).first() is None
            db.session.add(PlanMembership(plan_id=invite.plan_id, user_id=user.id, is_starred=is_first))
        db.session.delete(invite)
    db.session.commit()
