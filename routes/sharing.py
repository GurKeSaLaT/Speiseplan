"""Sharing page (/manage/sharing): members and invites of the active plan,
and the user's own plans with star/overview toggles. All members have the
same full access."""

from flask import Blueprint, abort, redirect, render_template, request, session, url_for

from models import PendingPlanInvite, PlanMembership, User, db
from services.auth import EMAIL_PATTERN, current_plan, current_user
from services.mail import send_invite_email

sharing_bp = Blueprint('sharing', __name__)


@sharing_bp.route('/manage/sharing')
def sharing_view():
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
    """Known email: membership right away (starred only if it's their first,
    so everyone has a default plan). Unknown email: a pending invite that is
    applied on their first login."""
    plan = current_plan()
    if plan is None:
        abort(404)

    email = (request.form.get('email') or '').strip().lower()
    if not email or not EMAIL_PATTERN.match(email):
        return redirect(url_for('sharing.sharing_view'))

    existing = User.query.filter_by(email=email).first()
    if existing:
        if not PlanMembership.query.filter_by(plan_id=plan.id, user_id=existing.id).first():
            is_first_membership = PlanMembership.query.filter_by(user_id=existing.id).first() is None
            db.session.add(PlanMembership(plan_id=plan.id, user_id=existing.id, is_starred=is_first_membership))
            db.session.commit()
    else:
        if not PendingPlanInvite.query.filter_by(plan_id=plan.id, email=email).first():
            db.session.add(PendingPlanInvite(plan_id=plan.id, email=email))
            db.session.commit()
        send_invite_email(email, plan.name, url_for('plan.index', _external=True))

    return redirect(url_for('sharing.sharing_view'))


@sharing_bp.route('/manage/sharing/invite/<int:invite_id>/cancel', methods=['POST'])
def cancel_invite(invite_id):
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
    """The owner can't be removed, so no plan ends up without access."""
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
    """Leave any of one's own plans (not just the active one). Owners delete
    the plan instead."""
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
    user = current_user()
    membership = PlanMembership.query.filter_by(plan_id=plan_id, user_id=user.id).first()
    if membership is None:
        abort(404)

    membership.show_in_week_overview = not membership.show_in_week_overview
    db.session.commit()
    return redirect(request.referrer or url_for('sharing.sharing_view'))


@sharing_bp.route('/manage/sharing/star/<int:plan_id>', methods=['POST'])
def star_plan(plan_id):
    """Unstars the user's other plans in the same transaction (one star max)."""
    user = current_user()
    membership = PlanMembership.query.filter_by(plan_id=plan_id, user_id=user.id).first()
    if membership is None:
        abort(404)

    PlanMembership.query.filter_by(user_id=user.id).update({PlanMembership.is_starred: False})
    membership.is_starred = True
    db.session.commit()
    return redirect(request.referrer or url_for('sharing.sharing_view'))
