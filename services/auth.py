"""Login/session management and access to the "active plan".

Deliberately implemented without an extra package such as Flask-Login: the
app has so far gotten by with four dependencies (see requirements.txt), and
everything needed - a signed session plus password hashing - is already
provided by Flask/Werkzeug (app.py: SECRET_KEY signs the same session that
CSRFProtect also uses).

current_user()/current_plan() ONLY read from the already-set Flask session
(session['user_id']/session['active_plan_id']) - actually setting these
values is handled exclusively by routes/auth.py on login/plan switch.
login_required() exists as a decorator, but this app does not apply it
per-route - app.py: require_login() instead protects all routes globally
via a single @app.before_request hook, except the login page/static files
(considerably less error-prone than risking forgetting a single route's
@login_required)."""

import re
from functools import wraps

from flask import g, redirect, session, url_for, request
from werkzeug.security import check_password_hash, generate_password_hash

from models import PlanMembership, User

# Rough format check for email addresses (registration, email invitation,
# profile email change) - no new package like email-validator, in keeping
# with the existing lean dependency style (see module docstring above).
# Only checks the rough shape ("something@something.something"), not
# actual deliverability. ONE shared place instead of a copy per route file.
EMAIL_PATTERN = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')


def hash_password(raw_password):
    return generate_password_hash(raw_password)


def verify_password(user, raw_password):
    return check_password_hash(user.password_hash, raw_password)


def current_user():
    """Loads the logged-in user (or None, if there is no valid session) -
    loaded only once per request, cached via flask.g (g only lives for the
    duration of ONE request, no caching across requests needed/wanted)."""
    if 'user_id' not in session:
        return None
    if not hasattr(g, '_current_user'):
        g._current_user = User.query.get(session['user_id'])
        # The user ID in the session no longer exists (e.g. a session from
        # a test account that has since been deleted) - clean up the
        # session instead of running into a dead end on every further
        # access.
        if g._current_user is None:
            session.clear()
    return g._current_user


def current_plan():
    """Resolves the logged-in user's currently active plan (None if no one
    is logged in, or the user - practically never the case, see app.py:
    init_db() - is not yet a member of any plan at all).

    Order: 1. the plan last chosen via /plan/switch/<id>
    (session['active_plan_id']), provided the user is still a member there
    (could have changed, e.g. if they were removed in the meantime) -
    2. otherwise the starred plan (see PlanMembership.is_starred) -
    3. otherwise whichever (the first) existing membership. The result is
    written back into the session so that subsequent requests hit case 1
    directly, without having to look up the star again."""
    user = current_user()
    if user is None:
        return None
    if hasattr(g, '_current_plan'):
        return g._current_plan

    active_id = session.get('active_plan_id')
    membership = None
    if active_id is not None:
        membership = PlanMembership.query.filter_by(plan_id=active_id, user_id=user.id).first()
    if membership is None:
        membership = PlanMembership.query.filter_by(user_id=user.id, is_starred=True).first()
    if membership is None:
        membership = PlanMembership.query.filter_by(user_id=user.id).first()

    g._current_plan = membership.plan if membership else None
    if g._current_plan is not None:
        session['active_plan_id'] = g._current_plan.id
    return g._current_plan


def user_plan_memberships(user):
    """All plans user has access to (own + invited, see models/plan.py:
    PlanMembership) - starred plan first, then alphabetically by plan name.
    Shared by app.py: inject_current_user_and_plans() (sidebar navigation)
    and the tab switchers of the "settings" pages (routes/categories.py,
    routes/settings.py) - both should show exactly the same order."""
    memberships = PlanMembership.query.filter_by(user_id=user.id).all()
    memberships.sort(key=lambda m: (not m.is_starred, m.plan.name))
    return memberships


def user_has_plan_access(user, plan_id):
    """Whether user is a member of plan_id (see models/plan.py: PlanMembership) -
    the plain ownership check for routes that need to check a user's access
    against an object based on its own plan_id (as opposed to a query
    parameter like selected_plan_id() below), e.g. before a category/recipe
    is deleted/modified by its ID."""
    return PlanMembership.query.filter_by(plan_id=plan_id, user_id=user.id).first() is not None


def selected_plan_id(request_args, user):
    """Resolves which plan should be shown/edited for A SINGLE request to
    the "settings" pages (categories/units/equating ingredients/nutrition) -
    independent of the otherwise active plan (current_plan()), since these
    pages have their own tab switcher (see templates: the tab strip links
    with ?plan_id=<id>).

    Takes request_args (a mapping like flask.request.args) instead of
    importing flask.request directly, so that this function remains
    testable independent of the request context. A missing/invalid/foreign
    plan_id parameter falls back to the active plan (services/auth.py:
    current_plan()) - a manipulated query parameter can therefore never
    grant access to a plan the user isn't already a member of anyway."""
    requested = request_args.get('plan_id', type=int)
    if requested is not None:
        membership = PlanMembership.query.filter_by(plan_id=requested, user_id=user.id).first()
        if membership is not None:
            return requested
    plan = current_plan()
    return plan.id if plan else None


def default_plan_id(request_args, user):
    """Like selected_plan_id() above (a valid ?plan_id= parameter always
    wins), but FALLS BACK to the STARRED plan instead of current_plan() -
    for forms that should deliberately always suggest the same, predictable
    default INDEPENDENT of the otherwise active plan (which, e.g. due to a
    previously visited tab, may point at a different, non-starred plan)
    (e.g. "which plan does a newly created recipe belong to" -
    routes/recipes.py: recipe_create_view()).

    Assumes user has at least one membership - routes that use this are
    unreachable anyway for users without any plan at all, via the zero-plan
    gate (app.py: ZERO_PLAN_ALLOWED_ENDPOINTS)."""
    requested = request_args.get('plan_id', type=int)
    if requested is not None:
        membership = PlanMembership.query.filter_by(plan_id=requested, user_id=user.id).first()
        if membership is not None:
            return requested
    starred = PlanMembership.query.filter_by(user_id=user.id, is_starred=True).first()
    return starred.plan_id if starred else None


def login_required(view):
    """Not actively used in routing (see module docstring - app.py:
    require_login() handles this globally) - still present as a standalone
    decorator in case a single route needs to be protected differently from
    the global gate (e.g. within an otherwise open blueprint)."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        if current_user() is None:
            return redirect(url_for('auth.login', next=request.path))
        return view(*args, **kwargs)
    return wrapped
