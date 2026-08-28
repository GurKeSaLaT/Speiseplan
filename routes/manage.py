from flask import Blueprint, render_template

manage_bp = Blueprint('manage', __name__)


@manage_bp.route('/manage')
def manage():
    return render_template('manage.html')
