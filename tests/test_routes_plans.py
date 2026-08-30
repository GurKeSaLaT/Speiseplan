"""Tests für routes/plans.py (/plan/create, /plan/<id>/delete) sowie das
Zero-Plan-Gate in app.py: require_login() - seit Pläne von Accounts
entkoppelt sind, ist "gar kein Plan" ein normaler, erreichbarer Zustand."""


def _login_as(app, user_id):
    test_client = app.test_client()
    with test_client.session_transaction() as sess:
        sess['user_id'] = user_id
    return test_client


# --- /plan/create ---

def test_create_plan_switches_active_plan_and_redirects(client):
    from models import PlanMembership

    resp = client.post("/plan/create", data={"name": "Zweiter Plan"}, follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/")

    with client.session_transaction() as sess:
        new_plan_id = sess["active_plan_id"]
    assert new_plan_id != client.plan_id


def test_create_plan_grants_membership_with_default_categories(app, client):
    from models import Category, Plan, PlanMembership

    client.post("/plan/create", data={"name": "Zweiter Plan"})

    with app.app_context():
        plan = Plan.query.filter_by(name="Zweiter Plan").first()
        assert plan is not None
        assert PlanMembership.query.filter_by(plan_id=plan.id, user_id=client.user_id).first() is not None
        assert Category.query.filter_by(plan_id=plan.id).count() == 7


def test_create_plan_ignores_blank_name(app, client):
    from models import Plan

    with app.app_context():
        before = Plan.query.count()
    client.post("/plan/create", data={"name": "   "})
    with app.app_context():
        assert Plan.query.count() == before


# --- /plan/<id>/delete ---

def test_delete_plan_requires_membership(app, client, make_user):
    _, other_plan_id = make_user("Fremd")
    resp = client.post(f"/plan/{other_plan_id}/delete")
    assert resp.status_code == 404

    from models import Plan
    with app.app_context():
        assert Plan.query.get(other_plan_id) is not None


def test_delete_plan_allowed_for_any_member_not_just_owner(app, client, make_user):
    """Jedes Mitglied darf löschen, nicht nur der Eigentümer (siehe
    models.py: Plan-Docstring - owner_user_id verleiht keine besonderen
    Rechte)."""
    from models import Plan, PlanMembership, db

    other_user_id, _ = make_user("Mitbewohner")
    with app.app_context():
        db.session.add(PlanMembership(plan_id=client.plan_id, user_id=other_user_id, is_starred=False))
        db.session.commit()

    other_client = _login_as(app, other_user_id)
    resp = other_client.post(f"/plan/{client.plan_id}/delete", follow_redirects=False)
    assert resp.status_code == 302

    with app.app_context():
        assert Plan.query.get(client.plan_id) is None


def test_delete_last_plan_resolves_to_zero_plan_landing_page(client):
    resp = client.post(f"/plan/{client.plan_id}/delete", follow_redirects=True)
    assert resp.status_code == 200
    assert "noch in keinem Plan Mitglied".encode("utf-8") in resp.data


def test_delete_active_plan_switches_to_remaining_membership(app, client):
    """Wird der GERADE AKTIVE Plan gelöscht, während der Nutzer noch
    mindestens einen weiteren Plan hat, löst current_plan() nach dem
    Löschen automatisch auf diesen anderen Plan um."""
    from models import PlanMembership, db

    other_plan_id = None
    resp = client.post("/plan/create", data={"name": "Ausweichplan"}, follow_redirects=False)
    with client.session_transaction() as sess:
        other_plan_id = sess["active_plan_id"]

    # Zurück zum ursprünglichen Plan wechseln, DANN diesen löschen.
    client.post(f"/plan/switch/{client.plan_id}")
    resp = client.post(f"/plan/{client.plan_id}/delete", follow_redirects=True)
    assert resp.status_code == 200
    assert "noch in keinem Plan Mitglied".encode("utf-8") not in resp.data

    with client.session_transaction() as sess:
        assert sess["active_plan_id"] == other_plan_id


# --- Zero-Plan-Gate (app.py: require_login) ---

def test_user_without_any_plan_is_redirected_to_plan_index(app, make_user):
    from models import PlanMembership, User, db

    user_id, plan_id = make_user("Planlos")
    with app.app_context():
        PlanMembership.query.filter_by(user_id=user_id).delete()
        db.session.commit()

    planless_client = _login_as(app, user_id)
    resp = planless_client.get("/manage/sharing", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["Location"] == "/"


def test_user_without_any_plan_can_still_reach_create_and_logout(app, make_user):
    from models import PlanMembership, db

    user_id, plan_id = make_user("Planlos2")
    with app.app_context():
        PlanMembership.query.filter_by(user_id=user_id).delete()
        db.session.commit()

    planless_client = _login_as(app, user_id)
    resp = planless_client.post("/plan/create", data={"name": "Endlich ein Plan"}, follow_redirects=False)
    assert resp.status_code == 302

    with app.app_context():
        assert PlanMembership.query.filter_by(user_id=user_id).count() == 1


# --- /plan/<id>/rename ---

def test_rename_plan_updates_name(app, client):
    resp = client.post(f"/plan/{client.plan_id}/rename", data={"name": "Neuer Planname"}, follow_redirects=False)
    assert resp.status_code == 302

    from models import Plan
    with app.app_context():
        assert Plan.query.get(client.plan_id).name == "Neuer Planname"


def test_rename_plan_ignores_blank_name(app, client):
    from models import Plan
    with app.app_context():
        original_name = Plan.query.get(client.plan_id).name

    client.post(f"/plan/{client.plan_id}/rename", data={"name": "   "})

    with app.app_context():
        assert Plan.query.get(client.plan_id).name == original_name


def test_rename_plan_allowed_for_any_member_not_just_owner(app, client, make_user):
    from models import Plan, PlanMembership, db

    other_user_id, _ = make_user("Mitbewohner")
    with app.app_context():
        db.session.add(PlanMembership(plan_id=client.plan_id, user_id=other_user_id, is_starred=False))
        db.session.commit()

    other_client = _login_as(app, other_user_id)
    resp = other_client.post(f"/plan/{client.plan_id}/rename", data={"name": "Von Mitbewohner umbenannt"})
    assert resp.status_code == 302

    with app.app_context():
        assert Plan.query.get(client.plan_id).name == "Von Mitbewohner umbenannt"


def test_rename_plan_requires_membership(app, client, make_user):
    from models import Plan

    _, other_plan_id = make_user("Fremd")
    with app.app_context():
        original_name = Plan.query.get(other_plan_id).name

    resp = client.post(f"/plan/{other_plan_id}/rename", data={"name": "Übernommen"})
    assert resp.status_code == 404

    with app.app_context():
        assert Plan.query.get(other_plan_id).name == original_name
