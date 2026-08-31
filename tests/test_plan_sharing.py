"""Tests for routes/sharing.py (invite/remove/star) as well as plan
isolation itself (data from one plan must not show up in another plan)
and services/auth.py: current_plan()."""
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
    """An invited user immediately gets full access (without any
    confirmation step) - can e.g. fill in a plan day right away."""
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
        # The user's own plan stays starred regardless - see app.py:
        # init_db() comment for the same principle with the seed accounts.
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
    """Only ONE plan of the same user may be starred at a time -
    star_plan() has to automatically remove the previous marking."""
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
    """/plan/switch/<id> may only set the active plan to a plan where a
    membership actually exists (see routes/auth.py: switch_plan) -
    otherwise the previously active plan remains in place."""
    _, other_plan_id = make_user("Fremd")

    client.post(f"/plan/switch/{other_plan_id}")
    # Direct test via a real action: the active plan must NOT have
    # changed to the foreign plan.
    resp = client.post("/day/2026-06-15/servings", json={"servings": 3})
    assert resp.status_code == 200

    from models import PlanDay
    with app.app_context():
        row = PlanDay.query.filter_by(date=date(2026, 6, 15)).first()
        assert row.plan_id == client.plan_id
        assert row.plan_id != other_plan_id


# --- Plan isolation: data from one plan must not show up in another ---

def test_week_view_does_not_show_other_plans_data(app, client, make_recipe, make_user):
    """Recipes themselves are deliberately GLOBAL (shared cookbook, see
    the models/plan.py comment on Plan) - "Fremdes Gericht" is therefore
    still allowed to show up in the client-side recipe search
    (window.PLAN_DATA.allRecipes). Only the actual PLANNING needs to be
    isolated: this day must not show an assigned main dish in the
    user's own plan just because an ANOTHER plan has one for the same
    calendar day."""
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
    assert b"no plan for this week" in resp.data

    match = re.search(r"window\.PLAN_DATA = (\{.*?\});", resp.get_data(as_text=True), re.S)
    plan_data = json.loads(match.group(1))
    assert plan_data["plan"][0] is None


def test_reroll_repetition_weighting_ignores_other_plans_history(app, client, make_recipe, make_user):
    """Only indirectly checkable via recent_usage_counts (see the unit
    test for that in test_services_planning.py) - here additionally
    making sure that a reroll in the user's own plan works at all,
    independent of whether a foreign plan filled with the SAME-NAMED
    entry exists (no cross-plan collision via the date column, see
    models/calendar.py: PlanDay.__table_args__)."""
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
    assert b"/register" in resp.data


def test_invite_rejects_malformed_email(app, client):
    from models import PendingPlanInvite

    resp = client.post("/manage/sharing/invite", data={"email": "keine-email"})
    assert resp.status_code == 302
    with app.app_context():
        assert PendingPlanInvite.query.count() == 0


def test_registering_with_invited_email_auto_joins_plan(app, client):
    """The actual core of the invitation flow: if someone later
    registers with EXACTLY the invited email, the PlanMembership is
    created immediately - without the client having to act again."""
    client.post("/manage/sharing/invite", data={"email": "neu@test.local"})

    test_client = app.test_client()
    resp = test_client.post("/register", data={"name": "Neu", "email": "neu@test.local", "password": "geheim123"})
    assert resp.status_code == 302

    from models import PendingPlanInvite, PlanMembership, User
    with app.app_context():
        user = User.query.filter_by(email="neu@test.local").first()
        membership = PlanMembership.query.filter_by(plan_id=client.plan_id, user_id=user.id).first()
        assert membership is not None
        # First (and only) membership of the new user -> starred,
        # see services/plans.py: accept_pending_invites().
        assert membership.is_starred is True
        assert PendingPlanInvite.query.filter_by(plan_id=client.plan_id, email="neu@test.local").first() is None

    # Immediately logged in and lands in the invited plan.
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
        # The plan and the owner's membership stay untouched.
        assert Plan.query.get(other_plan_id) is not None
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
