"""Recipe tree rules in the recipe form (ADR 0001): a follow-up recipe has
at most one source recipe and follow-up links never form a cycle. The form
only offers valid follow-up recipes; the server checks all links in the
database and rejects violations with a message naming the recipes."""
import re

from werkzeug.datastructures import MultiDict

XHR = {"X-Requested-With": "XMLHttpRequest"}


def _link(app, source_id, follow_up_id):
    from models import RecipeFollowUp, db
    with app.app_context():
        db.session.add(RecipeFollowUp(recipe_id=source_id, follow_up_recipe_id=follow_up_id))
        db.session.commit()


def _share(app, recipe_id, plan_id):
    from models import RecipePlanLink, db
    with app.app_context():
        db.session.add(RecipePlanLink(recipe_id=recipe_id, plan_id=plan_id))
        db.session.commit()


def _form(name, category_id, follow_up_ids):
    form = MultiDict([("name", name), ("category_id", str(category_id)), ("servings", "2")])
    for follow_up_id in follow_up_ids:
        form.add("fu_recipe[]", str(follow_up_id))
        form.add("fu_min[]", "2")
        form.add("fu_max[]", "3")
    return form


def _save(client, recipe_id, name, category_id, follow_up_ids):
    return client.post(f"/edit-recipe/{recipe_id}", data=_form(name, category_id, follow_up_ids), headers=XHR)


def _links(app, recipe_id):
    from models import RecipeFollowUp
    with app.app_context():
        return sorted(l.follow_up_recipe_id for l in RecipeFollowUp.query.filter_by(recipe_id=recipe_id))


def _offered(client, recipe_id=None):
    url = f"/manage/recipe/edit/{recipe_id}" if recipe_id else "/manage/recipe/create"
    html = client.get(url).get_data(as_text=True)
    ids = re.search(r"window\.FOLLOW_UP_CHOICES = (\[.*?\]);", html).group(1)
    return sorted(int(i) for i in re.findall(r"\d+", ids))


def _other_plan(make_user):
    _user_id, plan_id = make_user("Fremd")
    return plan_id


# --- form choices ---

def test_form_offers_only_follow_ups_without_source_and_not_ancestors(app, client, make_recipe, make_category):
    cat = make_category("Alles")
    braten = make_recipe("Braten", category_id=cat)
    ragout = make_recipe("Ragout", category_id=cat)
    lasagne = make_recipe("Lasagne", category_id=cat)
    suppe = make_recipe("Suppe", category_id=cat)
    pfanne = make_recipe("Pfanne", category_id=cat)
    _link(app, braten, ragout)
    _link(app, ragout, lasagne)
    _link(app, suppe, pfanne)

    # Lasagne: Braten and Ragout are its ancestors, Pfanne has a source, itself is out.
    assert _offered(client, lasagne) == [suppe]
    # Ragout keeps its own follow-up (Lasagne) on offer, but not its source Braten.
    assert _offered(client, ragout) == [lasagne, suppe]
    # A new recipe can take any recipe that has no source yet.
    assert _offered(client) == [braten, suppe]


def test_form_offers_none_with_a_source_in_an_invisible_plan(app, client, make_user, make_recipe, make_category, test_plan_id):
    other = _other_plan(make_user)
    cat = make_category("Alles")
    eigen = make_recipe("Eigenes", category_id=cat)
    fremd_quelle = make_recipe("Fremde Quelle", plan_id=other)
    geteilt = make_recipe("Geteilt", plan_id=other)
    _share(app, geteilt, test_plan_id)
    _link(app, fremd_quelle, geteilt)

    assert _offered(client, eigen) == []


# --- server-side rules ---

def test_second_source_is_rejected_with_a_message(app, client, make_recipe, make_category):
    cat = make_category("Alles")
    braten = make_recipe("Braten", category_id=cat)
    suppe = make_recipe("Suppe", category_id=cat)
    ragout = make_recipe("Ragout", category_id=cat)
    _link(app, braten, ragout)

    resp = _save(client, suppe, "Suppe neu", cat, [ragout])

    assert resp.status_code == 400
    error = resp.get_json()["error"]
    assert "Ragout" in error and "Braten" in error
    assert _links(app, suppe) == []
    with app.app_context():
        from models import Recipe, db
        assert db.session.get(Recipe, suppe).name == "Suppe"  # nothing of the post saved


