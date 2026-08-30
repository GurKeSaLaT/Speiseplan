"""Anlegen und Löschen eines ganzen Plans (siehe services/plans.py für die
eigentliche Logik) - anders als routes/sharing.py (Mitglieder/Stern EINES
bereits bestehenden Plans verwalten) geht es hier um den Plan als Ganzes.

Seit Pläne von Accounts entkoppelt sind (kein automatischer Plan mehr pro
Nutzer), ist "gar keinen Plan haben" ein normaler, erreichbarer Zustand
(z.B. direkt nach dem Löschen des letzten eigenen Plans) - siehe app.py:
require_login() für das globale Zero-Plan-Gate, das create_plan() dafür
auf seiner eigenen Allowlist führt."""

from flask import Blueprint, abort, redirect, request, url_for, session

from services.auth import current_user, user_has_plan_access
from services.plans import create_plan, delete_plan
from models import Plan

plans_bp = Blueprint('plans', __name__)


@plans_bp.route('/plan/create', methods=['POST'])
def create():
    """Legt einen neuen, eigenen Plan für den eingeloggten Nutzer an und
    wechselt sofort dorthin (session['active_plan_id']) - ein leerer/
    fehlender Name wird stillschweigend ignoriert (kein Fehlertext nötig,
    das Namensfeld im Modal ist bereits als "required" markiert, siehe
    templates/base.html)."""
    name = (request.form.get('name') or '').strip()
    if not name:
        return redirect(url_for('plan.index'))

    plan = create_plan(current_user(), name)
    session['active_plan_id'] = plan.id
    return redirect(url_for('plan.index'))


@plans_bp.route('/plan/<int:plan_id>/delete', methods=['POST'])
def delete(plan_id):
    """Löscht einen Plan unwiderruflich (siehe services/plans.py:
    delete_plan) - jedes Mitglied darf das, nicht nur der, der ihn
    ursprünglich angelegt hat (siehe models.py: Plan-Docstring, owner_user_id
    verleiht keine besonderen Rechte). War plan_id der gerade aktive Plan,
    wird die Session-Markierung entfernt, damit der nächste current_plan()-
    Aufruf frisch auf einen verbleibenden Plan (oder None) auflöst, statt
    auf eine ID zu zeigen, die es nicht mehr gibt."""
    user = current_user()
    if not user_has_plan_access(user, plan_id):
        abort(404)
    plan = Plan.query.get_or_404(plan_id)

    delete_plan(plan)
    if session.get('active_plan_id') == plan_id:
        session.pop('active_plan_id', None)
    return redirect(url_for('plan.index'))
