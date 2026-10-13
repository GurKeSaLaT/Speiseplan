"""Recipe trees (Rezeptbäume, ADR 0001) as the unit of linking recipes into
other plans: a start recipe with all follow-up recipes below it, i.e. the
recipes connected by RecipeFollowUp links (over all links in the database,
not only those one plan can see). Linking or unlinking any member applies
to the whole tree; a follow-up link that merges two trees links the merged
tree into every plan either was in. Removing a follow-up link splits the
tree and removes no plan links, so both parts stay in all their plans."""

from flask_babel import gettext as _

from models import Plan, Recipe, RecipeFollowUp, RecipePlanLink, db


class TreeUnlinkError(ValueError):
    """The tree can't leave a plan that owns one of its recipes."""


def _neighbours():
    """recipe id -> ids it shares a follow-up link with (either direction)."""
    neighbours = {}
    for source_id, follow_up_id in db.session.query(RecipeFollowUp.recipe_id, RecipeFollowUp.follow_up_recipe_id):
        neighbours.setdefault(source_id, set()).add(follow_up_id)
        neighbours.setdefault(follow_up_id, set()).add(source_id)
    return neighbours


def _component(recipe_id, neighbours):
    tree = {recipe_id}
    queue = [recipe_id]
    while queue:
        for other_id in neighbours.get(queue.pop(), ()):
            if other_id not in tree:
                tree.add(other_id)
                queue.append(other_id)
    return tree


def tree_recipe_ids(recipe_id):
    """The ids of recipe_id's tree, recipe_id included."""
    return _component(recipe_id, _neighbours())


def _plans_by_recipe(recipe_ids):
    """recipe id -> plan ids it is in (owner plan plus linked plans)."""
    plans = {}
    for recipe_id, owner_plan_id in db.session.query(Recipe.id, Recipe.owner_plan_id).filter(Recipe.id.in_(recipe_ids)):
        plans.setdefault(recipe_id, set()).add(owner_plan_id)
    for recipe_id, plan_id in db.session.query(RecipePlanLink.recipe_id, RecipePlanLink.plan_id).filter(
        RecipePlanLink.recipe_id.in_(recipe_ids)
    ):
        plans.setdefault(recipe_id, set()).add(plan_id)
    return plans


def _tree_plan_ids(recipe_ids):
    return set().union(*_plans_by_recipe(recipe_ids).values())


def _link_into(recipe_ids, plan_ids):
    """Returns the (recipe id, plan id) pairs that were newly linked."""
    plans = _plans_by_recipe(recipe_ids)
    added = []
    for recipe_id in sorted(recipe_ids):
        for plan_id in sorted(plan_ids - plans.get(recipe_id, set())):
            db.session.add(RecipePlanLink(recipe_id=recipe_id, plan_id=plan_id))
            added.append((recipe_id, plan_id))
    return added


def link_tree(recipe_id, plan_id):
    """Links recipe_id's whole tree into plan_id (members it owns or already
    has stay as they are). No commit."""
    _link_into(tree_recipe_ids(recipe_id), {plan_id})


def unlink_tree(recipe_id, plan_id):
    """Removes recipe_id's whole tree from plan_id. Raises TreeUnlinkError if
    plan_id owns a member (it would keep a part of the tree). No commit."""
    tree = tree_recipe_ids(recipe_id)
    owned = Recipe.query.filter(Recipe.id.in_(tree), Recipe.owner_plan_id == plan_id).order_by(Recipe.name).all()
    if owned:
        raise TreeUnlinkError(_(
            "The recipe tree can't be removed from this plan, because %(recipes)s belongs to it.",
            recipes=", ".join(r.name for r in owned)))
    RecipePlanLink.query.filter(
        RecipePlanLink.recipe_id.in_(tree), RecipePlanLink.plan_id == plan_id
    ).delete(synchronize_session=False)


def complete_tree(recipe_id):
    """Links every recipe of recipe_id's tree into every plan any of them is
    in - after a follow-up link merged two trees. Flushes, no commit."""
    db.session.flush()
    _complete(tree_recipe_ids(recipe_id))


def _complete(tree):
    return _link_into(tree, _tree_plan_ids(tree))


def complete_all_trees():
    """complete_tree() for every tree - repairs trees that data from before
    the tree rules left partially linked. Returns the newly linked (recipe
    id, plan id) pairs. Flushes, no commit."""
    db.session.flush()
    neighbours = _neighbours()
    done, added = set(), []
    for recipe_id in sorted(neighbours):
        if recipe_id in done:
            continue
        tree = _component(recipe_id, neighbours)
        done |= tree
        added += _complete(tree)
    return added


def tree_owner_plan_ids(recipe_id):
    """Plans owning a recipe of recipe_id's tree; the tree can't leave them."""
    tree = tree_recipe_ids(recipe_id)
    return {owner for (owner,) in db.session.query(Recipe.owner_plan_id).filter(Recipe.id.in_(tree))}


def merge_plan_names(recipe, plan_id, candidate_ids):
    """{candidate id: sorted plan names} for the recipe form: the plans that
    get recipes they don't have yet if recipe (None = a new recipe in
    plan_id) takes candidate as a new follow-up - those of only one of the
    two trees. Candidates already in recipe's tree, or whose tree is in the
    same plans, are left out. For several new follow-ups at once, the union
    of their lists is exactly the set of affected plans."""
    neighbours = _neighbours()
    own_tree = _component(recipe.id, neighbours) if recipe is not None else set()
    own_plans = _tree_plan_ids(own_tree) if own_tree else {plan_id}
    result_ids = {}
    for candidate_id in candidate_ids:
        if candidate_id in own_tree:
            continue
        affected = own_plans ^ _tree_plan_ids(_component(candidate_id, neighbours))
        if affected:
            result_ids[candidate_id] = affected
    all_ids = set().union(*result_ids.values()) if result_ids else set()
    names = dict(db.session.query(Plan.id, Plan.name).filter(Plan.id.in_(all_ids))) if all_ids else {}
    return {candidate_id: sorted(names[i] for i in ids) for candidate_id, ids in result_ids.items()}
