"""Self-service management of the user's own account (change UI language,
delete account) - see routes/account.py for the associated routes.

Unlike services/auth.py (identity/session/active plan) and
services/plans.py (the lifecycle of A SINGLE plan), this module is about
the user themselves as an object that can be changed or dissolved
entirely. Name/email are no longer changeable here - they're synced from
Authelia on every request instead (see services/auth.py: current_user())
- and there's no password to change anymore (see services/auth.py module
docstring).
"""

# lazy_gettext (not gettext): this module's functions are also called
# directly from tests without a real Flask request context (see
# tests/test_services_accounts.py) - gettext() requires request context to
# resolve the active locale immediately, lazy_gettext() defers that until
# the string is actually rendered/stringified, so it works either way.
from flask_babel import lazy_gettext as _l

from models import PlanMembership, db
from services.plans import delete_plan

# The languages this app ships a UI for (see app.py: get_locale()) - kept
# here rather than in models/user.py since it's a validation concern of the
# language form, not part of the User schema itself.
SUPPORTED_LANGUAGES = ('en', 'de')


def update_language(user, language):
    """Changes the UI language (User.language, see app.py: get_locale()) -
    the only account setting left that's actually an app-level preference
    rather than an Authelia-owned identity fact. Returns (True, None) on
    success, otherwise (False, error text) - only commits on success."""
    if language not in SUPPORTED_LANGUAGES:
        return False, _l('Please choose a valid language.')

    user.language = language
    db.session.commit()
    return True, None


def delete_account(user):
    """Deletes the user's own account irrevocably, along with everything
    that becomes orphaned AS A RESULT. For each of the user's plan
    memberships:

    - If they are the ONLY remaining member, the whole plan disappears
      with them (services/plans.py: delete_plan() - already takes care of
      everything needed there, including recipes still linked elsewhere,
      which doesn't apply here though since there's no one left who could
      own them).
    - If there are OTHER members, the plan remains for them - only the
      user's own membership is removed. If the user was its (purely
      informational, see models/plan.py: Plan docstring) owner, that title
      passes to a remaining member, so the plan isn't left without one at
      all."""
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
