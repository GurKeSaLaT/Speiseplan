"""Self-service management of the user's own account (change profile, change
password, delete account) - see routes/account.py for the associated routes.

Unlike services/auth.py (login/session/active plan) and services/plans.py
(the lifecycle of A SINGLE plan), this module is about the user themselves
as an object that can be changed or dissolved entirely.
"""

# lazy_gettext (not gettext): this module's functions are also called
# directly from tests without a real Flask request context (see
# tests/test_services_accounts.py) - gettext() requires request context to
# resolve the active locale immediately, lazy_gettext() defers that until
# the string is actually rendered/stringified, so it works either way.
from flask_babel import lazy_gettext as _l

from models import PlanMembership, User, db
from services.auth import EMAIL_PATTERN, hash_password, verify_password
from services.plans import delete_plan

# The languages this app ships a UI for (see app.py: get_locale()) - kept
# here rather than in models/user.py since it's a validation concern of the
# profile form, not part of the User schema itself.
SUPPORTED_LANGUAGES = ('en', 'de')


def update_profile(user, name, email, language):
    """Changes name (a free-form display name, no uniqueness required, see
    models/user.py: User docstring), email (the LOGIN field, so it must still be
    unique and roughly valid) and the UI language (User.language, see
    app.py: get_locale()). Returns (True, None) on success, otherwise
    (False, error text) - only commits on success."""
    name = (name or '').strip()
    email = (email or '').strip().lower()
    if not name or not email:
        return False, _l('Please provide a name and email address.')
    if not EMAIL_PATTERN.match(email):
        return False, _l('Please provide a valid email address.')
    existing = User.query.filter(User.email == email, User.id != user.id).first()
    if existing is not None:
        return False, _l('Another account already exists for this email address.')
    if language not in SUPPORTED_LANGUAGES:
        return False, _l('Please choose a valid language.')

    user.name = name
    user.email = email
    user.language = language
    db.session.commit()
    return True, None


def update_password(user, current_password, new_password):
    """Requires (unlike update_profile() above) the CURRENT password - a
    simple safeguard against a hijacked but still logged-in session (e.g.
    on a shared device), which could otherwise take over the account
    without any further hurdle."""
    if not verify_password(user, current_password or ''):
        return False, _l('Current password is incorrect.')
    if not new_password:
        return False, _l('Please provide a new password.')

    user.password_hash = hash_password(new_password)
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
