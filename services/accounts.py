"""The user's own account: UI language and account deletion. Name and
email come from Authelia and aren't editable here."""

# lazy_gettext: also called from tests without a request context.
from flask_babel import lazy_gettext as _l

from models import PlanMembership, db
from services.plans import delete_plan

SUPPORTED_LANGUAGES = ('en', 'de')


def update_language(user, language):
    """(True, None) or (False, error message)."""
    if language not in SUPPORTED_LANGUAGES:
        return False, _l('Please choose a valid language.')

    user.language = language
    db.session.commit()
    return True, None


def delete_account(user):
    """Plans where the user is the last member are deleted; in shared plans
    only the membership goes, and ownership passes to another member."""
    for membership in list(PlanMembership.query.filter_by(user_id=user.id).all()):
        plan = membership.plan
        other_member = PlanMembership.query.filter(
            PlanMembership.plan_id == plan.id, PlanMembership.user_id != user.id
        ).first()
        if other_member is None:
            delete_plan(plan)
        else:
            if plan.owner_user_id == user.id:
                plan.owner_user_id = other_member.user_id
            db.session.delete(membership)

    db.session.delete(user)
    db.session.commit()
