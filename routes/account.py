"""Self-service management of the logged-in user's own account
(/manage/account): change the UI language, delete the account. Name/email
are no longer editable here - they're synced from Authelia on every
request (see services/auth.py: current_user()) - and there's no password
to change or confirm anymore (see services/auth.py module docstring).

No flash-messaging system in this app - success/error is passed directly
into the re-render of account.html, instead of redirecting after the
POST."""

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
    """Deletes the user's own Speiseplan data irrevocably
    (services/accounts.py: delete_account()) - the confirmation modal
    (templates/account.html) is the only safeguard now; there's no
    password left to additionally require (Authelia already gated access
    to this page in the first place).

    Doesn't (and can't) actually log the person out: identity comes from
    Authelia on every request (see services/auth.py module docstring), so
    the very next request - including the redirect target below -
    auto-provisions a brand new, empty User row for the same email again.
    "Delete account" therefore really means "wipe my plans/recipes/
    settings and start over", not "close my account" - closing the actual
    account is Authelia's job, not this app's."""
    delete_account(current_user())
    return redirect(url_for('plan.index'))
