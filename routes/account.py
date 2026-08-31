"""Profile management for the logged-in user (/manage/account): change own
name/email address, change password, delete account.

No flash-messaging system in this app (see templates/login.html: the same
re-render-with-error pattern for invalid forms) - success/error of each of
the three actions is therefore passed directly into the re-render of
account.html, instead of redirecting after the POST."""

from flask import Blueprint, redirect, render_template, request, session, url_for
from flask_babel import gettext as _

from services.accounts import delete_account, update_password, update_profile
from services.auth import current_user, verify_password

account_bp = Blueprint('account', __name__)


@account_bp.route('/manage/account')
def account_view():
    return render_template('account.html', user=current_user())


@account_bp.route('/manage/account/profile', methods=['POST'])
def update_profile_route():
    user = current_user()
    ok, error = update_profile(
        user, request.form.get('name'), request.form.get('email'), request.form.get('language')
    )
    return render_template('account.html', user=user, profile_error=error, profile_success=ok)


@account_bp.route('/manage/account/password', methods=['POST'])
def update_password_route():
    user = current_user()
    ok, error = update_password(user, request.form.get('current_password'), request.form.get('new_password'))
    return render_template('account.html', user=user, password_error=error, password_success=ok)


@account_bp.route('/manage/account/delete', methods=['POST'])
def delete_account_route():
    """Deletes the user's own account irrevocably (services/accounts.py:
    delete_account()) - requires entering the CURRENT password in addition
    to the confirmation modal (templates/account.html), so that a single
    click on an otherwise still-open session isn't enough. Afterward
    clears the session entirely (the user no longer exists) and redirects
    to the login page."""
    user = current_user()
    if not verify_password(user, request.form.get('password') or ''):
        return render_template('account.html', user=user, delete_error=_('Password is incorrect.'))

    delete_account(user)
    session.clear()
    return redirect(url_for('auth.login'))
