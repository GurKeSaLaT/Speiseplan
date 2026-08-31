"""Core planning logic of the app: everything that determines WHICH
weekday has WHICH date and WHICH recipe ends up on a given day.

Three related areas of responsibility in this file:

1. Week/date helpers (monday_of, week_dates_for, parse_iso_date,
   week_neighbor_exclude_ids, week_side_recipe_ids): convert between a
   "week-start date" and its seven associated calendar days, and
   determine which recipes are already planned in the same calendar
   week - handled separately for main dishes (one value per day) and
   side dishes (any number per day, see models.py: PlanDaySide), since
   the two differ structurally.

2. Category balance (assign_balanced_categories): decides, when
   auto-filling a week, which CATEGORY (not which recipe) goes on which
   day - distributed as evenly as possible across all categories and,
   where possible, without repeating on consecutive days.

3. Recipe selection (choose_recipe, weighted_recipe_choice,
   recent_usage_counts, jsonify_recipe, jsonify_side): then actually
   picks ONE concrete recipe from a category/pool, taking into account
   favorite weighting, season availability, and a soft repetition
   weighting (the more often a recipe recently appeared in the plan, the
   less often it gets picked again - not a hard block, see
   recent_usage_counts). jsonify_recipe/jsonify_side serialize the
   result for the JSON responses of the AJAX endpoints in routes/plan/.

Used by the routes/plan/ package both when generating a whole new week
(pages.py) and for a single-day reroll via HTTP endpoints (day_actions.py).
"""

import random
from collections import Counter
from datetime import date, timedelta

from flask_babel import lazy_gettext as _l

from models import db, Recipe, PlanDay, PlanDaySide
from services.recipe_visibility import visible_recipes_query
from services.seasons import recipe_available_now
from services.ingredient_aliases import normalize_ingredient_name
from services.settings import get_display_units
from services.units import convert_for_display

# Weekday names in ISO order (Monday = index 0), matching date.weekday().
# Passed through both for computing the week start and as the "days"
# context variable to the plan.html/create_week.html templates, so the
# name isn't maintained twice. lazy_gettext (not gettext): this is a
# module-level constant evaluated at import time, outside any request.
DAY_NAMES = [_l('Monday'), _l('Tuesday'), _l('Wednesday'), _l('Thursday'), _l('Friday'), _l('Saturday'), _l('Sunday')]

# How much more likely a recipe marked as a favorite is to be picked
# during automatic/random selection, compared to a non-favorite recipe
# (3 = three times as likely). A pure taste/mood weighting, not a hard
# filter - non-favorites always stay in the selection pool.
FAVORITE_WEIGHT = 3

# How many weeks back recent_usage_counts() looks for the soft repetition
# weighting - uses further back than this no longer count. A separate
# constant on purpose, in case practice shows a different window works
# better.
REPETITION_LOOKBACK_WEEKS = 8


def recent_usage_counts(recipe_ids, reference_date, is_side_dish, plan_id):
    """For each of the given recipe IDs, counts how often it was used in
    the plan calendar in the REPETITION_LOOKBACK_WEEKS weeks BEFORE
    reference_date. Returns a dict {recipe ID: count} - recipes with no
    use at all in this period are simply absent from it (no entry with 0).

    is_side_dish distinguishes WHICH table is queried: main dishes live
    directly in PlanDay.main_recipe_id (one value per day), side dishes
    in the separate PlanDaySide table instead (any number per day, see
    models.py) - the two pools are counted separately since they're never
    mixed during selection anyway (see choose_recipe).

    reference_date is deliberately NOT date.today(), but the day currently
    being planned for - week planning also allows past or future weeks,
    and the count should always relate to the period IMMEDIATELY BEFORE
    the day in question, regardless of the actual current date.

    plan_id restricts the count to ONE plan (see models.py:
    PlanDay.plan_id) - a plan's repetition weighting should only be based
    on ITS OWN history, not that of a completely different, shared plan.

    Used by choose_recipe() to hand weighted_recipe_choice() a soft
    (non-exclusive) repetition weighting - see there.
    """
    if not recipe_ids:
        return {}
    since = reference_date - timedelta(weeks=REPETITION_LOOKBACK_WEEKS)

    if is_side_dish:
        rows = (
            db.session.query(PlanDaySide.recipe_id)
            .join(PlanDay, PlanDaySide.plan_day_id == PlanDay.id)
            .filter(
                PlanDay.plan_id == plan_id, PlanDay.date >= since, PlanDay.date < reference_date,
                PlanDaySide.recipe_id.in_(recipe_ids)
            )
            .all()
        )
        return Counter(rid for (rid,) in rows)

    rows = PlanDay.query.filter(
        PlanDay.plan_id == plan_id, PlanDay.date >= since, PlanDay.date < reference_date,
        PlanDay.main_recipe_id.in_(recipe_ids)
    ).all()
    return Counter(pd.main_recipe_id for pd in rows)


