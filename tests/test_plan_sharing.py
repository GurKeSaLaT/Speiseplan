"""Tests für routes/sharing.py (Einladen/Entfernen/Sternen) sowie die
Plan-Isolation selbst (Daten eines Plans dürfen in einem anderen Plan
nicht auftauchen) und services/auth.py: current_plan()."""
from datetime import date


def _login_as(app, user_id):
    test_client = app.test_client()
    with test_client.session_transaction() as sess:
        sess['user_id'] = user_id
    return test_client


def _email_for(app, user_id):
    from models import User
    with app.app_context():
        return User.query.get(user_id).email


def test_sharing_view_lists_owner_as_member(client):
    resp = client.get("/manage/sharing")
    assert resp.status_code == 200
    assert b"Testnutzer" in resp.data


def test_invite_member_grants_full_access(app, client, make_user):
    """Ein eingeladener Nutzer bekommt sofort (ohne Bestätigung) vollen
    Zugriff - kann z.B. direkt einen Tag im Plan befüllen."""
    other_id, _ = make_user("Mitbewohner")

    resp = client.post("/manage/sharing/invite", data={"email": _email_for(app, other_id)})
    assert resp.status_code == 302

    from models import PlanMembership
    with app.app_context():
        assert PlanMembership.query.filter_by(plan_id=client.plan_id, user_id=other_id).first() is not None

    other_client = _login_as(app, other_id)
    with other_client.session_transaction() as sess:
        sess['active_plan_id'] = client.plan_id
    resp = other_client.post("/day/2026-06-15/servings", json={"servings": 4})
    assert resp.status_code == 200


def test_invite_is_not_starred_for_invitee(app, client, make_user):
    other_id, own_plan_id = make_user("Mitbewohner")
    client.post("/manage/sharing/invite", data={"email": _email_for(app, other_id)})

    from models import PlanMembership
    with app.app_context():
        membership = PlanMembership.query.filter_by(plan_id=client.plan_id, user_id=other_id).first()
        assert membership.is_starred is False
        # Der eigene Plan bleibt weiterhin gesternt - siehe app.py:
        # init_db()-Kommentar zum selben Prinzip bei Jonas/Elo.
        own_membership = PlanMembership.query.filter_by(plan_id=own_plan_id, user_id=other_id).first()
        assert own_membership.is_starred is True


def test_remove_member_removes_access(app, client, make_user):
    other_id, _ = make_user("Mitbewohner")
    client.post("/manage/sharing/invite", data={"email": _email_for(app, other_id)})

    resp = client.post(f"/manage/sharing/remove/{other_id}")
    assert resp.status_code == 302

    from models import PlanMembership
    with app.app_context():
        assert PlanMembership.query.filter_by(plan_id=client.plan_id, user_id=other_id).first() is None


def test_remove_owner_is_rejected(client):
    resp = client.post(f"/manage/sharing/remove/{client.user_id}")
    assert resp.status_code == 400


def test_star_plan_switches_default_and_unstars_previous(app, client, make_user):
    """Nur EIN Plan desselben Nutzers darf gleichzeitig gesternt sein -
    star_plan() muss die vorherige Markierung automatisch entfernen."""
    other_owner_id, other_plan_id = make_user("Andere")
    with app.app_context():
        from models import PlanMembership, db
        db.session.add(PlanMembership(plan_id=other_plan_id, user_id=client.user_id, is_starred=False))
        db.session.commit()

    resp = client.post(f"/manage/sharing/star/{other_plan_id}")
    assert resp.status_code == 302

    from models import PlanMembership
    with app.app_context():
        memberships = {m.plan_id: m.is_starred for m in PlanMembership.query.filter_by(user_id=client.user_id).all()}
        assert memberships[other_plan_id] is True
        assert memberships[client.plan_id] is False


def test_star_plan_without_membership_returns_404(client, make_user):
    _, other_plan_id = make_user("Fremd")
    resp = client.post(f"/manage/sharing/star/{other_plan_id}")
    assert resp.status_code == 404


