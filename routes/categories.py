"""Category management: display, create, and delete. Categories are
deliberately kept simple (just a name) - the actual "intelligence" around
categories (balance across the week, adjacency rule) lives in
services/planning.py, not here.

Each plan maintains its own categories (see models.py: Category.
plan_id) - if a user has access to more than one plan (own + shared),
the page shows a tab switcher (see services/auth.py:
selected_plan_id/user_plan_memberships) and
add_category()/delete_category() act on the CURRENTLY selected plan,
not necessarily the otherwise active one (current_plan())."""

from flask import Blueprint, abort, render_template, request, redirect, url_for
from flask_babel import gettext as _

from models import db, Category
from services.auth import current_user, selected_plan_id, user_has_plan_access, user_plan_memberships

categories_bp = Blueprint('categories', __name__)


@categories_bp.route('/manage/categories')
def category_manage_view():
    """Shows the list of all categories of the selected plan with a
    delete button and a form for creating a new one. Categories that
    still have recipes assigned to them are shown here with the delete
    button disabled (see templates/category_manage.html: cat.recipes)."""
    user = current_user()
    plan_id = selected_plan_id(request.args, user)
    categories = Category.query.filter_by(plan_id=plan_id).order_by(Category.name).all()
    return render_template(
        'category_manage.html', categories=categories, plan_id=plan_id,
        user_plans=user_plan_memberships(user),
    )


@categories_bp.route('/add-category', methods=['POST'])
def add_category():
    """Creates a new category in the selected plan, provided the name
    isn't empty and doesn't already exist there (Category additionally
    has a unique constraint on (plan_id, name) in the database - this
    upfront check only prevents the less helpful IntegrityError message
    for a duplicate)."""
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
    """Deletes a category - but only if it currently has NO recipe
    assigned to it anymore. A recipe without a valid category would be
    inconsistent (category_id is not nullable), so the deletion is
    rejected with an error message instead of automatically orphaning or
    deleting the recipes along with it - the user must first manually
    recategorize or remove them.

    Additional ownership check: the category must belong to a plan the
    logged-in user actually has access to (see selected_plan_id() for the
    same check when displaying/creating) - otherwise a guessed ID could
    be used to delete someone else's category."""
    user = current_user()
    category = Category.query.get_or_404(id)
    if not user_has_plan_access(user, category.plan_id):
        abort(404)
    if len(category.recipes) > 0:
        return _("Error: This category still contains recipes!"), 400
    db.session.delete(category)
    db.session.commit()
    return redirect(url_for('categories.category_manage_view', plan_id=category.plan_id))
