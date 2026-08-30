"""Lebenszyklus eines Plans selbst (anlegen/löschen) - anders als
services/auth.py (Login/aktiver Plan/Mitgliedschafts-Lookups) oder
routes/sharing.py (Mitglieder/Stern EINES bereits bestehenden Plans) geht
es hier um den Plan als Ganzes.

Ein Nutzer bekommt seit der Entkopplung von Accounts/Plänen NICHT mehr
automatisch genau einen Plan - er legt sie sich selbst über /plan/create
an (routes/plans.py), beliebig viele. create_plan()/delete_plan() sind
hier gebündelt, weil beide dieselbe Kategorie-Logik anfassen (Seeden bzw.
Übernehmen von Kategorien) und von mehreren Stellen wiederverwendet
werden: create_plan() sowohl von der Route als auch (über
seed_default_categories()) von app.py: init_db() für jeden Plan ohne
eigene Kategorien.
"""

from models import (
    Category, ExtraShoppingItem, IngredientAlias, IngredientNutrition,
    AppSettings, Plan, PlanDay, PlanDaySide, PlanMembership, Recipe,
    RecipePlanLink, db,
)

# Ein sinnvoller Grundstock an Kategorien, damit ein neuer Plan nicht mit
# einer leeren Kategorie-Liste (und damit unbenutzbarer automatischer
# Planung) startet - siehe seed_default_categories() unten.
DEFAULT_CATEGORIES = ["Fleisch", "Fisch", "Vegetarisch", "Vegan", "Nudeln/Pasta", "Suppe/Eintopf", "Schnelle Küche"]


def seed_default_categories(plan_id):
    """Legt DEFAULT_CATEGORIES für plan_id an, falls er noch KEINE einzige
    eigene Kategorie hat - eigene, später hinzugefügte oder umbenannte
    Kategorien werden dadurch nie überschrieben oder erneut angelegt (der
    Check ist rein "hat dieser Plan schon irgendeine Kategorie?").
    Committet nicht selbst - der Aufrufer (create_plan() oder app.py:
    init_db()) entscheidet, wann committet wird."""
    if Category.query.filter_by(plan_id=plan_id).first():
        return
    for name in DEFAULT_CATEGORIES:
        db.session.add(Category(plan_id=plan_id, name=name))


def create_plan(user, name):
    """Legt einen neuen, eigenständigen Plan für user an: die Plan-Zeile
    selbst (user wird informativ als owner_user_id eingetragen, siehe
    models.py: Plan-Docstring - keine besonderen Rechte dadurch), eine
    PlanMembership für user (gesternt, falls dies seine ERSTE Mitgliedschaft
    überhaupt ist - sonst bleibt der bisherige gesternte Plan gesternt,
    ein neuer Plan drängt sich nicht automatisch nach vorne), und die
    Standard-Kategorien (siehe seed_default_categories)."""
    is_first_membership = PlanMembership.query.filter_by(user_id=user.id).first() is None

    plan = Plan(name=name, owner_user_id=user.id)
    db.session.add(plan)
    db.session.flush()

    db.session.add(PlanMembership(plan_id=plan.id, user_id=user.id, is_starred=is_first_membership))
    seed_default_categories(plan.id)
    db.session.commit()
    return plan


def delete_plan(plan):
    """Löscht einen Plan unwiderruflich, samt allem, was AUSSCHLIESSLICH er
    besitzt - Rezepte, die noch per RecipePlanLink in einen anderen Plan
    eingebunden sind, werden STATTDESSEN an diesen anderen Plan übergeben
    (neuer owner_plan_id), nicht mitgelöscht (siehe Recipe-Docstring:
    category_id zeigt immer auf eine Kategorie des Eigentümer-Plans - beim
    Eigentümerwechsel muss also auch die Kategorie mitwandern, sonst bliebe
    sie auf eine gleich mitgelöschte Kategorie zeigen).

    SQLite läuft in dieser App ohne PRAGMA foreign_keys=ON (siehe
    routes/recipes.py: delete_recipe()-Docstring) - die Lösch-Reihenfolge
    unten ist trotzdem bewusst so gewählt, dass zum Zeitpunkt jedes
    einzelnen Schritts keine noch benötigte Referenz bereits verschwunden
    ist (Rezepte/Kategorien VOR den übrigen, rein plan-gebundenen Daten,
    Mitgliedschaften und der Plan selbst ganz zuletzt)."""
    for recipe in Recipe.query.filter_by(owner_plan_id=plan.id).all():
        links = RecipePlanLink.query.filter_by(recipe_id=recipe.id).order_by(RecipePlanLink.plan_id).all()
        if links:
            new_owner_plan_id = links[0].plan_id
            old_category_name = recipe.category.name
            new_category = Category.query.filter_by(plan_id=new_owner_plan_id, name=old_category_name).first()
            if new_category is None:
                new_category = Category(plan_id=new_owner_plan_id, name=old_category_name)
                db.session.add(new_category)
                db.session.flush()
            recipe.owner_plan_id = new_owner_plan_id
            recipe.category_id = new_category.id
            RecipePlanLink.query.filter_by(recipe_id=recipe.id, plan_id=new_owner_plan_id).delete()
        else:
            db.session.delete(recipe)

    plan_day_ids = db.session.query(PlanDay.id).filter(PlanDay.plan_id == plan.id)
    PlanDaySide.query.filter(PlanDaySide.plan_day_id.in_(plan_day_ids)).delete(synchronize_session=False)
    PlanDay.query.filter_by(plan_id=plan.id).delete()

    ExtraShoppingItem.query.filter_by(plan_id=plan.id).delete()
    AppSettings.query.filter_by(plan_id=plan.id).delete()
    IngredientAlias.query.filter_by(plan_id=plan.id).delete()
    IngredientNutrition.query.filter_by(plan_id=plan.id).delete()
    Category.query.filter_by(plan_id=plan.id).delete()

    PlanMembership.query.filter_by(plan_id=plan.id).delete()
    db.session.delete(plan)
    db.session.commit()
