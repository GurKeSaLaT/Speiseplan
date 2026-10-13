"""Recipe trees are linked into other plans only as a whole (ADR 0001):
linking or unlinking any member applies to the whole tree, a follow-up link
that merges two trees links the merged tree into every plan either was in
(the recipe form warns which plans first), and removing a follow-up link
splits the tree while both parts stay in all their plans."""
import json
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


def _shared_into(app, plan_id):
    """Recipe ids linked into plan_id."""
    from models import RecipePlanLink
    with app.app_context():
        return sorted(l.recipe_id for l in RecipePlanLink.query.filter_by(plan_id=plan_id))


def _member_plan(app, make_user, user_id, name):
    """A plan of another user that user_id is a member of too."""
    from models import PlanMembership, db
    _owner_id, plan_id = make_user(name)
    with app.app_context():
        db.session.add(PlanMembership(plan_id=plan_id, user_id=user_id, is_starred=False))
        db.session.commit()
    return plan_id


def _save(client, recipe_id, name, category_id, follow_up_ids):
    form = MultiDict([("name", name), ("category_id", str(category_id)), ("servings", "2")])
    for follow_up_id in follow_up_ids:
        form.add("fu_recipe[]", str(follow_up_id))
        form.add("fu_min[]", "2")
        form.add("fu_max[]", "3")
    return client.post(f"/edit-recipe/{recipe_id}", data=form, headers=XHR)


def _merge_plans(client, recipe_id):
    html = client.get(f"/manage/recipe/edit/{recipe_id}").get_data(as_text=True)
    raw = re.search(r"window\.FOLLOW_UP_MERGE_PLANS = (\{.*?\});\n", html).group(1)
    return {int(k): v for k, v in json.loads(raw).items()}


# --- linking and unlinking a whole tree ---

def test_linking_any_member_links_the_whole_tree(app, client, make_user, make_recipe, make_category):
    other = _member_plan(app, make_user, client.user_id, "Familie")
    cat = make_category("Alles")
    braten = make_recipe("Braten", category_id=cat)
    ragout = make_recipe("Ragout", category_id=cat)
    lasagne = make_recipe("Lasagne", category_id=cat)
    salat = make_recipe("Salat", category_id=cat)
    sauce = make_recipe("Sauce", category_id=cat)
    _link(app, braten, ragout)
    _link(app, ragout, lasagne)
    _link(app, braten, sauce)

    resp = client.post(f"/manage/recipe/{lasagne}/link/{other}")

    assert resp.status_code == 302
    assert _shared_into(app, other) == sorted([braten, ragout, lasagne, sauce])
    assert salat not in _shared_into(app, other)


def test_linking_skips_members_the_target_plan_owns(app, client, make_user, make_recipe, make_category, test_plan_id):
    other = _member_plan(app, make_user, client.user_id, "Familie")
    braten = make_recipe("Braten", category_id=make_category("Alles"))
    ragout = make_recipe("Ragout", plan_id=other)
    _share(app, ragout, test_plan_id)
    _link(app, braten, ragout)

    client.post(f"/manage/recipe/{braten}/link/{other}")

    assert _shared_into(app, other) == [braten]


def test_unlinking_any_member_unlinks_the_whole_tree(app, client, make_user, make_recipe, make_category):
    other = _member_plan(app, make_user, client.user_id, "Familie")
    cat = make_category("Alles")
    braten = make_recipe("Braten", category_id=cat)
    ragout = make_recipe("Ragout", category_id=cat)
    salat = make_recipe("Salat", category_id=cat)
    _link(app, braten, ragout)
    for recipe_id in (braten, ragout, salat):
        _share(app, recipe_id, other)

    resp = client.post(f"/manage/recipe/{ragout}/unlink/{other}")

    assert resp.status_code == 302
    assert _shared_into(app, other) == [salat]


def test_unlinking_a_plan_that_owns_a_tree_member_is_refused(app, client, make_user, make_recipe, make_category, test_plan_id):
    other = _member_plan(app, make_user, client.user_id, "Familie")
    braten = make_recipe("Braten", category_id=make_category("Alles"))
    ragout = make_recipe("Ragout", plan_id=other)
    _share(app, ragout, test_plan_id)
    _share(app, braten, other)
    _link(app, braten, ragout)

    resp = client.post(f"/manage/recipe/{braten}/unlink/{other}")

    assert resp.status_code == 400
    assert "Ragout" in resp.get_data(as_text=True)
    assert _shared_into(app, other) == [braten]


