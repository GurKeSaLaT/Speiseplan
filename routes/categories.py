from flask import Blueprint, render_template, request, redirect, url_for

from models import db, Category

categories_bp = Blueprint('categories', __name__)


@categories_bp.route('/manage/categories')
def category_manage_view():
    categories = Category.query.all()
    return render_template('category_manage.html', categories=categories)


@categories_bp.route('/add-category', methods=['POST'])
def add_category():
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
    category = Category.query.get_or_404(id)
    if len(category.recipes) > 0:
        return "Fehler: Diese Kategorie enthält noch Rezepte!", 400
    db.session.delete(category)
    db.session.commit()
    return redirect(url_for('categories.category_manage_view'))
