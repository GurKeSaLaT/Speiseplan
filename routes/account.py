"""Profil-Verwaltung des eingeloggten Nutzers (/manage/account): eigenen
Namen/E-Mail-Adresse ändern, Passwort ändern, Konto löschen.

Kein Flash-Messaging-System in dieser App (siehe templates/login.html:
dasselbe re-render-mit-error-Muster für ungültige Formulare) - Erfolg/
Fehler jeder der drei Aktionen wird deshalb direkt beim erneuten Rendern
von account.html mitgegeben, statt nach dem POST umzuleiten."""

from flask import Blueprint, redirect, render_template, request, session, url_for

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
    """Löscht das eigene Konto unwiderruflich (services/accounts.py:
    delete_account()) - erfordert zusätzlich zum Bestätigungs-Modal
    (templates/account.html) die Eingabe des AKTUELLEN Passworts, damit
    ein einzelner Klick auf einer sonst noch offenen Sitzung nicht
    reicht. Löscht danach die Session komplett (der Nutzer existiert ja
    nicht mehr) und leitet zur Login-Seite."""
    user = current_user()
    if not verify_password(user, request.form.get('password') or ''):
        return render_template('account.html', user=user, delete_error='Passwort ist falsch.')

    delete_account(user)
    session.clear()
    return redirect(url_for('auth.login'))
