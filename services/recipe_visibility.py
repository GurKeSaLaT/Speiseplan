"""Welche Rezepte für einen bestimmten Plan nutzbar sind (siehe models.py:
Recipe.owner_plan_id/RecipePlanLink) - ein Rezept ist für einen Plan
sichtbar, wenn er entweder dessen Eigentümer ist ODER das Rezept per
RecipePlanLink zusätzlich dort eingebunden wurde (echte Verknüpfung, keine
Kopie - siehe models.py-Docstring dort).

Bewusst ein eigenes, extra schlankes Modul OHNE weitere Abhängigkeiten
(nur models): services/planning.py importiert bereits services/
ingredient_aliases.py und services/settings.py, die ihrerseits jetzt (seit
Zutaten-Gleichsetzung/Nährwerte/Einstellungen ebenfalls plan-gebunden sind)
wissen müssen, welche Rezepte zu einem Plan gehören - läge diese Funktion
in services/planning.py selbst, entstünde ein Ringschluss.
"""

from models import Recipe, RecipePlanLink, db


def visible_recipe_ids_subquery(plan_id):
    """Eine SQLAlchemy-Subquery aller Rezept-IDs, die für plan_id nutzbar
    sind - für Filter wie Ingredient.recipe_id.in_(visible_recipe_ids_subquery(plan_id))
    oder Recipe.id.in_(...)."""
    owned = db.session.query(Recipe.id).filter(Recipe.owner_plan_id == plan_id)
    linked = db.session.query(RecipePlanLink.recipe_id).filter(RecipePlanLink.plan_id == plan_id)
    return owned.union(linked)


def visible_recipes_query(plan_id):
    """Recipe.query, eingeschränkt auf die für plan_id sichtbaren Rezepte
    (Eigentümer ODER verknüpft) - siehe visible_recipe_ids_subquery()."""
    return Recipe.query.filter(Recipe.id.in_(visible_recipe_ids_subquery(plan_id)))


def is_recipe_visible_to_plan(recipe, plan_id):
    """Kurzform für einen einzelnen bereits geladenen Recipe-Datensatz -
    vermeidet eine eigene Datenbankabfrage, wenn recipe.plan_links (siehe
    models.py: Recipe.plan_links) bereits (mit-)geladen wurde."""
    if recipe.owner_plan_id == plan_id:
        return True
    return any(link.plan_id == plan_id for link in recipe.plan_links)
