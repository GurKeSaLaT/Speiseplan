"""Selbstverwaltung des eigenen Kontos (Profil ändern, Passwort ändern,
Konto löschen) - siehe routes/account.py für die zugehörigen Routen.

Anders als services/auth.py (Login/Session/aktiver Plan) und
services/plans.py (Lebenszyklus EINES Plans) geht es hier um den Nutzer
selbst als Objekt, das sich ändern oder ganz auflösen lässt.
"""

from models import PlanMembership, User, db
from services.auth import EMAIL_PATTERN, hash_password, verify_password
from services.plans import delete_plan


def update_profile(user, name, email):
    """Ändert Name (freier Anzeigename, keine Eindeutigkeit nötig, siehe
    models.py: User-Docstring) und E-Mail (das LOGIN-Feld, muss daher
    weiterhin eindeutig und grob gültig sein). Gibt (True, None) bei
    Erfolg zurück, sonst (False, Fehlertext) - committet nur im
    Erfolgsfall."""
    name = (name or '').strip()
    email = (email or '').strip().lower()
    if not name or not email:
        return False, 'Bitte Name und E-Mail-Adresse angeben.'
    if not EMAIL_PATTERN.match(email):
        return False, 'Bitte eine gültige E-Mail-Adresse angeben.'
    existing = User.query.filter(User.email == email, User.id != user.id).first()
    if existing is not None:
        return False, 'Für diese E-Mail-Adresse existiert bereits ein anderes Konto.'

    user.name = name
    user.email = email
    db.session.commit()
    return True, None


def update_password(user, current_password, new_password):
    """Erfordert (anders als update_profile() oben) das AKTUELLE Passwort -
    eine schlichte Absicherung gegen eine übernommene, aber noch
    eingeloggte Sitzung (z.B. an einem gemeinsam genutzten Gerät), die
    sich sonst ohne jede weitere Hürde ins Konto einnisten könnte."""
    if not verify_password(user, current_password or ''):
        return False, 'Aktuelles Passwort ist falsch.'
    if not new_password:
        return False, 'Bitte ein neues Passwort angeben.'

    user.password_hash = hash_password(new_password)
    db.session.commit()
    return True, None


def delete_account(user):
    """Löscht das eigene Konto unwiderruflich, samt allem, was DADURCH
    verwaist. Für jede Plan-Mitgliedschaft des Nutzers:

    - Ist er das EINZIGE verbliebene Mitglied, verschwindet der ganze Plan
      mit ihm (services/plans.py: delete_plan() - übernimmt dabei bereits
      alles Nötige, u.a. noch anderswo verknüpfte Rezepte, was hier aber
      nicht greift, da ja niemand mehr übrig ist, der sie besitzen könnte).
    - Gibt es noch ANDERE Mitglieder, bleibt der Plan für sie bestehen -
      nur die eigene Mitgliedschaft wird entfernt. War der Nutzer dessen
      (rein informativer, siehe models.py: Plan-Docstring) Eigentümer,
      geht dieser Titel auf ein verbleibendes Mitglied über, damit der
      Plan nicht ganz ohne dasteht."""
    for membership in list(PlanMembership.query.filter_by(user_id=user.id).all()):
        plan = membership.plan
        other_member = PlanMembership.query.filter(
            PlanMembership.plan_id == plan.id, PlanMembership.user_id != user.id
        ).first()
        if other_member is None:
            delete_plan(plan)
        else:
            if plan.owner_user_id == user.id:
                plan.owner_user_id = other_member.user_id
            db.session.delete(membership)

    db.session.delete(user)
    db.session.commit()