def weighted_recipe_choice(recipes, usage_counts=None):
    """Randomly picks a recipe from a list, functionally like
    random.choice(), but weighted by two independent criteria that are
    combined multiplicatively:

    1. Favorites (is_favorite) get FAVORITE_WEIGHT times the base
       weighting compared to everything else (base weight 1).
    2. Soft repetition weighting: usage_counts (see recent_usage_counts,
       optional - if absent, this function behaves as it did before this
       weighting was introduced) indicates how often a recipe recently
       appeared in the plan. The factor 1/(count+1) makes the probability
       DECREASE with each additional recent use (never used: factor 1,
       once: 0.5, twice: 0.33, ...), but it NEVER drops to 0 - unlike a
       hard block, every recipe theoretically stays selectable, just less
       likely.

    Since choose_recipe() only calls this function AFTER season filtering
    (see there), this automatically also favors currently seasonal
    recipes, with no need for a third factor here: when season
    pre-filtering is active, simply only seasonal candidates remain in
    the pool at all, which are then weighted as usual among themselves.

    random.choices() (note the s!) does the actual weighted draw; k=1
    returns exactly one element, which is unpacked via [0].
    """
    usage_counts = usage_counts or {}
    weights = [
        (FAVORITE_WEIGHT if r.is_favorite else 1) / (usage_counts.get(r.id, 0) + 1)
        for r in recipes
    ]
    return random.choices(recipes, weights=weights, k=1)[0]


# --- WEEK CALENDAR HELPERS ---
# The week plan works throughout with real calendar days (date objects),
# not an abstract "day 0-6" concept without a date reference. These four
# small functions are the only place where conversion happens between
# "some date" and "Monday start of a calendar week".

def monday_of(d):
    """Returns the Monday of the calendar week that date d falls in.
    date.weekday() returns 0 for Monday through 6 for Sunday, so exactly
    that many days are subtracted from d's distance from its week start."""
    return d - timedelta(days=d.weekday())


def week_dates_for(start):
    """Builds the list of the 7 calendar days of the week from a start
    date (assumed to be a Monday), Monday first. It is NOT checked
    whether start is actually a Monday - monday_of() takes care of that
    beforehand at the call sites (see routes/plan/)."""
    return [start + timedelta(days=i) for i in range(7)]


def parse_iso_date(value):
    """Parses a string in ISO format ("YYYY-MM-DD", e.g. from a URL path
    segment or an <input type="date">) into a date object. Returns None
    instead of raising an exception on invalid or missing input, so
    callers (typically route handlers) can respond consistently with a
    404/400 instead of a 500 error."""
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def week_neighbor_exclude_ids(day_date, plan_id):
    """Collects the main-dish recipe IDs of all OTHER days in the same
    calendar week as day_date, WITHIN ONE plan (plan_id, see models.py:
    PlanDay.plan_id) - for duplicate avoidance when (re-)rolling a main
    dish (see week_side_recipe_ids below for the side-dish counterpart,
    which works differently since a day there can have multiple entries
    at once).

    day_date itself is deliberately EXCLUDED (see "if pd.date ==
    day_date: continue") - the day currently being re-rolled shouldn't
    count its own current recipe as "taken" against itself. The callers
    in routes/plan/day_actions.py explicitly re-add the target day's
    current recipe when needed, to prevent a reroll from drawing the same
    recipe again.
    """
    start = monday_of(day_date)
    dates = week_dates_for(start)
    rows = PlanDay.query.filter(PlanDay.plan_id == plan_id, PlanDay.date.in_(dates)).all()
    ids = set()
    for pd in rows:
        if pd.date == day_date:
            continue
        if pd.main_recipe_id:
            ids.add(pd.main_recipe_id)
    return ids


