"""Flask app setup: config, database, blueprints, auth gate, security
headers and global template context. Migrations run at import time."""

import os
import secrets

from flask import Flask, abort, has_request_context, redirect, request, url_for
from flask_babel import Babel
from flask_wtf import CSRFProtect

from models import db
from migrations import init_db
from services.auth import current_plan, current_user, user_plan_memberships, SESSION_LIFETIME
from services.demo_seed import seed_demo_data_if_requested
from services.ingredient_aliases import get_all_aliases
from services.nutrition import get_all_nutrition_entries
from services.shopping import SHOPPING_CATEGORIES, UNCATEGORIZED
from routes.auth import auth_bp
from routes.plan import plan_bp
from routes.manage import manage_bp
from routes.recipes import recipes_bp
from routes.categories import categories_bp
from routes.settings import settings_bp
from routes.sharing import sharing_bp
from routes.plans import plans_bp
from routes.account import account_bp

app = Flask(__name__)
# instance/ is the persistent volume in Docker. DATABASE_URL is read here at
# import time (no app factory) - tests must set it before importing app.
app.config['SQLALCHEMY_DATABASE_URI'] = (
    os.environ.get('DATABASE_URL') or 'sqlite:///' + os.path.join(app.instance_path, 'speiseplan.db')
)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['PERMANENT_SESSION_LIFETIME'] = SESSION_LIFETIME

os.makedirs(app.instance_path, exist_ok=True)
db.init_app(app)


def load_or_create_secret_key():
    """SECRET_KEY from the environment, else generated once and persisted in
    instance/secret_key so sessions/CSRF tokens survive restarts."""
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
# Every write request needs a csrf_token field or X-CSRFToken header
# (window.CSRF_TOKEN in base.html for fetch() calls).
CSRFProtect(app)


def get_locale():
    """The user's saved language, else the browser's, else English. Outside
    a request (lazy strings resolved in tests) always English."""
    if not has_request_context():
        return 'en'
    user = current_user()
    if user is not None:
        return user.language
    return request.accept_languages.best_match(['de', 'en']) or 'en'


# English needs no catalog: the msgids are the English text.
Babel(app, default_locale='en', locale_selector=get_locale)

app.register_blueprint(auth_bp)
app.register_blueprint(plan_bp)
app.register_blueprint(manage_bp)
app.register_blueprint(recipes_bp)
app.register_blueprint(categories_bp)
app.register_blueprint(settings_bp)
app.register_blueprint(sharing_bp)
app.register_blueprint(plans_bp)
app.register_blueprint(account_bp)


# At import time, so the schema is current before the first request.
with app.app_context():
    init_db()
    seed_demo_data_if_requested()


# Reachable without any plan membership. index and week_view must both be
# listed (index delegates to week_view) or the redirect below would loop.
ZERO_PLAN_ALLOWED_ENDPOINTS = {
    'plan.index', 'plan.week_view', 'plans.create',
    'account.account_view', 'account.update_language_route', 'account.delete_account_route',
}


@app.before_request
def require_login():
    """Single gate for every route. No identity header means the request
    bypassed the Authelia proxy, so 401 (there is no login page). Users
    without any plan are sent to the "create a plan" page. Unknown paths
    pass through so Flask can answer 404."""
    if request.endpoint is None or request.endpoint == 'static':
        return None
    if current_user() is None:
        abort(401, description='Not authenticated. This app expects Authelia/the reverse proxy to attach an identity header to every request - see services/auth.py: AUTHELIA_EMAIL_HEADER.')
    if current_plan() is None and request.endpoint not in ZERO_PLAN_ALLOWED_ENDPOINTS:
        return redirect(url_for('plan.index'))
    return None


@app.after_request
def set_security_headers(response):
    """No HSTS: TLS terminates at the reverse proxy. 'unsafe-inline' is
    needed because templates use inline scripts and handlers."""
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
    """style.css mtime as a cache-busting ?v= parameter."""
    css_path = os.path.join(app.static_folder, 'style.css')
    try:
        css_version = int(os.path.getmtime(css_path))
    except OSError:
        css_version = 0
    return {'css_version': css_version}


@app.context_processor
def inject_current_user_and_plans():
    """Sidebar data. AUTHELIA_LOGOUT_URL is optional; without it no logout
    link is shown (the app has no session of its own to end)."""
    user = current_user()
    if user is None:
        return {
            'nav_current_user': None, 'nav_current_plan': None, 'nav_user_plans': [],
            'nav_authelia_logout_url': os.environ.get('AUTHELIA_LOGOUT_URL'),
        }

    return {
        'nav_current_user': user,
        'nav_current_plan': current_plan(),
        'nav_user_plans': user_plan_memberships(user),
        'nav_authelia_logout_url': os.environ.get('AUTHELIA_LOGOUT_URL'),
    }


@app.context_processor
def inject_shopping_categories():
    return {
        'shopping_categories': SHOPPING_CATEGORIES,
        'shopping_uncategorized': UNCATEGORIZED,
    }


@app.context_processor
def inject_ingredient_aliases():
    plan = current_plan()
    return {'ingredient_aliases': get_all_aliases(plan.id) if plan else {}}


@app.context_processor
def inject_ingredient_nutrition():
    plan = current_plan()
    return {'ingredient_nutrition': get_all_nutrition_entries(plan.id) if plan else {}}


if __name__ == '__main__':
    # Docker sets FLASK_DEBUG=0 and PORT=80; locally debug mode on port 5000.
    # The debugger must never be reachable over the network.
    debug_mode = os.environ.get('FLASK_DEBUG', '1') == '1'
    port = int(os.environ.get('PORT', 5000))
    host = os.environ.get('HOST', '0.0.0.0')
    app.run(host=host, port=port, debug=debug_mode)
