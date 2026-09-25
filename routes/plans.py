"""Creating, deleting and renaming plans. Having no plan at all is a valid
state, so create stays reachable (app.py: ZERO_PLAN_ALLOWED_ENDPOINTS)."""

from flask import Blueprint, abort, redirect, request, url_for, session

from services.auth import current_user, user_has_plan_access
from services.plans import create_plan, delete_plan
from models import Plan, db

plans_bp = Blueprint('plans', __name__)


@plans_bp.route('/plan/create', methods=['POST'])
def create():
    """Switches to the new plan; an empty name is ignored."""
    name = (request.form.get('name') or '').strip()
    if not name:
        return redirect(url_for('plan.index'))

    plan = create_plan(current_user(), name)
    session['active_plan_id'] = plan.id
    return redirect(url_for('plan.index'))


@plans_bp.route('/plan/<int:plan_id>/delete', methods=['POST'])
def delete(plan_id):
    """Any member may delete (the owner has no extra rights)."""
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
    """Any member may rename; an empty name is ignored."""
    user = current_user()
    if not user_has_plan_access(user, plan_id):
        abort(404)
    plan = Plan.query.get_or_404(plan_id)

    name = (request.form.get('name') or '').strip()
    if name:
        plan.name = name
        db.session.commit()
    return redirect(url_for('sharing.sharing_view'))