def test_edit_page_says_plan_changes_apply_to_the_whole_tree(app, client, make_recipe, make_category):
    cat = make_category("Alles")
    braten = make_recipe("Braten", category_id=cat)
    ragout = make_recipe("Ragout", category_id=cat)
    _link(app, braten, ragout)

    html = client.get(f"/manage/recipe/edit/{braten}").get_data(as_text=True)

    assert "recipe tree with 2 recipes" in html


# --- merging trees ---

def test_merging_link_links_the_merged_tree_into_the_union_of_plans(app, client, make_user, make_recipe, make_category):
    familie = _member_plan(app, make_user, client.user_id, "Familie")
    _user, fremd = make_user("Fremd")
    cat = make_category("Alles")
    braten = make_recipe("Braten", category_id=cat)
    ragout = make_recipe("Ragout", category_id=cat)
    suppe = make_recipe("Suppe", category_id=cat)
    pfanne = make_recipe("Pfanne", category_id=cat)
    _link(app, braten, ragout)
    _link(app, suppe, pfanne)
    _share(app, braten, familie)
    _share(app, ragout, familie)
    _share(app, suppe, fremd)
    _share(app, pfanne, fremd)

    # Ragout -> Suppe hangs the Suppe tree under the Braten tree.
    resp = _save(client, ragout, "Ragout", cat, [suppe])

    assert resp.status_code == 200
    everything = sorted([braten, ragout, suppe, pfanne])
    assert _shared_into(app, familie) == everything
    assert _shared_into(app, fremd) == everything


def test_new_recipe_with_a_follow_up_from_a_linked_tree_joins_its_plans(app, client, make_user, make_recipe, make_category, test_plan_id):
    familie = _member_plan(app, make_user, client.user_id, "Familie")
    cat = make_category("Alles")
    suppe = make_recipe("Suppe", category_id=cat)
    _share(app, suppe, familie)

    client.post("/add-recipe", data={
        "name": "Eintopf", "category_id": str(cat), "servings": "2", "plan_id": str(test_plan_id),
        "fu_recipe[]": str(suppe), "fu_min[]": "2", "fu_max[]": "3",
    })

    from models import Recipe
    with app.app_context():
        eintopf = Recipe.query.filter_by(name="Eintopf").one().id
    assert _shared_into(app, familie) == sorted([suppe, eintopf])


def test_form_shows_the_plans_a_merging_link_adds(app, client, make_user, make_recipe, make_category):
    familie = _member_plan(app, make_user, client.user_id, "Familie")
    _user, fremd = make_user("Fremd")
    cat = make_category("Alles")
    braten = make_recipe("Braten", category_id=cat)
    ragout = make_recipe("Ragout", category_id=cat)
    suppe = make_recipe("Suppe", category_id=cat)
    eintopf = make_recipe("Eintopf", category_id=cat)
    _link(app, braten, ragout)
    _share(app, braten, familie)
    _share(app, ragout, familie)
    _share(app, suppe, fremd)

    merge_plans = _merge_plans(client, braten)

    # Suppe's tree is in "Fremd", Braten's in "Familie": both are affected.
    assert merge_plans[suppe] == ["Families Plan", "Fremds Plan"]
    # Eintopf is only in this plan: the Braten tree adds "Familie" for it.
    assert merge_plans[eintopf] == ["Families Plan"]
    # Ragout is already in Braten's tree: nothing changes.
    assert ragout not in merge_plans


# --- splitting a tree ---

def test_removing_a_follow_up_link_keeps_both_parts_in_all_plans(app, client, make_user, make_recipe, make_category):
    familie = _member_plan(app, make_user, client.user_id, "Familie")
    cat = make_category("Alles")
    braten = make_recipe("Braten", category_id=cat)
    ragout = make_recipe("Ragout", category_id=cat)
    lasagne = make_recipe("Lasagne", category_id=cat)
    _link(app, braten, ragout)
    _link(app, ragout, lasagne)
    for recipe_id in (braten, ragout, lasagne):
        _share(app, recipe_id, familie)

    resp = _save(client, braten, "Braten", cat, [])
    assert resp.status_code == 200
    assert _shared_into(app, familie) == sorted([braten, ragout, lasagne])

    # The parts are separate trees now: unlinking one leaves the other.
    client.post(f"/manage/recipe/{lasagne}/unlink/{familie}")
    assert _shared_into(app, familie) == [braten]
