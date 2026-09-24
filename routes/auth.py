"""Switching the active plan (see services/auth.py: current_plan() for the
resolution order). Login/registration no longer live here - since
2026-09-24 identity comes entirely from Authelia in front of the reverse
proxy (see services/auth.py module docstring); this blueprint's name and
URL prefix ("/plan/switch/...") predate that change and were kept as-is
to avoid an unrelated churn of every url_for('auth.switch_plan') call
site."""

from datetime import date

from flask import Blueprint, redirect, session, url_for

from models import PlanMembership
from services.auth import current_user
from services.planning import friday_of

auth_bp = Blueprint('auth', __name__)


@auth_bp.route('/plan/switch/<int:plan_id>', methods=['POST'])
def switch_plan(plan_id):
    """Switches the active plan of the logged-in user (see
    templates/base.html: the plan list in the sidebar) - only allowed if a
    membership for this plan actually exists, otherwise
    session['active_plan_id'] stays unchanged (no error needed: a user
    without access doesn't even see the other plan in the rail menu in the
    first place, a manually crafted request here simply has no effect).

    ALWAYS redirects to that plan's own interactive week view for the
    CURRENT calendar week (routes/plan/pages.py: week_view()) - not back
    to request.referrer. "/" is the cross-plan read-only summary
    (routes/plan/pages.py: index()), a different page entirely; jumping
    there after a sidebar plan pick would just show the same summary
    again with nothing visibly changed except the highlight. Redirecting
    back to an arbitrary referring "settings" page (categories/units/
    ingredient aliasing/nutrition, recipe edit-list) would also be wrong
    whenever that page still carried the PREVIOUS plan's ?plan_id= in its
    URL (see services/auth.py: selected_plan_id(), which prefers an
    explicit ?plan_id= over the just-switched active plan) - it would
    silently keep showing the old plan's content there too. Always
    landing on the interactive calendar avoids both cases."""
    user = current_user()
    if user is not None and PlanMembership.query.filter_by(plan_id=plan_id, user_id=user.id).first():
        session['active_plan_id'] = plan_id
    start = friday_of(date.today())
    return redirect(url_for('plan.week_view', start_date=start.isoformat(), plan_id=plan_id))