def week_side_recipe_ids(day_date, plan_id):
    """Collects the recipe IDs of ALL side dishes already used anywhere
    in the calendar week that day_date falls in - within one plan, across
    all 7 days, without excluding any particular day or side dish.

    Unlike week_neighbor_exclude_ids() (which deliberately excludes the
    day in question itself, so a reroll doesn't count its own current
    recipe as "taken against itself"), no such exception is needed here:
    since a day can have multiple side dishes at once, rerolling ONE side
    dish could otherwise accidentally duplicate another side dish already
    present on the SAME day - so that day's side dishes must stay
    excluded too. The side dish currently being re-rolled is already part
    of this set anyway (it's already assigned) - which automatically
    prevents a reroll from returning the same recipe again, without any
    special case of its own.
    """
    start = monday_of(day_date)
    dates = week_dates_for(start)
    rows = (
        db.session.query(PlanDaySide.recipe_id)
        .join(PlanDay, PlanDaySide.plan_day_id == PlanDay.id)
        .filter(PlanDay.plan_id == plan_id, PlanDay.date.in_(dates))
        .all()
    )
    return {rid for (rid,) in rows}


# --- CATEGORY BALANCE & RECIPE SELECTION ---

def assign_balanced_categories(all_categories, days_to_fill, final_plan, preexisting_counts=None):
    """Assigns a category to each day still to be filled (days_to_fill, a
    list of day indices 0-6 within ONE week) - not yet a concrete recipe,
    just the category a recipe will later be drawn from (see
    choose_recipe).

    Two goals are pursued at the same time, with a clear priority:
    1. (higher priority) Where possible, never the same category as the
       direct predecessor or successor day - so, e.g., Monday AND Tuesday
       aren't both "Pasta". Days already fixed (which already have a
       recipe, visible in final_plan) count as a known neighbor here even
       if they aren't being newly assigned themselves.
    2. (lower priority) As even a distribution of categories as possible
       across all 7 days of the week (see counts/preexisting_counts).

    If goal 1 can't be reached (e.g. because only a single category
    exists in total), the neighbor rule is silently relaxed in favor of
    goal 2 - it's more important that every day gets a category at all
    than enforcing the neighbor rule at any cost.

    The prioritization is implemented via sort_key(): a tuple
    (is_neighbor_category, current_count). Since False < True in Python,
    non-neighbor categories always sort before neighbor categories, and
    within each of these two groups, the category used least so far
    wins. min() over all sort_key() values then finds the best reachable
    compromise; random.choice() adds variety among several equally good
    candidates.

    Returns a dict {day index: category ID}, one per entry in
    days_to_fill.
    """
    cat_ids = [c.id for c in all_categories]
    if not cat_ids:
        return {}

    # Initial counter state: days already fixed flow into the balance via
    # preexisting_counts, so the automatic selection is NOT based only on
    # its own 7 (or fewer) newly assigned slots, but on the whole week.
    counts = Counter(preexisting_counts or {})
    for cid in cat_ids:
        counts.setdefault(cid, 0)

    # Known neighbors at the start: all days that already have a fixed
    # recipe (final_plan[i] is already set). Extended over the course of
    # the loop with each freshly assigned day, so that e.g. with two
    # consecutive free days, the first is also recognized as a neighbor
    # of the second.
    known_category_by_day = {
        i: final_plan[i].category_id for i in range(7) if final_plan[i] is not None
    }

    assigned = {}
    for day_index in days_to_fill:
        # Categories of the direct neighbor days (previous/next day), as
        # far as already known. Days outside 0-6 (which wouldn't exist)
        # are filtered out by the range check.
        neighbor_cats = {
            known_category_by_day[n] for n in (day_index - 1, day_index + 1)
            if 0 <= n <= 6 and n in known_category_by_day
        }

        def sort_key(cid):
            return (cid in neighbor_cats, counts[cid])

        best_key = min(sort_key(cid) for cid in cat_ids)
        candidates = [cid for cid in cat_ids if sort_key(cid) == best_key]
        choice = random.choice(candidates)

        assigned[day_index] = choice
        counts[choice] += 1
        # Record immediately, so the NEXT day in this loop already takes
        # this one into account as a known neighbor.
        known_category_by_day[day_index] = choice

    return assigned