def test_keeping_own_follow_up_is_not_a_second_source(app, client, make_recipe, make_category):
    cat = make_category("Alles")
    braten = make_recipe("Braten", category_id=cat)
    ragout = make_recipe("Ragout", category_id=cat)
    lasagne = make_recipe("Lasagne", category_id=cat)
    _link(app, braten, ragout)

    resp = _save(client, braten, "Braten", cat, [ragout, lasagne])

    assert resp.status_code == 200
    assert _links(app, braten) == sorted([ragout, lasagne])


def test_cycle_is_rejected_with_a_message_naming_the_cycle(app, client, make_recipe, make_category):
    cat = make_category("Alles")
    braten = make_recipe("Braten", category_id=cat)
    ragout = make_recipe("Ragout", category_id=cat)
    lasagne = make_recipe("Lasagne", category_id=cat)
    _link(app, braten, ragout)
    _link(app, ragout, lasagne)

    resp = _save(client, lasagne, "Lasagne", cat, [braten])

    assert resp.status_code == 400
    assert "Lasagne → Braten → Ragout → Lasagne" in resp.get_json()["error"]
    assert _links(app, lasagne) == []


def test_self_link_is_rejected_as_a_cycle(app, client, make_recipe, make_category):
    cat = make_category("Alles")
    braten = make_recipe("Braten", category_id=cat)

    resp = _save(client, braten, "Braten", cat, [braten])

    assert resp.status_code == 400
    assert "Braten → Braten" in resp.get_json()["error"]
    assert _links(app, braten) == []


def test_rules_see_links_invisible_to_the_plan(app, client, make_user, make_recipe, make_category, test_plan_id):
    other = _other_plan(make_user)
    cat = make_category("Alles")
    eigen = make_recipe("Eigenes", category_id=cat)
    fremd_quelle = make_recipe("Fremde Quelle", plan_id=other)
    geteilt = make_recipe("Geteilt", plan_id=other)
    _share(app, geteilt, test_plan_id)
    _link(app, fremd_quelle, geteilt)

    resp = _save(client, eigen, "Eigenes", cat, [geteilt])
    assert resp.status_code == 400
    error = resp.get_json()["error"]
    # The plan can't see the other source, so its name isn't given away.
    assert "Geteilt" in error and "another plan" in error and "Fremde Quelle" not in error

    # A cycle through a recipe the plan can't see: Geteilt2 -> Versteckt -> Eigenes2.
    eigen2 = make_recipe("Eigenes2", category_id=cat)
    versteckt = make_recipe("Versteckt", plan_id=other)
    geteilt2 = make_recipe("Geteilt2", plan_id=other)
    _share(app, geteilt2, test_plan_id)
    _link(app, geteilt2, versteckt)
    _link(app, versteckt, eigen2)

    resp = _save(client, eigen2, "Eigenes2", cat, [geteilt2])
    assert resp.status_code == 400
    assert "Eigenes2 → Geteilt2 → a recipe in another plan → Eigenes2" in resp.get_json()["error"]


def test_create_with_second_source_is_rejected_and_nothing_saved(app, client, make_recipe, make_category, test_plan_id):
    from models import Recipe
    cat = make_category("Alles")
    braten = make_recipe("Braten", category_id=cat)
    ragout = make_recipe("Ragout", category_id=cat)
    _link(app, braten, ragout)

    form = _form("Suppe", cat, [ragout])
    form.add("plan_id", str(test_plan_id))
    resp = client.post("/add-recipe", data=form)

    assert resp.status_code == 400
    assert "Braten" in resp.get_data(as_text=True)
    with app.app_context():
        assert Recipe.query.filter_by(name="Suppe").count() == 0
