"""Login/Session-Verwaltung und Zugriff auf den "aktiven Plan".

Bewusst ohne ein zusätzliches Paket wie Flask-Login umgesetzt: die App
kommt bislang mit vier Abhängigkeiten aus (siehe requirements.txt), und
alles Nötige - eine signierte Session sowie Passwort-Hashing - bringt
Flask/Werkzeug bereits mit (app.py: SECRET_KEY signiert dieselbe Session,
die auch CSRFProtect nutzt).

current_user()/current_plan() lesen NUR aus der bereits gesetzten Flask-
Session (session['user_id']/session['active_plan_id']) - das eigentliche
Setzen dieser Werte übernimmt ausschließlich routes/auth.py beim
Login/Plan-Wechsel. login_required() ist als Decorator vorhanden, wird in
dieser App aber nicht pro Route einzeln eingesetzt - app.py: require_login()
schützt stattdessen global über einen einzigen @app.before_request-Hook
alle Routen außer Login-Seite/statischen Dateien (deutlich weniger
fehleranfällig als das Risiko, eine einzelne Route beim @login_required
zu vergessen).
"""

from functools import wraps

from flask import g, redirect, session, url_for, request
from werkzeug.security import check_password_hash, generate_password_hash

from models import PlanMembership, User


def hash_password(raw_password):
    return generate_password_hash(raw_password)


def verify_password(user, raw_password):
    return check_password_hash(user.password_hash, raw_password)


def current_user():
    """Lädt den eingeloggten Nutzer (oder None, falls keine gültige Session
    besteht) - pro Request nur einmal geladen, über flask.g zwischengespeichert
    (g lebt nur für die Dauer EINES Requests, kein Caching über Requests
    hinweg nötig/gewollt)."""
    if 'user_id' not in session:
        return None
    if not hasattr(g, '_current_user'):
        g._current_user = User.query.get(session['user_id'])
        # Die Nutzer-ID in der Session existiert nicht mehr (z.B. Session
        # von einem inzwischen gelöschten Testkonto) - Session bereinigen,
        # statt bei jedem weiteren Zugriff erneut ins Leere zu laufen.
        if g._current_user is None:
            session.clear()
    return g._current_user


def current_plan():
    """Löst den gerade aktiven Plan des eingeloggten Nutzers auf (None, wenn
    niemand eingeloggt ist oder der Nutzer - eigentlich nie der Fall,
    siehe app.py: init_db() - noch in keinem einzigen Plan Mitglied ist).

    Reihenfolge: 1. der zuletzt per /plan/switch/<id> gewählte Plan
    (session['active_plan_id']), sofern der Nutzer dort noch Mitglied ist
    (könnte sich z.B. geändert haben, falls er zwischenzeitlich entfernt
    wurde) - 2. sonst der gesternte Plan (siehe PlanMembership.is_starred) -
    3. sonst irgendeine (die erste) bestehende Mitgliedschaft. Das Ergebnis
    wird zurück in die Session geschrieben, damit nachfolgende Requests
    direkt Fall 1 treffen, ohne erneut den Stern nachschlagen zu müssen."""
    user = current_user()
    if user is None:
        return None
    if hasattr(g, '_current_plan'):
        return g._current_plan

    active_id = session.get('active_plan_id')
    membership = None
    if active_id is not None:
        membership = PlanMembership.query.filter_by(plan_id=active_id, user_id=user.id).first()
    if membership is None:
        membership = PlanMembership.query.filter_by(user_id=user.id, is_starred=True).first()
    if membership is None:
        membership = PlanMembership.query.filter_by(user_id=user.id).first()

    g._current_plan = membership.plan if membership else None
    if g._current_plan is not None:
        session['active_plan_id'] = g._current_plan.id
    return g._current_plan


def login_required(view):
    """Nicht aktiv im Routing eingesetzt (siehe Modul-Docstring - app.py:
    require_login() übernimmt das global) - als eigenständiger Decorator
    trotzdem vorhanden, falls eine einzelne Route abweichend vom globalen
    Gate geschützt werden soll (z.B. innerhalb eines sonst offenen
    Blueprints)."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        if current_user() is None:
            return redirect(url_for('auth.login', next=request.path))
        return view(*args, **kwargs)
    return wrapped
