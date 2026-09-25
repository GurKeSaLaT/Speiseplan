"""Per-plan recipe category management."""

from flask import Blueprint, abort, render_template, request, redirect, url_for
from flask_babel import gettext as _

from models import db, Category
from services.auth import current_user, selected_plan_id, user_has_plan_access, user_plan_memberships

categories_bp = Blueprint('categories', __name__)


@categories_bp.route('/manage/categories')
def category_manage_view():
    user = current_user()
    plan_id = selected_plan_id(request.args, user)
    categories = Category.query.filter_by(plan_id=plan_id).order_by(Category.name).all()
    return render_template(
        'category_manage.html', categories=categories, plan_id=plan_id,
        user_plans=user_plan_memberships(user),
    )


@categories_bp.route('/add-category', methods=['POST'])
def add_category():
    """Empty and duplicate names are ignored."""
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
    """Refused while recipes still use the category (category_id is required)."""
    user = current_user()
    category = Category.query.get_or_404(id)
    if not user_has_plan_access(user, category.plan_id):
        abort(404)
    if len(category.recipes) > 0:
        return _("Error: This category still contains recipes!"), 400
    db.session.delete(category)
    db.session.commit()
    return redirect(url_for('categories.category_manage_view', plan_id=category.plan_id))
