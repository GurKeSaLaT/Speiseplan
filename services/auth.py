"""Identity via Authelia, and the active plan.

The app has no login of its own: Authelia authenticates in front of the
SWAG/nginx reverse proxy, which passes the identity as request headers.

SECURITY ASSUMPTION: the app must only be reachable through that proxy.
nginx overwrites any client-sent Remote-* headers, but the app itself does
not verify them - exposed directly, anyone could set them and act as
anyone.
"""

import os
import re
from datetime import timedelta

from flask import g, request, session

from models import PlanMembership, User, db
from services.plans import accept_pending_invites

# Sanity check only (a trusted header is not validated for hostility).
# Also used to validate invite addresses.
EMAIL_PATTERN = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')

# SWAG's authelia snippet defaults; overridable for other proxies or local dev.
AUTHELIA_EMAIL_HEADER = os.environ.get('AUTHELIA_EMAIL_HEADER', 'Remote-Email')
AUTHELIA_NAME_HEADER = os.environ.get('AUTHELIA_NAME_HEADER', 'Remote-Name')

# Lifetime of the Flask session, which only remembers the active plan.
SESSION_LIFETIME = timedelta(days=30)


def current_user():
    """The request's user from the identity headers, cached per request.
    None without a valid header. A new email is auto-provisioned (and gets
    its pending invites); a known user's name is synced from Authelia."""
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
    """The session's active plan if the user is still a member, else the
    starred plan, else any membership; None without user or plan. Written
    back to the session."""
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
    """Starred plan first, then by name."""
    memberships = PlanMembership.query.filter_by(user_id=user.id).all()
    memberships.sort(key=lambda m: (not m.is_starred, m.plan.name))
    return memberships


def user_has_plan_access(user, plan_id):
    return PlanMembership.query.filter_by(plan_id=plan_id, user_id=user.id).first() is not None


def selected_plan_id(request_args, user):
    """?plan_id= if the user is a member (pages with their own plan tabs),
    else the active plan - a forged id never grants access."""
    requested = request_args.get('plan_id', type=int)
    if requested is not None:
        membership = PlanMembership.query.filter_by(plan_id=requested, user_id=user.id).first()
        if membership is not None:
            return requested
    plan = current_plan()
    return plan.id if plan else None


def default_plan_id(request_args, user):
    """Like selected_plan_id(), but falls back to the starred plan rather
    than the active one - a predictable default, e.g. for new recipes."""
    requested = request_args.get('plan_id', type=int)
    if requested is not None:
        membership = PlanMembership.query.filter_by(plan_id=requested, user_id=user.id).first()
        if membership is not None:
            return requested
    starred = PlanMembership.query.filter_by(user_id=user.id, is_starred=True).first()
    return starred.plan_id if starred else None
