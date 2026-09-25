"""Plan calendar routes, sharing one blueprint: pages.py (full pages),
day_actions.py (main dish and whole-day JSON actions), day_actions_sides.py
(side dishes) and shopping.py (manual shopping-list items)."""

from flask import Blueprint

plan_bp = Blueprint('plan', __name__)

# Importing the modules registers their routes on plan_bp.
from routes.plan import pages, day_actions, day_actions_sides, shopping  # noqa: E402,F401