def choose_recipe(is_side_dish, exclude_ids, plan_id, category_id=None, prefer_season=True, reference_date=None):
    """The central recipe-selection function: picks ONE suitable,
    not-yet-used recipe from the database. Called both when generating a
    whole week and on every single-day reroll.

    plan_id restricts the selection pool to the recipes visible to THIS
    plan (owner OR linked via RecipePlanLink, see
    services/recipe_visibility.py) and is also passed through to
    recent_usage_counts() (see below), so the repetition weighting is
    also based on the history of EXACTLY this plan, not that of another,
    completely independent plan.

    Filter order:
    1. is_side_dish strictly separates the main-dish and side-dish pools -
       the two are never mixed.
    2. exclude_ids excludes recipes that (depending on the caller) are
       already used in the same week or are the recipe currently on this
       day (prevents duplicates or a "reroll" landing on the same
       result). This is the only HARD exclusion rule here - everything
       below is soft weighting, not a further exclusion.
    3. category_id (optional) additionally restricts to a specific
       category - used during automatic filling to actually hit the
       category determined by assign_balanced_categories(). If left
       empty (None), any category is eligible (fallback for when the
       desired category has no candidates left).

    If no candidate remains after these three filters, None is returned
    immediately (no further fallback here - that's left to the callers,
    e.g. via a second choose_recipe() call without category_id).

    Season preference comes next (prefer_season, default: on): among the
    remaining candidates, an attempt is first made to draw only from
    those CURRENTLY seasonally available (recipe_available_now()). If at
    least one exists, selection happens ONLY from this subset; if none
    exists at all (e.g. because this category only has winter recipes and
    it's currently summer), it silently falls back to ALL candidates - a
    season assignment must never completely block automatic selection.

    reference_date (the day currently being drawn for) controls the soft
    repetition weighting: recent_usage_counts() counts how often each
    remaining candidate was already used in the REPETITION_LOOKBACK_WEEKS
    weeks BEFORE this day, and weighted_recipe_choice() reduces their
    draw probability accordingly (never to 0 - see there). If
    reference_date is left empty (None), no repetition weighting takes
    place (only favorites count as before) - doesn't occur in the current
    app, all callers pass the day, but it's a harmless fallback for e.g.
    future calls outside a calendar-day context.

    In both cases, weighted_recipe_choice() (not a plain random.choice())
    ultimately decides, so favorites and rarely used recipes are
    preferred among the remaining candidates.
    """
    base_query = visible_recipes_query(plan_id).filter(
        Recipe.is_side_dish.is_(is_side_dish),
        ~Recipe.id.in_(exclude_ids)
    )
    if category_id is not None:
        base_query = base_query.filter(Recipe.category_id == category_id)

    candidates = base_query.all()
    if not candidates:
        return None

    usage_counts = {}
    if reference_date is not None:
        usage_counts = recent_usage_counts([r.id for r in candidates], reference_date, is_side_dish, plan_id)

    if prefer_season:
        seasonal_candidates = [r for r in candidates if recipe_available_now(r)]
        if seasonal_candidates:
            return weighted_recipe_choice(seasonal_candidates, usage_counts)

    return weighted_recipe_choice(candidates, usage_counts)


