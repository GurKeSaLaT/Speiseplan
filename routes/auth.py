"""Login/Registrierung/Logout sowie das Umschalten des aktiven Plans
(siehe services/auth.py: current_plan() für die Auflösungsreihenfolge).
"""

from datetime import timedelta

from flask import Blueprint, redirect, render_template, request, session, url_for

from models import PlanMembership, User, db
from services.auth import EMAIL_PATTERN, current_user, hash_password, verify_password
from services.plans import accept_pending_invites

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
        email = (request.form.get('email') or '').strip().lower()
        password = request.form.get('password') or ''
        user = User.query.filter_by(email=email).first()

        if user and verify_password(user, password):
            session.clear()
            session['user_id'] = user.id
            session.permanent = True
            next_path = request.form.get('next') or ''
            destination = next_path if next_path.startswith('/') and not next_path.startswith('//') else url_for('plan.index')
            return redirect(destination)

        error = 'E-Mail-Adresse oder Passwort falsch.'

    return render_template('login.html', error=error, next=request.args.get('next', ''))


@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    """Zeigt das Registrierungsformular (templates/register.html, gleiches
    eigenständiges Seiten-Muster wie login.html) bzw. verarbeitet dessen
    Absenden. Erreichbar über den "Konto erstellen"-Button auf der
    Login-Seite, oder über einen Einladungs-Link (?email=<adresse>
    befüllt dann nur das Feld vor, ändert aber nichts an der eigentlichen
    Zuordnung - die läuft ausschließlich über die tatsächlich eingegebene
    E-Mail bei accept_pending_invites() unten).

    Nach erfolgreicher Registrierung sofort eingeloggt (wie nach einem
    normalen Login) und auf die Wochenplan-Startseite weitergeleitet -
    landet dort entweder direkt im per Einladung erhaltenen Plan
    (accept_pending_invites) oder, ohne passende Einladung, auf der
    Zero-Plan-Landing-Seite mit dem "eigenen Plan erstellen"-Formular
    (siehe routes/plan/pages.py: week_view())."""
    if current_user() is not None:
        return redirect(url_for('plan.index'))

    error = None
    name = ''
    email = request.args.get('email', '')
    if request.method == 'POST':
        name = (request.form.get('name') or '').strip()
        email = (request.form.get('email') or '').strip().lower()
        password = request.form.get('password') or ''

        if not name or not email or not password:
            error = 'Bitte Name, E-Mail-Adresse und Passwort angeben.'
        elif not EMAIL_PATTERN.match(email):
            error = 'Bitte eine gültige E-Mail-Adresse angeben.'
        elif User.query.filter_by(email=email).first() is not None:
            error = 'Für diese E-Mail-Adresse existiert bereits ein Konto.'
        else:
            user = User(name=name, email=email, password_hash=hash_password(password))
            db.session.add(user)
            db.session.flush()
            accept_pending_invites(user)

            session.clear()
            session['user_id'] = user.id
            session.permanent = True
            return redirect(url_for('plan.index'))

    return render_template('register.html', error=error, name=name, email=email)


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
