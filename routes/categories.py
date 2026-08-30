"""Kategorie-Verwaltung: anzeigen, anlegen und löschen. Kategorien sind
bewusst simpel gehalten (nur ein Name) - die eigentliche "Intelligenz" rund
um Kategorien (Balance über die Woche, Nachbarschaftsregel) steckt in
services/planning.py, nicht hier.

Jeder Plan pflegt seine eigenen Kategorien (siehe models.py: Category.
plan_id) - hat ein Nutzer Zugriff auf mehr als einen Plan (eigener +
freigegebene), zeigt die Seite einen Tab-Umschalter (siehe
services/auth.py: selected_plan_id/user_plan_memberships) und
add_category()/delete_category() wirken auf den GERADE ausgewählten Plan,
nicht zwingend den sonst aktiven (current_plan())."""

from flask import Blueprint, abort, render_template, request, redirect, url_for

from models import db, Category
from services.auth import current_user, selected_plan_id, user_has_plan_access, user_plan_memberships

categories_bp = Blueprint('categories', __name__)


@categories_bp.route('/manage/categories')
def category_manage_view():
    """Zeigt die Liste aller Kategorien des ausgewählten Plans mit
    Lösch-Button und ein Formular zum Anlegen einer neuen. Kategorien,
    denen noch Rezepte zugeordnet sind, werden hier mit deaktiviertem
    Lösch-Button dargestellt (siehe templates/category_manage.html:
    cat.recipes)."""
    user = current_user()
    plan_id = selected_plan_id(request.args, user)
    categories = Category.query.filter_by(plan_id=plan_id).order_by(Category.name).all()
    return render_template(
        'category_manage.html', categories=categories, plan_id=plan_id,
        user_plans=user_plan_memberships(user),
    )


@categories_bp.route('/add-category', methods=['POST'])
def add_category():
    """Legt eine neue Kategorie im ausgewählten Plan an, sofern der Name
    nicht leer ist und dort noch nicht existiert (Category hat zusätzlich
    eine unique-Constraint auf (plan_id, name) in der Datenbank, dieser
    Vorab-Check verhindert nur die weniger hilfreiche
    IntegrityError-Fehlermeldung bei einem Duplikat)."""
    user = current_user()
    plan_id = selected_plan_id(request.form, user)
    name = request.form.get('category_name').strip()
    if name:
        existing = Category.query.filter_by(plan_id=plan_id, name=name).first()
        if not existing:
            new_cat = Category(plan_id=plan_id, name=name)
            db.session.add(new_cat)
            db.session.commit()
    return redirect(url_for('categories.category_manage_view', plan_id=plan_id))


@categories_bp.route('/delete-category/<int:id>', methods=['POST'])
def delete_category(id):
    """Löscht eine Kategorie - aber nur, wenn ihr aktuell KEIN Rezept mehr
    zugeordnet ist. Ein Rezept ohne gültige Kategorie wäre inkonsistent
    (category_id ist nicht nullable), daher wird das Löschen mit einer
    Fehlermeldung abgelehnt statt die Rezepte automatisch zu verwaisen oder
    mitzulöschen - der Nutzer muss sie erst manuell umkategorisieren oder
    entfernen.

    Zusätzlicher Besitz-Check: die Kategorie muss zu einem Plan gehören,
    auf den der eingeloggte Nutzer tatsächlich Zugriff hat (siehe
    selected_plan_id() für dieselbe Prüfung beim Anzeigen/Anlegen) - sonst
    ließe sich über eine erratene ID eine fremde Kategorie löschen."""
    user = current_user()
    category = Category.query.get_or_404(id)
    if not user_has_plan_access(user, category.plan_id):
        abort(404)
    if len(category.recipes) > 0:
        return "Fehler: Diese Kategorie enthält noch Rezepte!", 400
    db.session.delete(category)
    db.session.commit()
    return redirect(url_for('categories.category_manage_view', plan_id=category.plan_id))
