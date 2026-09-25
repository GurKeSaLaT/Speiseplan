"""Sharing (invite/remove/star/leave), plan switching and plan isolation."""
from datetime import date


def _email_for(app, user_id):
    from models import User, db
    with app.app_context():
        return db.session.get(User, user_id).email


def test_sharing_view_lists_owner_as_member(client):
    resp = client.get("/manage/sharing")
    assert resp.status_code == 200
    assert b"Testnutzer" in resp.data


def test_invite_member_grants_full_access(app, client, make_user, login_as):
    """No confirmation step: the invitee can edit the plan right away."""
    other_id, _ = make_user("Mitbewohner")

    resp = client.post("/manage/sharing/invite", data={"email": _email_for(app, other_id)})
    assert resp.status_code == 302

    from models import PlanMembership
    with app.app_context():
        assert PlanMembership.query.filter_by(plan_id=client.plan_id, user_id=other_id).first() is not None

    other_client = login_as(other_id)
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
        # Their own plan stays the starred one.
        own_membership = PlanMembership.query.filter_by(plan_id=own_plan_id, user_id=other_id).first()
        assert own_membership.is_starred is True


def test_invite_stars_first_membership_for_user_with_no_plan_yet(app, client):
    """Regression: a user without any plan got an unstarred membership, left
    no default plan and saw e.g. an empty category dropdown."""
    from models import User, PlanMembership, db

    with app.app_context():
        user = User(name="Ohne Plan", email="ohne-plan@example.com")
        db.session.add(user)
        db.session.commit()
        other_id = user.id
        assert PlanMembership.query.filter_by(user_id=other_id).count() == 0

    resp = client.post("/manage/sharing/invite", data={"email": "ohne-plan@example.com"})
    assert resp.status_code == 302

    with app.app_context():
        membership = PlanMembership.query.filter_by(plan_id=client.plan_id, user_id=other_id).first()
        assert membership is not None
        assert membership.is_starred is True


def test_migrate_ensure_starred_membership_repairs_existing_data(app, make_user):
    """Repairs data left by that bug, preferring the user's own plan."""
    from migrations import _migrate_ensure_starred_membership
    from models import Plan, PlanMembership, db

    owner_id, own_plan_id = make_user("Besitzerin")
    other_owner_id, other_plan_id = make_user("Andere Besitzerin")

    with app.app_context():
        # The buggy state: no starred membership at all.
        PlanMembership.query.filter_by(user_id=owner_id, plan_id=own_plan_id).update({"is_starred": False})
        db.session.add(PlanMembership(plan_id=other_plan_id, user_id=owner_id, is_starred=False))
        db.session.commit()
        assert PlanMembership.query.filter_by(user_id=owner_id, is_starred=True).count() == 0

        _migrate_ensure_starred_membership()

        starred = PlanMembership.query.filter_by(user_id=owner_id, is_starred=True).all()
        assert len(starred) == 1
        assert starred[0].plan_id == own_plan_id  # their OWN plan, not the other one

        # A user who already has a starred membership stays untouched.
        other_starred = PlanMembership.query.filter_by(user_id=other_owner_id, is_starred=True).first()
        assert other_starred is not None
        assert other_starred.plan_id == other_plan_id


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
    """Only one plan per user may be starred."""
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
    """Switching to a plan without membership keeps the current plan active."""
    _, other_plan_id = make_user("Fremd")

    client.post(f"/plan/switch/{other_plan_id}")
    resp = client.post("/day/2026-06-15/servings", json={"servings": 3})
    assert resp.status_code == 200

    from models import PlanDay
    with app.app_context():
        row = PlanDay.query.filter_by(date=date(2026, 6, 15)).first()
        assert row.plan_id == client.plan_id
        assert row.plan_id != other_plan_id


def test_switch_plan_always_lands_on_interactive_week_view(app, client, make_user):
    """Regression: switching must land on the new plan's current week, not
    the referrer - which may still carry the old plan's ?plan_id= and keep
    showing the old plan."""
    other_id, other_plan_id = make_user("Mitbewohner")
    from models import PlanMembership, db
    with app.app_context():
        db.session.add(PlanMembership(plan_id=other_plan_id, user_id=client.user_id, is_starred=False))
        db.session.commit()

    from datetime import date
    from services.planning import friday_of
    friday = friday_of(date.today()).isoformat()

    referrer = f"http://localhost/manage/recipe/edit-list?plan_id={client.plan_id}"
    resp = client.post(f"/plan/switch/{other_plan_id}", headers={"Referer": referrer})
    assert resp.status_code == 302
    assert resp.headers["Location"] == f"/plan/{friday}?plan_id={other_plan_id}"

    resp2 = client.post(f"/plan/switch/{client.plan_id}")
    assert resp2.status_code == 302
    assert resp2.headers["Location"] == f"/plan/{friday}?plan_id={client.plan_id}"


# --- Plan isolation: data from one plan must not show up in another ---

