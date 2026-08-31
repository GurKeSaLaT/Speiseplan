"""SQLAlchemy data models for the Speiseplan app.

Seven tables with the following relationships:

    Category 1---n Recipe 1---n Ingredient
                      |  1
                      |  n
                RecipeSeason

    Recipe 1---n PlanDay (as main_recipe)
    Recipe 1---n PlanDaySide n---1 PlanDay

    ExtraShoppingItem (standalone, only loosely tied to a calendar week via
                        week_start - no foreign key)

Recipes (Recipe) are the central entity: they belong to exactly one
category, carry their own ingredients, and optionally several availability
windows (RecipeSeason). The weekly-plan calendar (PlanDay) references at
most one main dish per calendar day, but via PlanDaySide ANY NUMBER of
extra dishes (side dishes) - unlike the main dish (a single foreign-key
column main_recipe_id directly on PlanDay), this is therefore its own
1:n table instead of a single column. ExtraShoppingItem supplements the
shopping list derived from recipe ingredients with manually added items
(e.g. toiletries) that don't belong to any recipe.
"""

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class Category(db.Model):
    """A recipe category (e.g. "Meat", "Vegetarian", "Pasta").

    Categories are used during automatic weekly-plan generation to spread
    the selection as evenly as possible across the week (see
    services/planning.py: assign_balanced_categories). A category can only
    be deleted once no recipes are assigned to it anymore (see
    routes/categories.py: delete_category).

    plan_id ties the category to ONE plan (see Plan/PlanMembership further
    below) - each plan maintains its own category list, just like the
    other "settings" (AppSettings/IngredientAlias/IngredientNutrition).
    name is therefore only unique WITHIN a plan (see __table_args__), no
    longer globally.
    """
    id = db.Column(db.Integer, primary_key=True)
    plan_id = db.Column(db.Integer, db.ForeignKey('plan.id'), nullable=False, index=True)
    name = db.Column(db.String(50), nullable=False)

    __table_args__ = (db.UniqueConstraint('plan_id', 'name', name='uq_category_plan_id_name'),)


