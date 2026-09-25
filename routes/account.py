"""Account page (/manage/account): UI language and account deletion.
Results are rendered directly (no flash messages)."""

from flask import Blueprint, redirect, render_template, request, url_for

from services.accounts import delete_account, update_language
from services.auth import current_user

account_bp = Blueprint('account', __name__)


@account_bp.route('/manage/account')
def account_view():
    return render_template('account.html', user=current_user())


@account_bp.route('/manage/account/language', methods=['POST'])
def update_language_route():
    user = current_user()
    ok, error = update_language(user, request.form.get('language'))
    return render_template('account.html', user=user, language_error=error, language_success=ok)


@account_bp.route('/manage/account/delete', methods=['POST'])
def delete_account_route():
    """Wipes the user's data. The Authelia account stays, so the next request
    provisions a fresh empty user for the same email - effectively "start
    over", not "close account"."""
    delete_account(current_user())
    return redirect(url_for('plan.index'))