def test_switch_plan_requires_membership(app, client, make_user):
    """/plan/switch/<id> darf den aktiven Plan nur auf einen Plan setzen,
    in dem tatsächlich eine Mitgliedschaft besteht (siehe routes/auth.py:
    switch_plan) - sonst bleibt der bisherige aktive Plan bestehen."""
    _, other_plan_id = make_user("Fremd")

    client.post(f"/plan/switch/{other_plan_id}")
    # Direkter Test über eine echte Aktion: der aktive Plan darf sich NICHT
    # auf den fremden Plan geändert haben.
    resp = client.post("/day/2026-06-15/servings", json={"servings": 3})
    assert resp.status_code == 200

    from models import PlanDay
    with app.app_context():
        row = PlanDay.query.filter_by(date=date(2026, 6, 15)).first()
        assert row.plan_id == client.plan_id
        assert row.plan_id != other_plan_id


# --- Plan-Isolation: Daten eines Plans dürfen nicht in einem anderen auftauchen ---

def test_week_view_does_not_show_other_plans_data(app, client, make_recipe, make_user):
    """Rezepte selbst sind bewusst GLOBAL (gemeinsames Kochbuch, siehe
    models.py-Kommentar bei Plan) - "Fremdes Gericht" darf daher weiterhin
    in der clientseitigen Rezept-Suche (window.PLAN_DATA.allRecipes)
    auftauchen. Isoliert werden muss nur die tatsächliche PLANUNG: dieser
    Tag darf im eigenen Plan kein zugewiesenes Hauptgericht zeigen, nur
    weil ein ANDERER Plan für denselben Kalendertag eines hat."""
    import json
    import re

    from models import PlanDay, db

    _, other_plan_id = make_user("Fremd")
    recipe_id = make_recipe("Fremdes Gericht")
    with app.app_context():
        db.session.add(PlanDay(plan_id=other_plan_id, date=date(2026, 6, 15), main_recipe_id=recipe_id, servings=2))
        db.session.commit()

    resp = client.get("/plan/2026-06-15")
    assert resp.status_code == 200
    assert b"noch keinen Plan" in resp.data

    match = re.search(r"window\.PLAN_DATA = (\{.*?\});", resp.get_data(as_text=True), re.S)
    plan_data = json.loads(match.group(1))
    assert plan_data["plan"][0] is None


def test_reroll_repetition_weighting_ignores_other_plans_history(app, client, make_recipe, make_user):
    """Nur indirekt prüfbar über recent_usage_counts (siehe dortigen
    Unit-Test in test_services_planning.py) - hier zusätzlich sichergestellt,
    dass ein Reroll im eigenen Plan überhaupt unabhängig vom Vorhandensein
    eines GLEICHNAMIG befüllten fremden Plans funktioniert (keine
    Cross-Plan-Kollision über die date-Spalte, siehe models.py: PlanDay.
    __table_args__)."""
    from models import PlanDay, db

    recipe_a = make_recipe("Bei mir")
    make_recipe("Andere Option")
    _, other_plan_id = make_user("Fremd")
    with app.app_context():
        db.session.add(PlanDay(plan_id=client.plan_id, date=date(2026, 6, 15), main_recipe_id=recipe_a, servings=2))
        db.session.add(PlanDay(plan_id=other_plan_id, date=date(2026, 6, 15), main_recipe_id=recipe_a, servings=2))
        db.session.commit()

    resp = client.post("/day/2026-06-15/reroll-main")
    assert resp.status_code == 200


# --- /manage/sharing/overview-toggle (PlanMembership.show_in_week_overview) ---

def test_toggle_overview_flips_own_membership(app, client):
    from models import PlanMembership

    with app.app_context():
        membership = PlanMembership.query.filter_by(plan_id=client.plan_id, user_id=client.user_id).first()
        assert membership.show_in_week_overview is True

    resp = client.post(f"/manage/sharing/overview-toggle/{client.plan_id}")
    assert resp.status_code == 302

    with app.app_context():
        membership = PlanMembership.query.filter_by(plan_id=client.plan_id, user_id=client.user_id).first()
        assert membership.show_in_week_overview is False


