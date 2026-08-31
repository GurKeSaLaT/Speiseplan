"""Sharing/star management for weekly plans (/manage/sharing): who is a
member of the currently active plan, inviting/removing further users, and
which of one's own plans is currently starred (see models.py:
Plan/PlanMembership as well as services/auth.py: current_plan()).

All members of a plan have full read/write access - there is no
role/permission distinction to manage here, only plain membership (who
belongs to it) and the per-user star (which plan is currently "the
default one").
"""

from flask import Blueprint, abort, redirect, render_template, request, session, url_for

from models import PendingPlanInvite, PlanMembership, User, db
from services.auth import EMAIL_PATTERN, current_plan, current_user
from services.mail import send_invite_email

sharing_bp = Blueprint('sharing', __name__)


@sharing_bp.route('/manage/sharing')
def sharing_view():
    """Shows the members of the currently active plan (with a remove
    option, except for its owner - see remove_member()), an email field
    for inviting (see invite_member()), the still-open invites to
    not-yet-registered addresses, and the list of ALL plans of the
    logged-in user with a star toggle."""
    plan = current_plan()
    if plan is None:
        abort(404)

    member_ids = {m.user_id for m in PlanMembership.query.filter_by(plan_id=plan.id).all()}
    members = User.query.filter(User.id.in_(member_ids)).order_by(User.name).all() if member_ids else []
    pending_invites = PendingPlanInvite.query.filter_by(plan_id=plan.id).order_by(PendingPlanInvite.invited_at).all()

    user = current_user()
    own_memberships = PlanMembership.query.filter_by(user_id=user.id).all()
    own_memberships.sort(key=lambda m: (not m.is_starred, m.plan.name))

    return render_template(
        'sharing.html', plan=plan, members=members, pending_invites=pending_invites,
        own_memberships=own_memberships,
    )


@sharing_bp.route('/manage/sharing/invite', methods=['POST'])
def invite_member():
    """Shares the currently active plan with an entered email address: if
    an account already exists for it, a PlanMembership with full access
    like any other member is created immediately (without an invite/
    confirmation workflow). If none exists yet, a PendingPlanInvite is
    created instead (see the models.py docstring there) and an invite is
    "sent" (services/mail.py: send_invite_email() - currently only
    logged, the link additionally appears directly on this page, see
    templates/sharing.html: "Pending invites"). Not starred, or only
    possibly starred upon registration (services/plans.py:
    accept_pending_invites()) - otherwise the invited user decides for
    themselves whether to make this plan their default plan."""
    plan = current_plan()
    if plan is None:
        abort(404)

    email = (request.form.get('email') or '').strip().lower()
    if not email or not EMAIL_PATTERN.match(email):
        return redirect(url_for('sharing.sharing_view'))

    existing = User.query.filter_by(email=email).first()
    if existing:
        if not PlanMembership.query.filter_by(plan_id=plan.id, user_id=existing.id).first():
            db.session.add(PlanMembership(plan_id=plan.id, user_id=existing.id, is_starred=False))
            db.session.commit()
    else:
        if not PendingPlanInvite.query.filter_by(plan_id=plan.id, email=email).first():
            db.session.add(PendingPlanInvite(plan_id=plan.id, email=email))
            db.session.commit()
        send_invite_email(email, plan.name, url_for('auth.register', email=email, _external=True))

    return redirect(url_for('sharing.sharing_view'))


@sharing_bp.route('/manage/sharing/invite/<int:invite_id>/cancel', methods=['POST'])
def cancel_invite(invite_id):
    """Withdraws a still-open invite to an unregistered email address -
    counterpart to remove_member() for actual members. Must belong to the
    currently active plan, otherwise 404 (same pattern as the other
    ownership checks in this app)."""
    plan = current_plan()
    if plan is None:
        abort(404)

    invite = PendingPlanInvite.query.get_or_404(invite_id)
    if invite.plan_id != plan.id:
        abort(404)

    db.session.delete(invite)
    db.session.commit()
    return redirect(url_for('sharing.sharing_view'))


@sharing_bp.route('/manage/sharing/remove/<int:user_id>', methods=['POST'])
def remove_member(user_id):
    """Removes a member from the currently active plan - except its owner
    (Plan.owner_user_id), who always remains a member, so that no plan is
    left without any access at all. If a user thereby removes themselves
    from a plan that happened to be their active one, the next
    current_plan() call automatically resolves to a different (starred
    or first remaining) plan - no special handling needed here."""
    plan = current_plan()
    if plan is None:
        abort(404)
    if user_id == plan.owner_user_id:
        abort(400)

    PlanMembership.query.filter_by(plan_id=plan.id, user_id=user_id).delete()
    db.session.commit()
    return redirect(url_for('sharing.sharing_view'))


@sharing_bp.route('/manage/sharing/leave/<int:plan_id>', methods=['POST'])
def leave_plan(plan_id):
    """Removes ONE'S OWN membership on plan_id - the counterpart to
    remove_member() above (which removes SOMEONE ELSE), here for oneself
    and deliberately independent of the currently active plan
    (current_plan()): the "My plans" list on sharing.html shows ALL of
    one's own plans, not just the active one, so leaving must work
    individually for each of them, regardless of which one is currently
    active.

    The OWNER of a plan (Plan.owner_user_id) CANNOT leave it this way -
    delete_plan() (routes/plans.py) exists for that, which correctly
    hands the plan over to another member when there are several, instead
    of simply leaving it without an owner."""
    user = current_user()
    membership = PlanMembership.query.filter_by(plan_id=plan_id, user_id=user.id).first()
    if membership is None:
        abort(404)
    plan = membership.plan
    if plan.owner_user_id == user.id:
        abort(400)

    db.session.delete(membership)
    db.session.commit()
    if session.get('active_plan_id') == plan_id:
        session.pop('active_plan_id', None)
    return redirect(url_for('sharing.sharing_view'))


@sharing_bp.route('/manage/sharing/overview-toggle/<int:plan_id>', methods=['POST'])
def toggle_overview(plan_id):
    """Toggles PlanMembership.show_in_week_overview for ONE'S OWN
    membership on plan_id (see the models.py docstring there - a flag
    that applies purely per user, analogous to is_starred) - never
    affects the membership of another user of the same, possibly shared,
    plan."""
    user = current_user()
    membership = PlanMembership.query.filter_by(plan_id=plan_id, user_id=user.id).first()
    if membership is None:
        abort(404)

    membership.show_in_week_overview = not membership.show_in_week_overview
    db.session.commit()
    return redirect(request.referrer or url_for('sharing.sharing_view'))


@sharing_bp.route('/manage/sharing/star/<int:plan_id>', methods=['POST'])
def star_plan(plan_id):
    """Marks plan_id as the one starred plan of the logged-in user (opens
    automatically after login from now on, appears at the top of the
    navigation) - to do so, first unstars all other memberships of the
    same user within the same transaction, so that never more than one
    is starred at the same time (see models.py: PlanMembership
    docstring)."""
    user = current_user()
    membership = PlanMembership.query.filter_by(plan_id=plan_id, user_id=user.id).first()
    if membership is None:
        abort(404)

    PlanMembership.query.filter_by(user_id=user.id).update({PlanMembership.is_starred: False})
    membership.is_starred = True
    db.session.commit()
    return redirect(request.referrer or url_for('sharing.sharing_view'))
