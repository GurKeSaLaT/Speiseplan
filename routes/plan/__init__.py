"""The weekly plan calendar: display, creation, and all live interactions
(roll dice, pick manually, swap, add/remove/move side dishes, change the
number of servings) against the plan permanently stored in
PlanDay/PlanDaySide.

This package replaces the former single routes/plan.py, which had grown
to over 800 lines over time (page routes, day actions, side-dish actions,
and shopping-list actions all in one file) - now split across three
topically separated files, which all share the SAME plan_bp blueprint
(defined here, imported and populated there via @plan_bp.route(...)):

- pages.py: page routes (/, /plan/<start_date>, /plan/<start_date>/create,
  /plan/<start_date>/generate) - deliver whole HTML pages or redirect.
- day_actions.py: AJAX endpoints for individual calendar days (roll/select
  main dish, add/roll/select/remove/move side dishes, servings, swap
  days).
- shopping.py: AJAX endpoints for items manually added to the shopping
  list (ExtraShoppingItem) that don't belong to any recipe.

app.py still imports `from routes.plan import plan_bp` unchanged - the
fact that this is now a package instead of a single module changes
nothing about that (nor about any `url_for('plan.xxx')` calls in the
templates, which continue to use the blueprint name "plan").
"""

from flask import Blueprint

plan_bp = Blueprint('plan', __name__)

# The imports here are what actually trigger route registration: each of
# the three files decorates its functions with @plan_bp.route(...), which
# only happens when the respective module is executed. Without these
# imports (even though plan_bp appears "unused") the routes simply would
# not be registered.
from routes.plan import pages, day_actions, shopping  # noqa: E402,F401