def test_toggle_overview_only_affects_calling_users_own_membership(app, client, make_user):
    from models import PlanMembership, db

    other_id, _ = make_user("Mitbewohner")
    with app.app_context():
        db.session.add(PlanMembership(plan_id=client.plan_id, user_id=other_id, is_starred=False))
        db.session.commit()

    client.post(f"/manage/sharing/overview-toggle/{client.plan_id}")

    with app.app_context():
        other_membership = PlanMembership.query.filter_by(plan_id=client.plan_id, user_id=other_id).first()
        assert other_membership.show_in_week_overview is True


def test_toggle_overview_requires_own_membership(client, make_user):
    _, other_plan_id = make_user("Fremd")
    resp = client.post(f"/manage/sharing/overview-toggle/{other_plan_id}")
    assert resp.status_code == 404


# --- Einladung per E-Mail an eine NOCH NICHT registrierte Adresse ---

def test_invite_unknown_email_creates_pending_invite_not_membership(app, client):
    from models import PendingPlanInvite, PlanMembership

    resp = client.post("/manage/sharing/invite", data={"email": "neu@test.local"})
    assert resp.status_code == 302

    with app.app_context():
        invite = PendingPlanInvite.query.filter_by(plan_id=client.plan_id, email="neu@test.local").first()
        assert invite is not None
        assert PlanMembership.query.filter_by(plan_id=client.plan_id).count() == 1  # nur client selbst


def test_invite_unknown_email_shows_up_as_pending_on_sharing_page(client):
    client.post("/manage/sharing/invite", data={"email": "neu@test.local"})
    resp = client.get("/manage/sharing")
    assert b"neu@test.local" in resp.data
    assert b"/register" in resp.data


def test_invite_rejects_malformed_email(app, client):
    from models import PendingPlanInvite

    resp = client.post("/manage/sharing/invite", data={"email": "keine-email"})
    assert resp.status_code == 302
    with app.app_context():
        assert PendingPlanInvite.query.count() == 0


def test_registering_with_invited_email_auto_joins_plan(app, client):
    """Der eigentliche Kern des Einladungs-Flows: registriert sich später
    jemand mit GENAU der eingeladenen E-Mail, entsteht sofort die
    PlanMembership - ohne dass client noch einmal tätig werden muss."""
    client.post("/manage/sharing/invite", data={"email": "neu@test.local"})

    test_client = app.test_client()
    resp = test_client.post("/register", data={"name": "Neu", "email": "neu@test.local", "password": "geheim123"})
    assert resp.status_code == 302

    from models import PendingPlanInvite, PlanMembership, User
    with app.app_context():
        user = User.query.filter_by(email="neu@test.local").first()
        membership = PlanMembership.query.filter_by(plan_id=client.plan_id, user_id=user.id).first()
        assert membership is not None
        # Erste (und einzige) Mitgliedschaft des neuen Nutzers -> gesternt,
        # siehe services/plans.py: accept_pending_invites().
        assert membership.is_starred is True
        assert PendingPlanInvite.query.filter_by(plan_id=client.plan_id, email="neu@test.local").first() is None

    # Direkt eingeloggt und landet im eingeladenen Plan.
    resp = test_client.get("/")
    assert resp.status_code == 302
    resp = test_client.get(resp.headers["Location"])
    assert b"noch in keinem Plan Mitglied" not in resp.data


def test_cancel_invite_removes_pending_invite(app, client):
    client.post("/manage/sharing/invite", data={"email": "neu@test.local"})
    from models import PendingPlanInvite
    with app.app_context():
        invite_id = PendingPlanInvite.query.filter_by(plan_id=client.plan_id, email="neu@test.local").first().id

    resp = client.post(f"/manage/sharing/invite/{invite_id}/cancel")
    assert resp.status_code == 302
    with app.app_context():
        assert PendingPlanInvite.query.get(invite_id) is None


def test_cancel_invite_requires_own_plan(app, client, make_user):
    _, other_plan_id = make_user("Fremd")
    from models import PendingPlanInvite, db
    with app.app_context():
        invite = PendingPlanInvite(plan_id=other_plan_id, email="fremd@test.local")
        db.session.add(invite)
        db.session.commit()
        invite_id = invite.id

    resp = client.post(f"/manage/sharing/invite/{invite_id}/cancel")
    assert resp.status_code == 404
    with app.app_context():
        assert PendingPlanInvite.query.get(invite_id) is not None
