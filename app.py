"""Entry point of the Speiseplan app: creates the Flask app, connects it
to the database, registers the four blueprints (the actual routes live in
routes/*.py resp. the routes/plan/ package) and, on startup, runs the
database migrations for fields that didn't exist in earlier versions of
the app (see migrations.py: init_db()).

This file is deliberately kept lean: it no longer contains a single route
itself (those all live in routes/plan/ (three files: pages.py,
day_actions.py, shopping.py - all three share the ONE plan_bp
blueprint), routes/recipes/, routes/categories.py, routes/manage.py),
no planning/selection logic (that lives in services/planning.py and
services/seasons.py), and no migration logic (that lives in
migrations.py) - just application setup now.
"""

import os
import secrets

from flask import Flask, has_request_context, redirect, request, session, url_for
from flask_babel import Babel
from flask_wtf import CSRFProtect

from models import db
from migrations import init_db
from services.auth import current_plan, current_user, user_plan_memberships
from services.ingredient_aliases import get_all_aliases
from services.nutrition import get_all_nutrition_entries
from services.shopping import PANTRY_CATEGORIES, SHOPPING_CATEGORIES, UNCATEGORIZED
from routes.auth import auth_bp, SESSION_LIFETIME
from routes.plan import plan_bp
from routes.manage import manage_bp
from routes.recipes import recipes_bp
from routes.categories import categories_bp
from routes.settings import settings_bp
from routes.sharing import sharing_bp
from routes.plans import plans_bp
from routes.account import account_bp

app = Flask(__name__)
# The SQLite file lives in Flask's default "instance" folder
# (instance/speiseplan.db), which is mounted as a volume during
# deployment/Docker operation so the database survives container
# restarts/rebuilds. Overridable via DATABASE_URL (analogous to SECRET_KEY
# below) - used only by tests/conftest.py, so tests run against their own,
# temporary SQLite file instead of instance/speiseplan.db (there's no app
# factory pattern; the connection is set up immediately below at module
# import time).
app.config['SQLALCHEMY_DATABASE_URI'] = (
    os.environ.get('DATABASE_URL') or 'sqlite:///' + os.path.join(app.instance_path, 'speiseplan.db')
)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
# How long a session stays valid without a fresh login (see
# routes/auth.py: SESSION_LIFETIME comment).
app.config['PERMANENT_SESSION_LIFETIME'] = SESSION_LIFETIME

os.makedirs(app.instance_path, exist_ok=True)
db.init_app(app)


def load_or_create_secret_key():
    """Returns the secret key Flask uses to sign sessions and CSRF tokens
    (see CSRFProtect below - Flask-WTF stores the CSRF token server-side in
    the signed session cookie, WITHOUT the app needing its own login/
    session management for that).

    Can be fixed via the SECRET_KEY environment variable (useful if
    several container instances need the same key); if it's not set, a
    random key is generated ONCE and stored in instance/secret_key - in
    the same, persistently mounted folder as the database, so the key
    (and thus the validity of issued CSRF tokens/sessions) survives a
    container restart. A key freshly rolled on every restart would
    otherwise invalidate every form currently open in the browser.
    """
    env_key = os.environ.get('SECRET_KEY')
    if env_key:
        return env_key

    key_path = os.path.join(app.instance_path, 'secret_key')
    if os.path.exists(key_path):
        with open(key_path, 'r') as f:
            return f.read().strip()

    new_key = secrets.token_hex(32)
    with open(key_path, 'w') as f:
        f.write(new_key)
    return new_key


app.config['SECRET_KEY'] = load_or_create_secret_key()
# Automatically protects all POST/PUT/PATCH/DELETE routes against
# cross-site request forgery: from now on, every write request requires a
# form field resp. an X-CSRFToken header carrying a valid token that
# matches the session (see csrf_token() in the templates and
# window.CSRF_TOKEN in base.html for the fetch() calls in plan.js) -
# without this, any other website open in the same browser could trigger
# write actions (deleting a recipe, etc.) unnoticed.
CSRFProtect(app)


def get_locale():
    """Resolves the active UI language for this request (Flask-Babel calls
    this once per request). Logged-in users get their saved preference
    (User.language, changeable on /manage/account, see
    services/accounts.py: update_profile()); anonymous requests (login/
    register) fall back to the browser's Accept-Language header, defaulting
    to English whenever it's absent or doesn't match a supported language -
    English is this app's default language.

    has_request_context() guard: a lazy_gettext() string (used throughout
    services/*.py, see e.g. services/accounts.py) can get resolved outside
    any request - most notably in tests that call a service function
    directly via app.app_context() without going through the Flask test
    client (see tests/test_services_accounts.py). current_user()/
    request.accept_languages both need an actual request (they read
    session/headers), so outside one this falls straight back to English
    instead of raising."""
    if not has_request_context():
        return 'en'
    user = current_user()
    if user is not None:
        return user.language
    return request.accept_languages.best_match(['de', 'en']) or 'en'


