"""Identity (via Authelia) and access to the "active plan".

Since 2026-09-24 this app no longer has its own login/registration: it runs
behind Authelia (a forward-auth check baked into the SWAG/nginx reverse
proxy in front of the home server) - Authelia handles authentication
entirely, and nginx's auth_request integration attaches the outcome to
every request as a fixed pair of headers (see AUTHELIA_EMAIL_HEADER/
AUTHELIA_NAME_HEADER below). This app never sees a password and performs
NO credential check itself - it only trusts whatever identity the reverse
proxy attaches to the request, exactly the same trust boundary the app
previously placed on its own signed Flask session.

SECURITY ASSUMPTION: this only holds as long as the app is reachable
EXCLUSIVELY through that proxy chain (SWAG -> Authelia auth_request ->
this app). nginx's proxy_set_header OVERWRITES any Remote-* header a
client might try to send itself, so a request can't forge its own
identity as long as it actually passes through nginx - but this app adds
no additional check of its own for that. If it were ever exposed directly
(bypassing the proxy), anyone could set these headers themselves and
"log in" as anyone.

current_user() auto-provisions a User row the first time a given email is
seen (Authelia already decided this person may authenticate - there's no
separate registration step anymore) and keeps the display name in sync
with Authelia's on every request. current_plan() is unchanged in spirit:
which PLAN is active is an app-level preference, not an identity concern,
and still lives in the Flask session (session['active_plan_id'], set here
and via routes/auth.py: switch_plan())."""

import os
import re
from datetime import timedelta

from flask import g, request, session

from models import PlanMembership, User, db
from services.plans import accept_pending_invites

# Rough sanity check on the email header value (a misconfigured/empty
# header should be treated as "not authenticated", not crash on a
# malformed value) - not a defense against a hostile header, since a
# header that reaches this app at all is already trusted (see the
# SECURITY ASSUMPTION above). Also still used to validate the email a
# plan is shared TO (routes/sharing.py: invite_member()).
EMAIL_PATTERN = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')

# Which request headers carry the authenticated identity, attached by
# nginx's auth_request integration with Authelia - matches the
# LinuxServer.io SWAG "authelia-server.conf" snippet's default
# proxy_set_header names, which is what's actually deployed in front of
# this app. Overridable via environment variable only for a differently
# named proxy setup or for local development without the real proxy chain
# in front (see README.md: Setup).
AUTHELIA_EMAIL_HEADER = os.environ.get('AUTHELIA_EMAIL_HEADER', 'Remote-Email')
AUTHELIA_NAME_HEADER = os.environ.get('AUTHELIA_NAME_HEADER', 'Remote-Name')

# How long the active-plan-switch preference (session['active_plan_id'],
# see current_plan() below) survives in the browser without a fresh
# request - set generously since these are private devices on one's own
# home network. Independent of the Authelia session itself, which this
# app doesn't manage at all.
SESSION_LIFETIME = timedelta(days=30)


def current_user():
    """Resolves the authenticated user for the CURRENT request from the
    Authelia identity headers (None if the header is missing/malformed -
    e.g. a request that somehow reached the app without going through the
    proxy) - loaded/created at most once per request, cached via flask.g
    (g only lives for the duration of ONE request).

    An email seen for the first time is auto-provisioned as a brand new
    User (Authelia already decided this person may authenticate) and any
    pending plan invite for that email is applied immediately (see
    services/plans.py: accept_pending_invites() - previously done in
    routes/auth.py: register(), now the natural place for it since this
    IS the moment a new identity first shows up). An already-known user
    instead gets their display name re-synced from AUTHELIA_NAME_HEADER
    whenever it changed, so a rename in Authelia/the identity provider
    shows up here automatically - there's no manual profile edit for the
    name anymore."""
    if hasattr(g, '_current_user'):
        return g._current_user

    email = (request.headers.get(AUTHELIA_EMAIL_HEADER) or '').strip().lower()
    if not email or not EMAIL_PATTERN.match(email):
        g._current_user = None
        return None

    display_name = (request.headers.get(AUTHELIA_NAME_HEADER) or '').strip() or email.split('@')[0]

    user = User.query.filter_by(email=email).first()
    if user is None:
        user = User(name=display_name, email=email)
        db.session.add(user)
        db.session.flush()
        accept_pending_invites(user)
        db.session.commit()
    elif user.name != display_name:
        user.name = display_name
        db.session.commit()

    g._current_user = user
    return user


def current_plan():
    """Resolves the currently authenticated user's active plan (None if
    nobody is authenticated, or the user - practically never the case, see
    migrations.py: init_db() - is not yet a member of any plan at all).

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
        session.permanent = True
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
    routes/recipes/crud.py: recipe_create_view()).

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
