"""Switching the active plan. (Named "auth" for historical reasons; login
is Authelia's job.)"""

from datetime import date

from flask import Blueprint, redirect, session, url_for

from models import PlanMembership
from services.auth import current_user
from services.planning import friday_of

auth_bp = Blueprint('auth', __name__)


@auth_bp.route('/plan/switch/<int:plan_id>', methods=['POST'])
def switch_plan(plan_id):
    """Only switches for members. Always lands on the plan's current week -
    not the referrer, which may carry the previous plan's ?plan_id=."""
    user = current_user()
    if user is not None and PlanMembership.query.filter_by(plan_id=plan_id, user_id=user.id).first():
        session['active_plan_id'] = plan_id
    start = friday_of(date.today())
    return redirect(url_for('plan.week_view', start_date=start.isoformat(), plan_id=plan_id))
