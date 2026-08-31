from models import db


class Category(db.Model):
    """A recipe category (e.g. "Meat", "Vegetarian", "Pasta").

    Categories are used during automatic weekly-plan generation to spread
    the selection as evenly as possible across the week (see
    services/planning.py: assign_balanced_categories). A category can only
    be deleted once no recipes are assigned to it anymore (see
    routes/categories.py: delete_category).

    plan_id ties the category to ONE plan (see Plan/PlanMembership in
    models/plan.py) - each plan maintains its own category list, just like
    the other "settings" (AppSettings/IngredientAlias/IngredientNutrition).
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
    # routes/recipes/crud.py: add_recipe()/edit_recipe()) - the sum of the
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
    # routes/recipes/crud.py: add_recipe()). DELIBERATELY no onupdate=...:
    # that would only trigger if at least one COLUMN VALUE actually
    # changes (SQLAlchemy doesn't mark an assignment to the same value as
    # "dirty") - if a user saves a recipe again unchanged (e.g. only
    # touched the ingredient list, left all other fields identical), the
    # timestamp would otherwise NOT be updated. edit_recipe() therefore
    # sets this field explicitly on every save.
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
    route (see routes/recipes/links.py: link_recipe_to_plan), which
    already has to look up current_plan()/memberships for that anyway.
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