class Recipe(db.Model):
    """A dish: either a main dish or a side dish, with nutritional
    information, an arbitrary ingredient list, and optional season
    restrictions.

    is_side_dish distinguishes two completely separate selection pools:
    during automatic weekly planning, main dishes (is_side_dish=False) and
    side dishes (is_side_dish=True) are never mixed together (see
    services/planning.py: choose_recipe).

    owner_plan_id is the plan under which the recipe was originally
    created ("tied to its own plan") - RecipePlanLink (see below)
    supplements that with any number of ADDITIONAL plans in which the same
    recipe is also visible/usable (a real link, not a copy: a change to
    the name/ingredients/instructions takes effect everywhere the recipe
    is embedded). services/planning.py: visible_recipes_query() is the
    single place that actually resolves "recipes usable for plan X"
    (owner_plan_id == X OR a RecipePlanLink pointing at X) - all routes
    query through it instead of Recipe.query directly, so this rule isn't
    duplicated in multiple places. category_id here ALWAYS points to a
    category of the OWNER plan (owner_plan_id) - when the recipe is
    embedded into another plan, it carries its category over unchanged,
    regardless of the target plan's category list.
    """
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    owner_plan_id = db.Column(db.Integer, db.ForeignKey('plan.id'), nullable=False, index=True)
    category_id = db.Column(db.Integer, db.ForeignKey('category.id'), nullable=False)
    is_side_dish = db.Column(db.Boolean, default=False, nullable=False)

    # Favorites are weighted higher in automatic selection (FAVORITE_WEIGHT
    # in services/planning.py), but don't block anything - just a soft
    # bonus, not an exclusion criterion for other recipes.
    is_favorite = db.Column(db.Boolean, default=False, nullable=False)

    # How many people the ingredient amounts maintained below are sized
    # for. The nutrition values (calories/protein/carbs/fat) are unaffected
    # by this, since they always apply PER SERVING - only the ingredient
    # amounts for the shopping list are scaled up or down in the frontend
    # based on the ratio between the desired number of people and this
    # value (see static/plan.js: rebuildShoppingList).
    servings = db.Column(db.Integer, nullable=False, default=2)

    # Nutrition values, each per serving (not for the whole recipe/all
    # servings combined). All four fields are optional and default to 0.
    #
    # By default these are NO LONGER maintained by hand, but computed
    # automatically from the ingredients on save (see
    # services/nutrition.py: compute_recipe_nutrition(), called from
    # routes/recipes.py: add_recipe()/edit_recipe()) - the sum of the
    # ingredient nutrition values (services/nutrition.py:
    # IngredientNutrition) is divided by servings, since Ingredient.amount
    # applies to the WHOLE serving count, but these fields here are PER
    # serving. They remain directly writable columns nonetheless (not
    # purely computed/not stored): nutrition_override=True still allows a
    # manually entered value for protein/carbs/fat that is never
    # automatically overwritten - e.g. when only the nutrition info printed
    # on the packaging of a ready-made product is known, not that of its
    # individual ingredients. calories itself is NEVER entered directly,
    # even in the override case - it always results from protein/carbs/fat
    # (services/nutrition.py: compute_calories(), the Atwater rule of thumb
    # of 4/4/9 kcal per g), so as to not make the figure redundant and
    # potentially contradictory.
    calories = db.Column(db.Integer, default=0)
    protein = db.Column(db.Float, default=0.0)
    carbs = db.Column(db.Float, default=0.0)
    fat = db.Column(db.Float, default=0.0)
    nutrition_override = db.Column(db.Boolean, default=False, nullable=False)

    # Source link (e.g. the chefkoch.de page it was imported from, or a
    # manually entered link to a recipe elsewhere) and the preparation
    # instructions as free text. Both optional and usable independently of
    # the import - even a completely manually created recipe may have a
    # link/instructions. See services/recipe_import.py for the automatic
    # import from chefkoch.de, which fills in both fields.
    source_url = db.Column(db.String(500), nullable=True)
    instructions = db.Column(db.Text, nullable=True)

    # For the "recently edited" list on the management overview page
    # (routes/manage.py) - default sets the timestamp on creation (see
    # routes/recipes.py: add_recipe()). DELIBERATELY no onupdate=...: that
    # would only trigger if at least one COLUMN VALUE actually changes
    # (SQLAlchemy doesn't mark an assignment to the same value as "dirty")
    # - if a user saves a recipe again unchanged (e.g. only touched the
    # ingredient list, left all other fields identical), the timestamp
    # would otherwise NOT be updated. edit_recipe() therefore sets this
    # field explicitly on every save.
    updated_at = db.Column(db.DateTime, default=db.func.now())

    category = db.relationship('Category', backref=db.backref('recipes', lazy=True))
    owner_plan = db.relationship('Plan', foreign_keys=[owner_plan_id])
    # cascade="all, delete-orphan": ingredients are automatically deleted
    # along with the recipe - there are no "orphaned" ingredients.
    ingredients = db.relationship('Ingredient', backref='recipe', cascade="all, delete-orphan")

    # No entries = available year-round (the default case for most
    # recipes). With one or more entries, the recipe is only "available"
    # (see services/seasons.py: recipe_available_now) if today's date
    # (month/day, year-independent) falls within at least one of the
    # stored windows. This only restricts AUTOMATIC selection, never
    # manual selection via search.
    seasons = db.relationship('RecipeSeason', backref='recipe', cascade="all, delete-orphan")

    # cascade="all, delete-orphan": links to further plans automatically
    # disappear along with it as soon as the recipe itself is deleted.
    plan_links = db.relationship('RecipePlanLink', backref='recipe', cascade="all, delete-orphan")


class RecipeSeason(db.Model):
    """A single availability window of a recipe, as month/day without a
    year (e.g. "6/1 to 8/31" for summer).

    A recipe can have several of these at once: both several checked
    standard seasons (spring/summer/autumn/winter, whose fixed month/day
    boundaries are stored in services/seasons.py as SEASON_PRESETS) and a
    self-defined window. A window whose end lies before its start (e.g.
    winter: 12/1 to 2/28) runs across the turn of the year - evaluating
    these windows is handled by services/seasons.py: date_in_range.
    """
    id = db.Column(db.Integer, primary_key=True)
    recipe_id = db.Column(db.Integer, db.ForeignKey('recipe.id'), nullable=False)
    start_month = db.Column(db.Integer, nullable=False)
    start_day = db.Column(db.Integer, nullable=False)
    end_month = db.Column(db.Integer, nullable=False)
    end_day = db.Column(db.Integer, nullable=False)