def jsonify_recipe(recipe, plan_id):
    """Serializes a Recipe ORM object into a plain dict that can be
    returned either directly as a Flask JSON response (Flask
    automatically converts a returned dict into a JSON response) or
    embedded into the window.PLAN_DATA JavaScript object via the Jinja
    filter `tojson` in templates/plan.html.

    is_favorite/source_url/instructions are included in addition to the
    fields actually needed for the shopping list/nutrition total - not
    needed for the calculations themselves, but shown by the read-only
    recipe detail popup on the plan page (see static/plan.js:
    openRecipeDetail), which builds directly from the
    weeklyPlanRecipes/weeklySideRecipes objects already present in the
    frontend instead of needing its own server round trip.

    Ingredient names are processed here via normalize_ingredient_name()
    (services/ingredient_aliases.py): first .strip().title() (leading/
    trailing whitespace removed, first letter of each word capitalized),
    so e.g. "  noodles" and "Noodles" are recognized as the same entry in
    the client-side consolidated shopping list (see
    static/plan-shopping.js: rebuildShoppingList), AND additionally
    replaced by a user-maintained alias mapping if one exists (e.g.
    "Spaghetti" -> "Noodles", "Olive oil" -> "Oil") - so different
    concrete ingredients that amount to the same thing for shopping are
    combined into one item. The recipe itself (add/edit form) still shows
    the originally entered name unchanged. Each ingredient's shopping-list
    category (see services/shopping.py) is passed through unchanged - it
    determines the group/order the ingredient is sorted into there.

    Amounts/units are converted here from the canonical storage form
    (always g/ml, see services/units.py) to the display unit chosen by
    the user (services/settings.py) - ALWAYS the same unit for the same
    family, regardless of recipe, which is why the purely client-side
    aggregation by "name+unit" in rebuildShoppingList() still correctly
    combines identically named ingredients across multiple recipes
    without its own conversion.

    plan_id determines whose ingredient aliasing/display units apply
    (services/ingredient_aliases.py: normalize_ingredient_name(),
    services/settings.py: get_display_units()) - for a recipe linked in
    via RecipePlanLink, ALWAYS those of the CURRENTLY ACTIVE plan, not its
    owner plan, so a user consistently sees their own settings on their
    own shopping list.
    """
    display_units = get_display_units(plan_id)
    return {
        "id": recipe.id,
        "name": recipe.name,
        "category_name": recipe.category.name,
        "category_id": recipe.category_id,
        "servings": recipe.servings,
        "calories": recipe.calories,
        "protein": recipe.protein,
        "carbs": recipe.carbs,
        "fat": recipe.fat,
        "is_favorite": recipe.is_favorite,
        "source_url": recipe.source_url,
        "instructions": recipe.instructions,
        "ingredients": [
            {
                "name": normalize_ingredient_name(plan_id, ing.name),
                **dict(zip(("amount", "unit"), convert_for_display(ing.amount, ing.unit, display_units))),
                "category": ing.category,
            }
            for ing in recipe.ingredients
        ]
    }


def jsonify_side(plan_day_side, plan_id):
    """Like jsonify_recipe(), but for a PlanDaySide row: additionally
    attaches side_id to the serialized recipe dict - the ID of the
    PlanDaySide row itself, NOT of the recipe. static/plan-sides.js needs
    this ID to specifically re-roll, manually replace, remove, or move
    this exact side-dish slot to another day, regardless of whether the
    same recipe might still be a side dish on another day. Also cooked -
    the ACTUAL CURRENT value of the PlanDaySide row (see models.py:
    PlanDaySide.cooked), not unconditionally False: reroll_one_side()/
    set_one_side() deliberately reset it before calling this (new dish =
    not yet cooked), while move_one_side() leaves it untouched (the same
    side dish just moves to another day)."""
    data = jsonify_recipe(plan_day_side.recipe, plan_id)
    data['side_id'] = plan_day_side.id
    data['cooked'] = plan_day_side.cooked
    return data
