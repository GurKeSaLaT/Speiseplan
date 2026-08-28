"""Kategorie-Verwaltung: anzeigen, anlegen und löschen. Kategorien sind
bewusst simpel gehalten (nur ein Name) - die eigentliche "Intelligenz" rund
um Kategorien (Balance über die Woche, Nachbarschaftsregel) steckt in
services/planning.py, nicht hier."""

from flask import Blueprint, render_template, request, redirect, url_for

from models import db, Category

categories_bp = Blueprint('categories', __name__)


@categories_bp.route('/manage/categories')
def category_manage_view():
    """Zeigt die Liste aller Kategorien mit Lösch-Button und ein Formular
    zum Anlegen einer neuen. Kategorien, denen noch Rezepte zugeordnet
    sind, werden hier mit deaktiviertem Lösch-Button dargestellt (siehe
    templates/category_manage.html: cat.recipes)."""
    categories = Category.query.all()
    return render_template('category_manage.html', categories=categories)


@categories_bp.route('/add-category', methods=['POST'])
def add_category():
    """Legt eine neue Kategorie an, sofern der Name nicht leer ist und noch
    nicht existiert (Category.name hat zusätzlich eine unique-Constraint in
    der Datenbank, dieser Vorab-Check verhindert nur die weniger
    hilfreiche IntegrityError-Fehlermeldung bei einem Duplikat)."""
    name = request.form.get('category_name').strip()
    if name:
        existing = Category.query.filter_by(name=name).first()
        if not existing:
            new_cat = Category(name=name)
            db.session.add(new_cat)
            db.session.commit()
    return redirect(url_for('categories.category_manage_view'))


@categories_bp.route('/delete-category/<int:id>', methods=['POST'])
def delete_category(id):
    """Löscht eine Kategorie - aber nur, wenn ihr aktuell KEIN Rezept mehr
    zugeordnet ist. Ein Rezept ohne gültige Kategorie wäre inkonsistent
    (category_id ist nicht nullable), daher wird das Löschen mit einer
    Fehlermeldung abgelehnt statt die Rezepte automatisch zu verwaisen oder
    mitzulöschen - der Nutzer muss sie erst manuell umkategorisieren oder
    entfernen."""
    category = Category.query.get_or_404(id)
    if len(category.recipes) > 0:
        return "Fehler: Diese Kategorie enthält noch Rezepte!", 400
    db.session.delete(category)
    db.session.commit()
    return redirect(url_for('categories.category_manage_view'))