class RecipePlanLink(db.Model):
    """Ties a recipe ADDITIONALLY to another plan, beyond its actual owner
    plan (Recipe.owner_plan_id) - "add dish to another plan" creates
    exactly one such row.

    This is a REAL link, not a copy: the same Recipe row (including all
    its Ingredient/RecipeSeason rows) becomes visible and fully editable
    for the linked plan - a change takes effect for ALL plans the recipe
    is embedded in. See services/planning.py: visible_recipes_query() for
    the single place that evaluates this visibility rule.

    No unique constraint against the OWNER plan itself (Recipe.
    owner_plan_id) at the database level - that's instead prevented by the
    route (see routes/recipes.py: link_recipe_to_plan), which already has
    to look up current_plan()/memberships for that anyway.
    """
    id = db.Column(db.Integer, primary_key=True)
    recipe_id = db.Column(db.Integer, db.ForeignKey('recipe.id'), nullable=False, index=True)
    plan_id = db.Column(db.Integer, db.ForeignKey('plan.id'), nullable=False, index=True)

    __table_args__ = (db.UniqueConstraint('recipe_id', 'plan_id', name='uq_recipe_plan_link_recipe_id_plan_id'),)

    plan = db.relationship('Plan')


class Ingredient(db.Model):
    """A single ingredient of a recipe with amount and unit.

    amount/unit are deliberately free-form values (no controlled
    vocabulary): unit is free text (e.g. "g", "pc", "tbsp"), amount
    applies to the number of people set on Recipe.servings. When
    assembling the shopping list, amount is scaled client-side to the
    number of people set per weekday (see static/plan.js).

    category is optional and one of the fixed values from
    services/shopping.py: SHOPPING_CATEGORIES (no dedicated foreign key,
    since the list is deliberately small/fixed) - determines which
    supermarket section this ingredient is sorted into on the shopping
    list. None (e.g. for ingredients from before this field was
    introduced) ends up in the catch-all "misc" group there.
    """
    id = db.Column(db.Integer, primary_key=True)
    recipe_id = db.Column(db.Integer, db.ForeignKey('recipe.id'), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    unit = db.Column(db.String(20), nullable=False)
    category = db.Column(db.String(50), nullable=True)


class PlanDay(db.Model):
    """The persistent weekly-plan calendar: one record per actual calendar
    day for which a plan was ever created or edited.

    Unlike in earlier versions of the app, the weekly plan is no longer
    rendered server-side just once and then only held in the browser (a
    page reload would have discarded everything) - every change (rerolling,
    swapping, adding a side dish, changing the number of people) writes
    immediately into this table (see routes/plan/).

    A day without a PlanDay row means "no plan has ever been created for
    this week" - in that case the week view shows the "Create new weekly
    plan" button instead of day cards (has_any_data in
    routes/plan/pages.py: week_view). Once a week has been created, all 7
    days get a row, even if main_recipe_id stays empty and not a single
    PlanDaySide exists (e.g. for an excluded day with no side dishes).

    main_recipe_id is an optional foreign key for EXACTLY ONE main dish;
    the (arbitrarily many) side dishes, by contrast, hang off this row via
    the separate PlanDaySide table (see below). So a day can only have one
    main dish, but zero to N side dishes, independent of that - excluded
    only excludes the main dish from automatic planning, never the side
    dishes.
    """
    id = db.Column(db.Integer, primary_key=True)
    # Which plan (see Plan/PlanMembership below) this calendar day belongs
    # to - each plan has its own, independent calendar. The former
    # unique=True directly on date (a day could have at most ONE row in
    # the ENTIRE app) has therefore given way to a composite unique
    # (plan_id, date) (see __table_args__ below): two different plans are
    # allowed to each have their own row for the same calendar day.
    plan_id = db.Column(db.Integer, db.ForeignKey('plan.id'), nullable=False, index=True)
    # index=True (instead of additionally unique=True, which now runs via
    # __table_args__): the week view regularly queries date ranges
    # (date.in_(...)).
    date = db.Column(db.Date, nullable=False, index=True)
    excluded = db.Column(db.Boolean, default=False, nullable=False)
    servings = db.Column(db.Integer, nullable=False, default=2)
    main_recipe_id = db.Column(db.Integer, db.ForeignKey('recipe.id'), nullable=True)

    __table_args__ = (db.UniqueConstraint('plan_id', 'date', name='uq_plan_day_plan_id_date'),)

    # Whether the main dish for THIS day has already been cooked (checkbox
    # in the recipe detail window, see static/plan.js: openRecipeDetail/
    # toggleCooked) - controls the "greying out" of the day card in the
    # weekly plan. Deliberately refers to the CURRENT assignment, not the
    # recipe itself: if the main dish is rerolled/manually replaced,
    # routes/plan/day_actions.py: reroll_day()/set_main_day() automatically
    # reset this field back to False, since it's then a different, not
    # yet cooked dish. With swap_days(), by contrast, the value travels
    # WITH the main dish to the respective other day.
    cooked = db.Column(db.Boolean, default=False, nullable=False)

    main_recipe = db.relationship('Recipe', foreign_keys=[main_recipe_id])
    # cascade="all, delete-orphan": if a PlanDay is deleted (doesn't happen
    # in the current app, but as a safeguard), its side-dish rows
    # disappear along with it instead of being left behind as orphaned
    # data. order_by ensures a stable, chronological order when
    # displaying (the most recently added side dish appears last).
    sides = db.relationship('PlanDaySide', cascade="all, delete-orphan", order_by='PlanDaySide.id')


class PlanDaySide(db.Model):
    """A single side dish assigned to a calendar day. A PlanDay can have any
    number of these (see PlanDay.sides) - unlike the main dish (a single
    column directly on PlanDay), this here is deliberately its own 1:n
    table, so that the number of side dishes per day isn't capped at a
    fixed value.

    No unique constraint on (plan_day_id, recipe_id): the server does
    consistently prevent assigning the same side dish twice in the same
    week (see services/planning.py:
    week_side_recipe_ids/choose_recipe), but that's a soft,
    application-side rule and not a database integrity constraint.
    """
    id = db.Column(db.Integer, primary_key=True)
    plan_day_id = db.Column(db.Integer, db.ForeignKey('plan_day.id'), nullable=False)
    recipe_id = db.Column(db.Integer, db.ForeignKey('recipe.id'), nullable=False)

    # Like PlanDay.cooked above, just for this one side dish instead of the
    # day's main dish - routes/plan/day_actions.py: reroll_one_side()/
    # set_one_side() reset it back to False when replacing the side dish,
    # while move_one_side() (just moving it to another day, the same row
    # remains) leaves it untouched.
    cooked = db.Column(db.Boolean, default=False, nullable=False)

    recipe = db.relationship('Recipe')


class ExtraShoppingItem(db.Model):
    """An item manually added to a week's shopping list that doesn't belong
    to any recipe (e.g. toiletries or drinks that aren't entered as an
    ingredient of any dish).

    week_start is deliberately JUST a date (the Monday of the calendar week
    in question, like start_date everywhere else in the project) instead of
    a foreign key to PlanDay/a dedicated "Week" table - there is no
    dedicated week model, weeks only exist implicitly via the 7 PlanDay
    rows that belong together. amount/unit are, like with Ingredient,
    optional and free-form, but (unlike ingredients from recipes) are NOT
    scaled with a weekday's number of people, since they aren't tied to a
    specific day or a specific recipe.

    plan_id assigns the item (like PlanDay.plan_id) to a specific plan -
    the same calendar week can have its own manual items in two different
    plans.
    """
    id = db.Column(db.Integer, primary_key=True)
    plan_id = db.Column(db.Integer, db.ForeignKey('plan.id'), nullable=False, index=True)
    week_start = db.Column(db.Date, nullable=False, index=True)
    name = db.Column(db.String(100), nullable=False)
    amount = db.Column(db.Float, nullable=True)
    unit = db.Column(db.String(20), nullable=True)
    category = db.Column(db.String(50), nullable=True)


class AppSettings(db.Model):
    """Display settings for ONE plan - currently only the preferred units
    for mass (g/kg) and volume (ml/l) in which ingredient amounts should be
    displayed (see services/units.py: convert_for_display,
    routes/settings.py). One row PER plan (plan_id unique) instead of a
    single global singleton row like before - services/settings.py:
    get_settings(plan_id) creates it lazily with these defaults when
    needed, no dedicated migration step needed for NEW plans (only for
    already-existing legacy data, see app.py: init_db()). Does NOT change
    the values stored canonically in Ingredient.amount/.unit (always grams/
    milliliters), only how they're converted when displayed."""
    id = db.Column(db.Integer, primary_key=True)
    plan_id = db.Column(db.Integer, db.ForeignKey('plan.id'), unique=True, nullable=False, index=True)
    mass_unit = db.Column(db.String(10), nullable=False, default='g')
    volume_unit = db.Column(db.String(10), nullable=False, default='ml')


class IngredientAlias(db.Model):
    """Maps a specific ingredient name (e.g. "spaghetti", "olive oil") to a
    parent, shared name (e.g. "pasta", "oil") - for the shopping list,
    which would otherwise list "spaghetti" and "fusilli" as two separate
    items even though what you usually buy for that is simply "pasta". See
    services/ingredient_aliases.py: normalize_ingredient_name() and
    routes/settings.py: the management page where users can maintain this
    mapping themselves.

    Does NOT change the name stored in Ingredient.name/shown in the
    recipe - a recipe still shows "spaghetti" in its own ingredient list.
    Only when building the shopping list (see services/planning.py:
    jsonify_recipe) is raw_name replaced by canonical_name, so that items
    can be meaningfully consolidated across multiple recipes. An
    ingredient name with no entry here simply stays itself (no alias = no
    grouping needed).

    raw_name is already stored in the form that jsonify_recipe() looks up
    (.strip().title(), see there) - capitalization and whitespace
    therefore don't matter when mapping. plan_id ties the mapping to ONE
    plan (each plan maintains its own equivalences), so raw_name is
    therefore only unique WITHIN a plan.
    """
    id = db.Column(db.Integer, primary_key=True)
    plan_id = db.Column(db.Integer, db.ForeignKey('plan.id'), nullable=False, index=True)
    raw_name = db.Column(db.String(100), nullable=False, index=True)
    canonical_name = db.Column(db.String(100), nullable=False)

    __table_args__ = (db.UniqueConstraint('plan_id', 'raw_name', name='uq_ingredient_alias_plan_id_raw_name'),)


class IngredientNutrition(db.Model):
    """Nutrition reference for a canonical ingredient (the same name that
    IngredientAlias/normalize_ingredient_name() also produces - so for an
    alias-grouped ingredient like "pasta", ONE shared entry instead of one
    per spelling like "spaghetti"/"fusilli"). See services/nutrition.py:
    compute_recipe_nutrition() uses this to automatically compute the
    recipe's nutrition values (Recipe.calories/.protein/.carbs/.fat) from
    the entered ingredients instead of them having to be maintained by
    hand (see Recipe.nutrition_override for the opt-out).

    Values apply per reference_amount/reference_unit (e.g. 100/"g" or
    1/"pc") - both deliberately free-form instead of fixed to "per 100g",
    since not every ingredient is sensibly measured in grams/milliliters
    (e.g. eggs are typically measured in "pc"). An ingredient name with no
    entry here, OR with a unit that differs from the actual Ingredient row
    of a recipe (e.g. reference stored in "g" but used in this recipe in
    "pc"), simply contributes 0 when computing - not an error, just an
    incomplete entry that can be filled in at any time.

    Deliberately NO dedicated calories column: calories can be computed
    from protein/carbs/fat (4 kcal/g for protein and carbs, 9 kcal/g for
    fat - the Atwater rule of thumb) and would only be a redundant,
    potentially contradictory figure if maintained separately. See
    services/nutrition.py: compute_calories().

    plan_id ties the entry to ONE plan (each plan maintains its own
    nutrition references), so canonical_name is therefore only unique
    WITHIN a plan."""
    id = db.Column(db.Integer, primary_key=True)
    plan_id = db.Column(db.Integer, db.ForeignKey('plan.id'), nullable=False, index=True)
    canonical_name = db.Column(db.String(100), nullable=False, index=True)
    reference_amount = db.Column(db.Float, nullable=False, default=100)
    reference_unit = db.Column(db.String(20), nullable=False, default='g')
    protein = db.Column(db.Float, default=0.0)
    carbs = db.Column(db.Float, default=0.0)
    fat = db.Column(db.Float, default=0.0)

    __table_args__ = (db.UniqueConstraint('plan_id', 'canonical_name', name='uq_ingredient_nutrition_plan_id_canonical_name'),)


class User(db.Model):
    """A user account - see services/auth.py for login/session handling.

    password_hash NEVER stores the plaintext password, but a hash produced
    via werkzeug.security.generate_password_hash() (PBKDF2 with salt) -
    services/auth.py: check_password() compares against it on login via
    werkzeug.security.check_password_hash(), without ever being able to
    reconstruct the password itself.

    Login happens via email (always stored lowercased, see
    routes/auth.py: login()/register()) - name is a pure display name
    WITHOUT uniqueness, so two users are allowed to have the same name.
    Registration runs via routes/auth.py: register() (button on the login
    page); at app start, app.py: init_db() additionally still seeds two
    generic demo accounts ("Nutzer1"/"Nutzer2") (placeholder emails
    following the pattern <name>@example.com, see there).

    language is the ISO 639-1 code Flask-Babel uses to pick this user's
    translation catalog (see app.py: get_locale()) - defaults to 'en'
    (English is the app's default language). Changeable on /manage/account
    (see services/accounts.py: update_profile())."""
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    language = db.Column(db.String(5), nullable=False, default='en')
    created_at = db.Column(db.DateTime, default=db.func.now())


class Plan(db.Model):
    """A standalone weekly-plan "household": an independent collection of
    PlanDay rows (see there: PlanDay.plan_id) along with a shopping list
    (ExtraShoppingItem.plan_id) AND its own cookbook/its own settings
    (Recipe.owner_plan_id, Category.plan_id, AppSettings.plan_id,
    IngredientAlias.plan_id, IngredientNutrition.plan_id) - each plan
    manages its recipes, categories, ingredient equivalences, nutrition
    references and display units completely independently of other plans.
    A recipe can additionally be embedded into ANOTHER plan via
    RecipePlanLink (see there) - a real link, not a separate cookbook per
    plan in the sense of separate copies.

    Every user automatically gets exactly one plan of their own when
    created (owner_user_id, see app.py: init_db()); via PlanMembership
    (below), further users can be added to a plan with full access (see
    routes/sharing.py: invite_member).

    owner_user_id is purely informational (shown e.g. on the sharing page,
    who originally created the plan) - actual access control is based
    solely on whether a PlanMembership row exists for the respective user
    (even the owner themselves gets a perfectly normal membership on
    creation, just additionally starred, see below) - so no user has any
    additional rights via owner_user_id alone that an invited member
    wouldn't also have.
    """
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    owner_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=db.func.now())

    owner = db.relationship('User', foreign_keys=[owner_user_id])


