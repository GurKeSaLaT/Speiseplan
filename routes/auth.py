"""Login/Logout sowie das Umschalten des aktiven Plans (siehe
services/auth.py: current_plan() für die Auflösungsreihenfolge).
"""

from datetime import timedelta

from flask import Blueprint, redirect, render_template, request, session, url_for

from models import PlanMembership, User
from services.auth import current_user, verify_password

auth_bp = Blueprint('auth', __name__)

# Wie lange eine Session ohne erneuten Login gültig bleibt (siehe
# app.py: SECRET_KEY-Kommentar) - großzügig bemessen, da es sich um private
# Geräte im eigenen Heimnetz handelt, kein ständiges Neu-Einloggen gewollt.
SESSION_LIFETIME = timedelta(days=30)


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    """Zeigt das Login-Formular (templates/login.html, EIGENSTÄNDIGE Seite
    ohne die App-Navigationsleiste - die setzt einen eingeloggten Nutzer
    mit aktivem Plan voraus) bzw. verarbeitet dessen Absenden.

    Bereits eingeloggte Nutzer, die die Login-Seite trotzdem aufrufen
    (z.B. über den Browser-Verlauf), werden direkt weitergeleitet statt
    das Formular erneut zu zeigen. `next` (optionales Query-Argument, von
    app.py: require_login() gesetzt) führt nach erfolgreichem Login zurück
    zu der Seite, die den Redirect ausgelöst hat - fehlt es oder zeigt es
    aus irgendeinem Grund nicht auf einen internen Pfad, geht es stattdessen
    zur Wochenplan-Startseite.
    """
    if current_user() is not None:
        return redirect(url_for('plan.index'))

    error = None
    if request.method == 'POST':
        username = (request.form.get('username') or '').strip()
        password = request.form.get('password') or ''
        user = User.query.filter_by(username=username).first()

        if user and verify_password(user, password):
            session.clear()
            session['user_id'] = user.id
            session.permanent = True
            next_path = request.form.get('next') or ''
            destination = next_path if next_path.startswith('/') and not next_path.startswith('//') else url_for('plan.index')
            return redirect(destination)

        error = 'Name oder Passwort falsch.'

    return render_template('login.html', error=error, next=request.args.get('next', ''))


@auth_bp.route('/logout', methods=['POST'])
def logout():
    session.clear()
    return redirect(url_for('auth.login'))


@auth_bp.route('/plan/switch/<int:plan_id>', methods=['POST'])
def switch_plan(plan_id):
    """Wechselt den aktiven Plan des eingeloggten Nutzers (siehe
    templates/base.html: die Plan-Liste in der Seitenleiste) - nur erlaubt,
    wenn tatsächlich eine Mitgliedschaft für diesen Plan besteht, sonst
    bleibt session['active_plan_id'] unverändert (kein Fehler nötig: ein
    Nutzer ohne Zugriff sieht den fremden Plan im Rail-Menü gar nicht erst,
    ein manuell zusammengebauter Aufruf läuft hier einfach ins Leere)."""
    user = current_user()
    if user is not None and PlanMembership.query.filter_by(plan_id=plan_id, user_id=user.id).first():
        session['active_plan_id'] = plan_id
    return redirect(request.referrer or url_for('plan.index'))
