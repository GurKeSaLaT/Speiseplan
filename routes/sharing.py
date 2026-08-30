"""Freigabe-/Sternverwaltung für Wochenpläne (/manage/sharing): wer ist
Mitglied des aktuell aktiven Plans, weitere Nutzer einladen/entfernen, und
welcher der eigenen Pläne gerade gesternt ist (siehe models.py:
Plan/PlanMembership sowie services/auth.py: current_plan()).

Alle Mitglieder eines Plans haben vollen Lese-/Schreibzugriff - es gibt
hier keine Rollen/Rechte-Unterscheidung zu verwalten, nur die reine
Mitgliedschaft (wer gehört dazu) und der pro-Nutzer-Stern (welcher Plan
ist gerade "der eigene").
"""

from flask import Blueprint, abort, redirect, render_template, request, session, url_for

from models import PendingPlanInvite, PlanMembership, User, db
from services.auth import EMAIL_PATTERN, current_plan, current_user
from services.mail import send_invite_email

sharing_bp = Blueprint('sharing', __name__)


@sharing_bp.route('/manage/sharing')
def sharing_view():
    """Zeigt die Mitglieder des aktuell aktiven Plans (mit Entfernen-Option,
    außer für dessen Eigentümer - siehe remove_member()), ein E-Mail-Feld
    zum Einladen (siehe invite_member()), die noch offenen Einladungen an
    noch unregistrierte Adressen, und die Liste ALLER Pläne des
    eingeloggten Nutzers mit Stern-Umschalter."""
    plan = current_plan()
    if plan is None:
        abort(404)

    member_ids = {m.user_id for m in PlanMembership.query.filter_by(plan_id=plan.id).all()}
    members = User.query.filter(User.id.in_(member_ids)).order_by(User.name).all() if member_ids else []
    pending_invites = PendingPlanInvite.query.filter_by(plan_id=plan.id).order_by(PendingPlanInvite.invited_at).all()

    user = current_user()
    own_memberships = PlanMembership.query.filter_by(user_id=user.id).all()
    own_memberships.sort(key=lambda m: (not m.is_starred, m.plan.name))

    return render_template(
        'sharing.html', plan=plan, members=members, pending_invites=pending_invites,
        own_memberships=own_memberships,
    )


@sharing_bp.route('/manage/sharing/invite', methods=['POST'])
def invite_member():
    """Teilt den aktuell aktiven Plan mit einer eingegebenen E-Mail-Adresse:
    existiert dazu bereits ein Konto, wird sofort (ohne Einladungs-/
    Bestätigungs-Workflow) eine PlanMembership mit vollem Zugriff wie jedes
    andere Mitglied angelegt. Existiert noch keins, entsteht stattdessen
    eine PendingPlanInvite (siehe models.py-Docstring dort) und eine
    Einladung wird "verschickt" (services/mail.py: send_invite_email() -
    aktuell nur geloggt, der Link steht zusätzlich direkt auf dieser Seite,
    siehe templates/sharing.html: "Ausstehende Einladungen"). Nicht
    gesternt bzw. erst beim Registrieren ggf. gesternt (services/plans.py:
    accept_pending_invites()) - der eingeladene Nutzer entscheidet sonst
    selbst, ob er sich diesen Plan zu seinem Standard-Plan macht."""
    plan = current_plan()
    if plan is None:
        abort(404)

    email = (request.form.get('email') or '').strip().lower()
    if not email or not EMAIL_PATTERN.match(email):
        return redirect(url_for('sharing.sharing_view'))

    existing = User.query.filter_by(email=email).first()
    if existing:
        if not PlanMembership.query.filter_by(plan_id=plan.id, user_id=existing.id).first():
            db.session.add(PlanMembership(plan_id=plan.id, user_id=existing.id, is_starred=False))
            db.session.commit()
    else:
        if not PendingPlanInvite.query.filter_by(plan_id=plan.id, email=email).first():
            db.session.add(PendingPlanInvite(plan_id=plan.id, email=email))
            db.session.commit()
        send_invite_email(email, plan.name, url_for('auth.register', email=email, _external=True))

    return redirect(url_for('sharing.sharing_view'))


@sharing_bp.route('/manage/sharing/invite/<int:invite_id>/cancel', methods=['POST'])
def cancel_invite(invite_id):
    """Zieht eine noch offene Einladung an eine unregistrierte E-Mail-
    Adresse zurück - Gegenstück zu remove_member() für echte Mitglieder.
    Muss zum aktuell aktiven Plan gehören, sonst 404 (gleiches Muster wie
    die übrigen Besitz-Checks in dieser App)."""
    plan = current_plan()
    if plan is None:
        abort(404)

    invite = PendingPlanInvite.query.get_or_404(invite_id)
    if invite.plan_id != plan.id:
        abort(404)

    db.session.delete(invite)
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


@sharing_bp.route('/manage/sharing/leave/<int:plan_id>', methods=['POST'])
def leave_plan(plan_id):
    """Entfernt die EIGENE Mitgliedschaft an plan_id - das Gegenstück zu
    remove_member() oben (das ANDERE entfernt), hier für sich selbst und
    bewusst unabhängig vom gerade aktiven Plan (current_plan()): die
    "Meine Pläne"-Liste auf sharing.html zeigt ALLE eigenen Pläne, nicht
    nur den aktiven, ein Verlassen muss also für jeden davon einzeln
    funktionieren, ganz gleich welcher davon gerade aktiv ist.

    Der EIGENTÜMER eines Plans (Plan.owner_user_id) kann ihn NICHT auf
    diesem Weg verlassen - dafür gibt es delete_plan() (routes/plans.py),
    das den Plan bei mehreren Mitgliedern korrekt an ein anderes übergibt,
    statt ihn einfach ohne Eigentümer zurückzulassen."""
    user = current_user()
    membership = PlanMembership.query.filter_by(plan_id=plan_id, user_id=user.id).first()
    if membership is None:
        abort(404)
    plan = membership.plan
    if plan.owner_user_id == user.id:
        abort(400)

    db.session.delete(membership)
    db.session.commit()
    if session.get('active_plan_id') == plan_id:
        session.pop('active_plan_id', None)
    return redirect(url_for('sharing.sharing_view'))


@sharing_bp.route('/manage/sharing/overview-toggle/<int:plan_id>', methods=['POST'])
def toggle_overview(plan_id):
    """Schaltet PlanMembership.show_in_week_overview für die EIGENE
    Mitgliedschaft an plan_id um (siehe models.py-Docstring dort - ein rein
    pro Nutzer geltendes Flag, analog zu is_starred) - wirkt nie auf die
    Mitgliedschaft eines anderen Nutzers desselben, ggf. geteilten Plans."""
    user = current_user()
    membership = PlanMembership.query.filter_by(plan_id=plan_id, user_id=user.id).first()
    if membership is None:
        abort(404)

    membership.show_in_week_overview = not membership.show_in_week_overview
    db.session.commit()
    return redirect(request.referrer or url_for('sharing.sharing_view'))


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