# translations/ holds the German catalog (translations/de/LC_MESSAGES/
# messages.po, compiled to messages.mo) - English needs no catalog at all,
# since the source strings written directly in _('...')/{{ _('...') }}
# calls throughout the app ARE the English text (gettext falls back to
# showing the msgid as-is when no translation is loaded for the active
# locale, which for 'en' is exactly the desired behavior).
Babel(app, default_locale='en', locale_selector=get_locale)

# Each blueprint brings its own URL namespace (e.g. the function week_view
# in plan_bp becomes the endpoint "plan.week_view", as used in url_for()
# calls in the templates/redirects).
app.register_blueprint(auth_bp)
app.register_blueprint(plan_bp)
app.register_blueprint(manage_bp)
app.register_blueprint(recipes_bp)
app.register_blueprint(categories_bp)
app.register_blueprint(settings_bp)
app.register_blueprint(sharing_bp)
app.register_blueprint(plans_bp)
app.register_blueprint(account_bp)


# Migration runs synchronously at module import time, not only on the
# first request - this guarantees the database is up to date before any
# request is handled at all (important e.g. for Gunicorn/Docker operation
# with multiple workers, which could otherwise migrate concurrently).
with app.app_context():
    init_db()


# Endpoints that must stay reachable even entirely WITHOUT plan
# membership (see require_login() below, second gate) - plan.index/
# plan.week_view show the "no plan yet" view in that case instead of the
# normal calendar data (see routes/plan/pages.py: week_view()), BOTH must
# be on the allowlist (index() redirects to week_view() - if only index()
# were listed here, the second redirect would immediately be caught by
# this same gate again, an infinite loop). plans.create is the only way
# to get out of the zero-plan state.
ZERO_PLAN_ALLOWED_ENDPOINTS = {
    'plan.index', 'plan.week_view', 'plans.create', 'auth.logout',
    # Profile management doesn't need a plan - a user without any
    # membership must still be able to manage/delete their own account
    # (routes/account.py).
    'account.account_view', 'account.update_profile_route',
    'account.update_password_route', 'account.delete_account_route',
}


@app.before_request
def require_login():
    """Globally protects EVERY route except the login/registration page
    itself and static files (CSS/JS/images) - a single gate point instead
    of a @login_required decorator on each of the existing routes (see
    services/auth.py: login_required() for the decorator variant, which is
    currently not used anywhere in the routing), so that no route stays
    unprotected by accident.

    request.endpoint is None for paths that can't be resolved (e.g. a
    typo in the URL) - those are deliberately let through here, so Flask
    delivers its normal 404 response instead of wrongly redirecting to
    /login.

    Second gate (since plans were decoupled from accounts, see
    services/plans.py): a logged-in user WITHOUT any plan membership
    (current_plan() is then None) is redirected to the weekly-plan landing
    page, UNLESS the target is already on ZERO_PLAN_ALLOWED_ENDPOINTS -
    the same central-gate philosophy as above, so that none of the
    numerous plan-bound routes (categories/settings/recipes/sharing/
    day actions) has to individually check whether current_plan() even
    exists."""
    if request.endpoint is None or request.endpoint in ('auth.login', 'auth.register', 'static'):
        return None
    if current_user() is None:
        return redirect(url_for('auth.login', next=request.path))
    if current_plan() is None and request.endpoint not in ZERO_PLAN_ALLOWED_ENDPOINTS:
        return redirect(url_for('plan.index'))
    return None


@app.after_request
def set_security_headers(response):
    """Sets a set of basic security headers on EVERY response that Flask
    doesn't send by default (identified via a pentest on 2026-08-28). No
    HSTS, since the app deliberately runs only over HTTP on the home
    network (no TLS certificate present) - an HSTS header without HTTPS
    would be ineffective resp. misleading.

    The Content Security Policy allows 'unsafe-inline' for scripts/styles,
    because the templates consistently use onclick attributes and inline
    <style>/<script> blocks (no nonce/hash-based setup) - but still
    prevents loading code/images from external sources, embedding the page
    in a foreign iframe (frame-ancestors), and submitting forms to
    external targets (form-action).
    """
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Referrer-Policy'] = 'same-origin'
    response.headers['Permissions-Policy'] = 'geolocation=(), camera=(), microphone=()'
    response.headers['Content-Security-Policy'] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; "
        "frame-ancestors 'none'; "
        "base-uri 'self'; "
        "form-action 'self'"
    )
    return response


