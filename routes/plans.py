"""Creating and deleting an entire plan (see services/plans.py for the
actual logic) - unlike routes/sharing.py (managing members/star of ONE
already-existing plan), this is about the plan as a whole.

Since plans were decoupled from accounts (no more automatic plan per
user), "having no plan at all" is a normal, reachable state (e.g. right
after deleting one's last own plan) - see app.py: require_login() for the
global zero-plan gate, which keeps create_plan() on its own allowlist for
that reason."""

from flask import Blueprint, abort, redirect, request, url_for, session

from services.auth import current_user, user_has_plan_access
from services.plans import create_plan, delete_plan
from models import Plan, db

plans_bp = Blueprint('plans', __name__)


@plans_bp.route('/plan/create', methods=['POST'])
def create():
    """Creates a new, own plan for the logged-in user and switches to it
    right away (session['active_plan_id']) - an empty/missing name is
    silently ignored (no error text needed, the name field in the modal
    is already marked "required", see templates/base.html)."""
    name = (request.form.get('name') or '').strip()
    if not name:
        return redirect(url_for('plan.index'))

    plan = create_plan(current_user(), name)
    session['active_plan_id'] = plan.id
    return redirect(url_for('plan.index'))


@plans_bp.route('/plan/<int:plan_id>/delete', methods=['POST'])
def delete(plan_id):
    """Deletes a plan irrevocably (see services/plans.py:
    delete_plan) - any member may do this, not just whoever originally
    created it (see models/plan.py: Plan docstring, owner_user_id doesn't grant
    any special rights). If plan_id was the currently active plan, the
    session marker is removed, so that the next current_plan() call
    resolves freshly to a remaining plan (or None), instead of pointing to
    an ID that no longer exists."""
    user = current_user()
    if not user_has_plan_access(user, plan_id):
        abort(404)
    plan = Plan.query.get_or_404(plan_id)

    delete_plan(plan)
    if session.get('active_plan_id') == plan_id:
        session.pop('active_plan_id', None)
    return redirect(url_for('plan.index'))


@plans_bp.route('/plan/<int:plan_id>/rename', methods=['POST'])
def rename(plan_id):
    """Renames a plan - any member may do this (same reasoning as with
    delete() above: owner_user_id doesn't grant any special rights). An
    empty name is ignored, the previous one then remains unchanged (no
    error text needed, the name field in the modal is already marked
    "required", see templates/sharing.html)."""
    user = current_user()
    if not user_has_plan_access(user, plan_id):
        abort(404)
    plan = Plan.query.get_or_404(plan_id)

    name = (request.form.get('name') or '').strip()
    if name:
        plan.name = name
        db.session.commit()
    return redirect(url_for('sharing.sharing_view'))