class PlanMembership(db.Model):
    """Links a user to a plan they have access to (full read/write access
    for all members, no distinction between owner and invited member - see
    Plan.owner_user_id above).

    is_starred marks, PER USER (not globally), the one plan that opens
    automatically after login and appears at the top of the navigation
    (see services/auth.py: current_plan()). That truly only ONE membership
    of the same user is ever starred at a time is not enforced via a
    database constraint (SQLite has no "at most one true per user_id"
    constraint without workarounds), but at the application level:
    routes/sharing.py: star_plan() unstars all other memberships of the
    same user in the SAME transaction before setting the new one.

    show_in_week_overview controls, likewise PER USER (not globally),
    whether this plan shows up in the WEEK-PLAN DAY TILES OF OTHER plans
    belonging to the same user as an additional, read-only entry (see
    routes/plan/pages.py: week_view() - "otherPlanMeals"). Does NOT affect
    the view of the plan itself (which, when it's the active plan, always
    stays visible normally) - only whether it additionally flows into the
    tiles of the user's other plans for a SHARED plan, for THIS one user.
    Default True (new memberships flow in automatically), togglable via
    the checkbox on /manage/sharing.
    """
    id = db.Column(db.Integer, primary_key=True)
    plan_id = db.Column(db.Integer, db.ForeignKey('plan.id'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    is_starred = db.Column(db.Boolean, default=False, nullable=False)
    show_in_week_overview = db.Column(db.Boolean, default=True, nullable=False)

    __table_args__ = (db.UniqueConstraint('plan_id', 'user_id', name='uq_plan_membership_plan_id_user_id'),)

    plan = db.relationship('Plan')
    user = db.relationship('User')


class PendingPlanInvite(db.Model):
    """A plan invite sent by email to an address that is NOT YET
    registered (see routes/sharing.py: invite_member() - for an email
    that already exists, a real PlanMembership is created immediately
    instead, no row here).

    If someone later registers with exactly this email (lowercased, see
    routes/auth.py: register()), the invite is automatically converted
    into a real PlanMembership and this row is deleted in the process
    (services/plans.py: accept_pending_invites()) - until then it stays
    here as a visible "pending" entry on /manage/sharing (including a
    re-fetchable invite link, since real email sending isn't wired up
    yet, see services/mail.py)."""
    id = db.Column(db.Integer, primary_key=True)
    plan_id = db.Column(db.Integer, db.ForeignKey('plan.id'), nullable=False, index=True)
    email = db.Column(db.String(255), nullable=False, index=True)
    invited_at = db.Column(db.DateTime, default=db.func.now())

    __table_args__ = (db.UniqueConstraint('plan_id', 'email', name='uq_pending_plan_invite_plan_id_email'),)

    plan = db.relationship('Plan')
