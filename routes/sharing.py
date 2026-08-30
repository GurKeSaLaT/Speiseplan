"""Freigabe-/Sternverwaltung für Wochenpläne (/manage/sharing): wer ist
Mitglied des aktuell aktiven Plans, weitere Nutzer einladen/entfernen, und
welcher der eigenen Pläne gerade gesternt ist (siehe models.py:
Plan/PlanMembership sowie services/auth.py: current_plan()).

Alle Mitglieder eines Plans haben vollen Lese-/Schreibzugriff - es gibt
hier keine Rollen/Rechte-Unterscheidung zu verwalten, nur die reine
Mitgliedschaft (wer gehört dazu) und der pro-Nutzer-Stern (welcher Plan
ist gerade "der eigene").
"""

from flask import Blueprint, abort, redirect, render_template, request, url_for

from models import PlanMembership, User, db
from services.auth import current_plan, current_user

sharing_bp = Blueprint('sharing', __name__)


@sharing_bp.route('/manage/sharing')
def sharing_view():
    """Zeigt die Mitglieder des aktuell aktiven Plans (mit Entfernen-Option,
    außer für dessen Eigentümer - siehe remove_member()), ein Dropdown zum
    Einladen weiterer bekannter Nutzer, und die Liste ALLER Pläne des
    eingeloggten Nutzers mit Stern-Umschalter."""
    plan = current_plan()
    if plan is None:
        abort(404)

    member_ids = {m.user_id for m in PlanMembership.query.filter_by(plan_id=plan.id).all()}
    members = User.query.filter(User.id.in_(member_ids)).order_by(User.username).all() if member_ids else []
    invitable_users = User.query.filter(~User.id.in_(member_ids)).order_by(User.username).all() if member_ids else User.query.order_by(User.username).all()

    user = current_user()
    own_memberships = PlanMembership.query.filter_by(user_id=user.id).all()
    own_memberships.sort(key=lambda m: (not m.is_starred, m.plan.name))

    return render_template(
        'sharing.html', plan=plan, members=members, invitable_users=invitable_users,
        own_memberships=own_memberships,
    )


@sharing_bp.route('/manage/sharing/invite', methods=['POST'])
def invite_member():
    """Fügt einen bekannten Nutzer sofort (ohne Einladungs-/Bestätigungs-
    Workflow - es gibt kein Benachrichtigungssystem) als Mitglied des
    aktuell aktiven Plans hinzu, mit vollem Zugriff wie jedes andere
    Mitglied. Nicht gesternt: der eingeladene Nutzer entscheidet selbst
    (auf seiner eigenen /manage/sharing-Seite), ob er sich diesen Plan zu
    seinem Standard-Plan macht."""
    plan = current_plan()
    if plan is None:
        abort(404)

    user_id = request.form.get('user_id', type=int)
    invited = User.query.get(user_id) if user_id else None
    if invited and not PlanMembership.query.filter_by(plan_id=plan.id, user_id=invited.id).first():
        db.session.add(PlanMembership(plan_id=plan.id, user_id=invited.id, is_starred=False))
        db.session.commit()

    return redirect(url_for('sharing.sharing_view'))


@sharing_bp.route('/manage/sharing/remove/<int:user_id>', methods=['POST'])
def remove_member(user_id):
    """Entfernt ein Mitglied aus dem aktuell aktiven Plan - außer dessen
    Eigentümer (Plan.owner_user_id), der immer Mitglied bleibt, damit kein
    Plan ohne jeden Zugriff zurückbleibt. Entfernt sich ein Nutzer damit
    selbst aus einem Plan, der zufällig gerade sein aktiver war, löst der
    nächste current_plan()-Aufruf automatisch auf einen anderen (gesternten
    oder ersten verbliebenen) Plan um - keine Sonderbehandlung hier nötig."""
    plan = current_plan()
    if plan is None:
        abort(404)
    if user_id == plan.owner_user_id:
        abort(400)

    PlanMembership.query.filter_by(plan_id=plan.id, user_id=user_id).delete()
    db.session.commit()
    return redirect(url_for('sharing.sharing_view'))


@sharing_bp.route('/manage/sharing/star/<int:plan_id>', methods=['POST'])
def star_plan(plan_id):
    """Markiert plan_id als den einen gesternten Plan des eingeloggten
    Nutzers (öffnet sich künftig automatisch nach dem Login, steht oben in
    der Navigation) - entsternt dafür zuerst alle anderen Mitgliedschaften
    desselben Nutzers in derselben Transaktion, damit nie mehr als eine
    gleichzeitig gesternt ist (siehe models.py: PlanMembership-Docstring)."""
    user = current_user()
    membership = PlanMembership.query.filter_by(plan_id=plan_id, user_id=user.id).first()
    if membership is None:
        abort(404)

    PlanMembership.query.filter_by(user_id=user.id).update({PlanMembership.is_starred: False})
    membership.is_starred = True
    db.session.commit()
    return redirect(request.referrer or url_for('sharing.sharing_view'))