@app.context_processor
def inject_css_version():
    """Makes the css_version variable available to all templates (see
    templates/base.html: style.css is included with ?v={{ css_version }}).

    Uses the modification time of the style.css file itself as the version
    number: whenever the file changes, this query parameter automatically
    changes too, causing browsers to load the new version instead of
    continuing to use a stale, cached copy - all without manually bumping
    a version number on every CSS change. If the file access fails (e.g.
    because style.css is missing for some reason), 0 is used instead of
    aborting the page with an error.
    """
    css_path = os.path.join(app.static_folder, 'style.css')
    try:
        css_version = int(os.path.getmtime(css_path))
    except OSError:
        css_version = 0
    return {'css_version': css_version}


@app.context_processor
def inject_current_user_and_plans():
    """Makes the logged-in user, their active plan, and the list of ALL
    plans they have access to (own + invited-to, see models/plan.py:
    PlanMembership) available to all templates - used by
    templates/base.html for the user/plan section in the sidebar (name,
    log out, plan switch/star). Starred plan first, otherwise
    alphabetical.

    On the login page itself (no logged-in user), all three values stay
    empty/None - the template there doesn't extend base.html anyway, so it
    doesn't need them at all."""
    user = current_user()
    if user is None:
        return {'nav_current_user': None, 'nav_current_plan': None, 'nav_user_plans': []}

    return {
        'nav_current_user': user,
        'nav_current_plan': current_plan(),
        'nav_user_plans': user_plan_memberships(user),
    }


@app.context_processor
def inject_shopping_categories():
    """Makes the fixed shopping-list category order available to all
    templates (see services/shopping.py) - needed both by the category
    dropdowns when entering ingredients (recipe_form.html,
    recipe_edit_list.html) and, via window.SHOPPING_CATEGORIES in
    base.html, by the client-side sorting/grouping of the shopping list
    (static/plan.js). pantry_categories (window.PANTRY_CATEGORIES)
    additionally marks which of these categories should NOT automatically
    go onto the shopping list, but onto the separate pantry list (see
    static/plan-shopping.js: rebuildShoppingList)."""
    return {
        'shopping_categories': SHOPPING_CATEGORIES,
        'shopping_uncategorized': UNCATEGORIZED,
        'pantry_categories': sorted(PANTRY_CATEGORIES),
    }


@app.context_processor
def inject_ingredient_aliases():
    """Makes the ingredient-alias mappings maintained for the ACTIVE plan
    available to all templates (see services/ingredient_aliases.py) -
    currently used only by recipe_form.html (window.INGREDIENT_ALIASES,
    see static/ingredient_alias_hint.js), but kept as a global context
    processor just as simply as inject_shopping_categories() above instead
    of repeating the query in every single route.

    Runs for EVERY page view, including the login page (no logged-in
    user, so current_plan() is None) - simply returns an empty dict then,
    instead of aborting with an error."""
    plan = current_plan()
    return {'ingredient_aliases': get_all_aliases(plan.id) if plan else {}}


@app.context_processor
def inject_ingredient_nutrition():
    """Makes the nutrition references maintained for the ACTIVE plan, per
    alias target ingredient, available to all templates (see
    services/nutrition.py) - used by recipe_form.html
    (window.INGREDIENT_NUTRITION, see static/ingredient_alias_hint.js),
    analogous to inject_ingredient_aliases() above (including the same
    login-page special case)."""
    plan = current_plan()
    return {'ingredient_nutrition': get_all_nutrition_entries(plan.id) if plan else {}}


if __name__ == '__main__':
    # Only relevant when app.py is run directly (local development resp.
    # CMD in the Dockerfile) - under a real WSGI server (Gunicorn etc.)
    # this block wouldn't run at all.
    #
    # FLASK_DEBUG and PORT are set via the Dockerfile in the Docker
    # deployment (FLASK_DEBUG=0, PORT=80): in the container, the app thus
    # runs without the Werkzeug debugger (which would be a remote-code-
    # execution risk if reachable over the network) and on the standard
    # HTTP port. Locally, with no variables set, debug/autoreload mode
    # stays on and the port stays at 5000 (no root needed, unlike with
    # port 80).
    #
    # host='0.0.0.0' is necessary in the Docker deployment: with Flask's
    # default ('127.0.0.1'), the app would be reachable only from
    # localhost even within the container, i.e. not at all from outside.
    # Overridable for local test runs outside of Docker via the HOST
    # environment variable, e.g. HOST=127.0.0.1, so the local test server
    # is deliberately NOT reachable via the machine's LAN IP, but only
    # from this machine itself.
    debug_mode = os.environ.get('FLASK_DEBUG', '1') == '1'
    port = int(os.environ.get('PORT', 5000))
    host = os.environ.get('HOST', '0.0.0.0')
    app.run(host=host, port=port, debug=debug_mode)
