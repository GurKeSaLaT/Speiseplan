"""Recipe management: the create/edit/delete pages for individual dishes
(Recipe), including their ingredients (Ingredient), season assignment
(RecipeSeason, managed via services/seasons.py) and the import from
chefkoch.de (via services/recipe_import.py).

This package replaces the former single routes/recipes.py, now split
across two topically separated files, which both share the SAME
recipes_bp blueprint (defined here, imported and populated there via
@recipes_bp.route(...)):

- crud.py: create/edit/delete/list views plus the chefkoch.de
  import-preview AJAX endpoint (tightly coupled to the create flow).
- links.py: link_recipe_to_plan()/unlink_recipe_from_plan() - a distinct
  concern (sharing one recipe across plans), not CRUD.

app.py still imports `from routes.recipes import recipes_bp` unchanged -
the fact that this is now a package instead of a single module changes
nothing about that (nor about any `url_for('recipes.xxx')` calls in the
templates, which continue to use the blueprint name "recipes").
"""

from flask import Blueprint

recipes_bp = Blueprint('recipes', __name__)

# The imports here are what actually trigger route registration: each of
# the two files decorates its functions with @recipes_bp.route(...), which
# only happens when the respective module is executed. Without these
# imports (even though recipes_bp appears "unused") the routes simply
# would not be registered.
from routes.recipes import crud, links  # noqa: E402,F401
