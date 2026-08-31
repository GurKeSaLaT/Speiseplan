"""Login/registration/logout as well as switching the active plan
(see services/auth.py: current_plan() for the resolution order).
"""

from datetime import timedelta
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

from flask import Blueprint, redirect, render_template, request, session, url_for
from flask_babel import gettext as _

from models import PlanMembership, User, db
from services.auth import EMAIL_PATTERN, current_user, hash_password, verify_password
from services.plans import accept_pending_invites

auth_bp = Blueprint('auth', __name__)

# How long a session stays valid without a fresh login (see
# app.py: SECRET_KEY comment) - set generously since these are private
# devices on one's own home network, no desire for constant re-logins.
SESSION_LIFETIME = timedelta(days=30)


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    """Shows the login form (templates/login.html, a STANDALONE page
    without the app navigation bar - that requires a logged-in user with
    an active plan) or processes its submission.

    Users who are already logged in but still call up the login page
    (e.g. via browser history) are redirected immediately instead of
    the form being shown again. `next` (optional query argument, set by
    app.py: require_login()) leads back after a successful login to the
    page that triggered the redirect - if it is missing or, for whatever
    reason, doesn't point to an internal path, it goes to the weekly plan
    home page instead.
    """
    if current_user() is not None:
        return redirect(url_for('plan.index'))

    error = None
    if request.method == 'POST':
        email = (request.form.get('email') or '').strip().lower()
        password = request.form.get('password') or ''
        user = User.query.filter_by(email=email).first()

        if user and verify_password(user, password):
            session.clear()
            session['user_id'] = user.id
            session.permanent = True
            next_path = request.form.get('next') or ''
            destination = next_path if next_path.startswith('/') and not next_path.startswith('//') else url_for('plan.index')
            return redirect(destination)

        error = _('Email address or password is incorrect.')

    return render_template('login.html', error=error, next=request.args.get('next', ''))


@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    """Shows the registration form (templates/register.html, the same
    standalone page pattern as login.html) or processes its submission.
    Reachable via the "create account" button on the login page, or via an
    invite link (?email=<address> then only pre-fills the field, but
    doesn't change the actual assignment - that runs exclusively via the
    email address actually entered, in accept_pending_invites() below).

    After successful registration, immediately logged in (as after a normal
    login) and redirected to the weekly plan home page - lands there either
    directly in the plan received via invite (accept_pending_invites) or,
    without a matching invite, on the zero-plan landing page with the
    "create your own plan" form (see routes/plan/pages.py: week_view())."""
    if current_user() is not None:
        return redirect(url_for('plan.index'))

    error = None
    name = ''
    email = request.args.get('email', '')
    if request.method == 'POST':
        name = (request.form.get('name') or '').strip()
        email = (request.form.get('email') or '').strip().lower()
        password = request.form.get('password') or ''
        confirm_password = request.form.get('confirm_password') or ''

        if not name or not email or not password:
            error = _('Please provide name, email address, and password.')
        elif password != confirm_password:
            error = _('Passwords do not match.')
        elif not EMAIL_PATTERN.match(email):
            error = _('Please provide a valid email address.')
        elif User.query.filter_by(email=email).first() is not None:
            error = _('An account already exists for this email address.')
        else:
            user = User(name=name, email=email, password_hash=hash_password(password))
            db.session.add(user)
            db.session.flush()
            accept_pending_invites(user)

            session.clear()
            session['user_id'] = user.id
            session.permanent = True
            return redirect(url_for('plan.index'))

    return render_template('register.html', error=error, name=name, email=email)


@auth_bp.route('/logout', methods=['POST'])
def logout():
    session.clear()
    return redirect(url_for('auth.login'))


@auth_bp.route('/plan/switch/<int:plan_id>', methods=['POST'])
def switch_plan(plan_id):
    """Switches the active plan of the logged-in user (see
    templates/base.html: the plan list in the sidebar) - only allowed if a
    membership for this plan actually exists, otherwise
    session['active_plan_id'] stays unchanged (no error needed: a user
    without access doesn't even see the other plan in the rail menu in the
    first place, a manually crafted request here simply has no effect).

    Redirects back to request.referrer, but with any ?plan_id=... query
    parameter stripped: several "settings" pages (categories/units/
    ingredient aliasing/nutrition, recipe edit-list) have their own tab
    switcher keyed by ?plan_id= (see services/auth.py: selected_plan_id(),
    which prefers an explicit ?plan_id= over the just-switched active
    plan) - if the referring page still carried the PREVIOUS plan's ID in
    its URL, redirecting back unchanged would silently keep showing that
    old plan's content (only the sidebar highlight would reflect the
    switch, since that's driven by current_plan() directly). Stripping it
    lets the target page fall back to the newly active plan instead."""
    user = current_user()
    if user is not None and PlanMembership.query.filter_by(plan_id=plan_id, user_id=user.id).first():
        session['active_plan_id'] = plan_id
    return redirect(_referrer_without_plan_id() or url_for('plan.index'))


def _referrer_without_plan_id():
    """See switch_plan() above. Returns None if there is no referrer at
    all (e.g. the request wasn't triggered from within the app)."""
    if not request.referrer:
        return None
    parts = urlsplit(request.referrer)
    query = [(k, v) for k, v in parse_qsl(parts.query) if k != 'plan_id']
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))