def test_week_view_does_not_show_other_plans_data(app, client, make_recipe, make_user):
    """Another plan's dish on the same date must not appear in this plan's
    calendar."""
    import json
    import re

    from models import PlanDay, db

    _, other_plan_id = make_user("Fremd")
    recipe_id = make_recipe("Fremdes Gericht")
    with app.app_context():
        db.session.add(PlanDay(plan_id=other_plan_id, date=date(2026, 6, 15), main_recipe_id=recipe_id, servings=2))
        db.session.commit()

    resp = client.get("/plan/2026-06-12")
    assert resp.status_code == 200
    assert b"no plan for this week" in resp.data

    match = re.search(r"window\.PLAN_DATA = (\{.*?\});", resp.get_data(as_text=True), re.S)
    plan_data = json.loads(match.group(1))
    assert plan_data["plan"][0] is None


def test_reroll_repetition_weighting_ignores_other_plans_history(app, client, make_recipe, make_user):
    """Two plans may have a row for the same date (unique per plan, not
    globally); the weighting itself is unit-tested in
    test_services_planning.py."""
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


# --- Invitation by email to an address NOT YET registered ---

def test_invite_unknown_email_creates_pending_invite_not_membership(app, client):
    from models import PendingPlanInvite, PlanMembership

    resp = client.post("/manage/sharing/invite", data={"email": "neu@test.local"})
    assert resp.status_code == 302

    with app.app_context():
        invite = PendingPlanInvite.query.filter_by(plan_id=client.plan_id, email="neu@test.local").first()
        assert invite is not None
        assert PlanMembership.query.filter_by(plan_id=client.plan_id).count() == 1  # only the client itself


def test_invite_unknown_email_shows_up_as_pending_on_sharing_page(client):
    client.post("/manage/sharing/invite", data={"email": "neu@test.local"})
    resp = client.get("/manage/sharing")
    assert b"neu@test.local" in resp.data
    # The invite link is just the app itself; joining happens on first login.
    assert b'value="http://localhost/"' in resp.data


def test_invite_rejects_malformed_email(app, client):
    from models import PendingPlanInvite

    resp = client.post("/manage/sharing/invite", data={"email": "keine-email"})
    assert resp.status_code == 302
    with app.app_context():
        assert PendingPlanInvite.query.count() == 0


def test_first_authentication_with_invited_email_auto_joins_plan(app, client):
    """The invited email's first login creates the membership."""
    client.post("/manage/sharing/invite", data={"email": "neu@test.local"})

    test_client = app.test_client()
    resp = test_client.get("/", headers={"Remote-Email": "neu@test.local", "Remote-Name": "Neu"})
    assert resp.status_code == 200

    from models import PendingPlanInvite, PlanMembership, User
    with app.app_context():
        user = User.query.filter_by(email="neu@test.local").first()
        membership = PlanMembership.query.filter_by(plan_id=client.plan_id, user_id=user.id).first()
        assert membership is not None
        assert membership.is_starred is True  # their first membership
        assert PendingPlanInvite.query.filter_by(plan_id=client.plan_id, email="neu@test.local").first() is None

    assert "not a member of any plan".encode("utf-8") not in resp.data


def test_cancel_invite_removes_pending_invite(app, client):
    client.post("/manage/sharing/invite", data={"email": "neu@test.local"})
    from models import PendingPlanInvite, db
    with app.app_context():
        invite_id = PendingPlanInvite.query.filter_by(plan_id=client.plan_id, email="neu@test.local").first().id

    resp = client.post(f"/manage/sharing/invite/{invite_id}/cancel")
    assert resp.status_code == 302
    with app.app_context():
        assert db.session.get(PendingPlanInvite, invite_id) is None


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
        assert db.session.get(PendingPlanInvite, invite_id) is not None


# --- /manage/sharing/leave (remove own membership) ---

def test_leave_plan_removes_own_membership_only(app, client, make_user):
    from models import PlanMembership, db

    other_user_id, other_plan_id = make_user("Planbesitzer")
    with app.app_context():
        db.session.add(PlanMembership(plan_id=other_plan_id, user_id=client.user_id, is_starred=False))
        db.session.commit()

    resp = client.post(f"/manage/sharing/leave/{other_plan_id}", follow_redirects=False)
    assert resp.status_code == 302

    from models import Plan
    with app.app_context():
        assert PlanMembership.query.filter_by(plan_id=other_plan_id, user_id=client.user_id).first() is None
        assert db.session.get(Plan, other_plan_id) is not None
        assert PlanMembership.query.filter_by(plan_id=other_plan_id, user_id=other_user_id).first() is not None


def test_leave_plan_rejected_for_owner(app, client):
    resp = client.post(f"/manage/sharing/leave/{client.plan_id}")
    assert resp.status_code == 400

    from models import PlanMembership
    with app.app_context():
        assert PlanMembership.query.filter_by(plan_id=client.plan_id, user_id=client.user_id).first() is not None


def test_leave_plan_requires_membership(client, make_user):
    _, other_plan_id = make_user("Fremd")
    resp = client.post(f"/manage/sharing/leave/{other_plan_id}")
    assert resp.status_code == 404


def test_leave_active_plan_resets_session_active_plan(app, client, make_user):
    from models import PlanMembership, db

    other_user_id, other_plan_id = make_user("Planbesitzer")
    with app.app_context():
        db.session.add(PlanMembership(plan_id=other_plan_id, user_id=client.user_id, is_starred=False))
        db.session.commit()

    client.post(f"/plan/switch/{other_plan_id}")
    client.post(f"/manage/sharing/leave/{other_plan_id}")

    with client.session_transaction() as sess:
        assert sess.get("active_plan_id") != other_plan_id
