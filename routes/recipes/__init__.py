"""Recipe routes: crud.py (create/edit/delete/list, import preview) and
links.py (linking recipes into other plans), sharing one blueprint."""

from flask import Blueprint

recipes_bp = Blueprint('recipes', __name__)

# Importing the modules registers their routes on recipes_bp.
from routes.recipes import crud, links  # noqa: E402,F401
