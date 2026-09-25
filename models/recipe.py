from models import db


class Category(db.Model):
    """Recipe category, per plan. Used to balance automatic week planning."""
    id = db.Column(db.Integer, primary_key=True)
    plan_id = db.Column(db.Integer, db.ForeignKey('plan.id'), nullable=False, index=True)
    name = db.Column(db.String(50), nullable=False)

    __table_args__ = (db.UniqueConstraint('plan_id', 'name', name='uq_category_plan_id_name'),)


class Recipe(db.Model):
    """A main or side dish (never mixed during automatic selection).

    Owned by one plan and optionally linked into others via RecipePlanLink
    (the same row, not a copy). Always query through
    services/recipe_visibility.py: visible_recipes_query(). category_id
    always points to a category of the owner plan.
    """
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    owner_plan_id = db.Column(db.Integer, db.ForeignKey('plan.id'), nullable=False, index=True)
    category_id = db.Column(db.Integer, db.ForeignKey('category.id'), nullable=False)
    is_side_dish = db.Column(db.Boolean, default=False, nullable=False)
    is_favorite = db.Column(db.Boolean, default=False, nullable=False)

    # The people the ingredient amounts are sized for; the shopping list
    # scales amounts from this to each day's servings.
    servings = db.Column(db.Integer, nullable=False, default=2)

    # Per serving. Computed from the ingredients on save unless
    # nutrition_override is set; calories always derive from protein/carbs/fat.
    calories = db.Column(db.Integer, default=0)
    protein = db.Column(db.Float, default=0.0)
    carbs = db.Column(db.Float, default=0.0)
    fat = db.Column(db.Float, default=0.0)
    nutrition_override = db.Column(db.Boolean, default=False, nullable=False)

    source_url = db.Column(db.String(500), nullable=True)
    instructions = db.Column(db.Text, nullable=True)

    # No onupdate: it wouldn't fire when a save changes no column value, so
    # edit_recipe() sets this explicitly on every save.
    updated_at = db.Column(db.DateTime, default=db.func.now())

    category = db.relationship('Category', backref=db.backref('recipes', lazy=True))
    owner_plan = db.relationship('Plan', foreign_keys=[owner_plan_id])
    ingredients = db.relationship('Ingredient', backref='recipe', cascade="all, delete-orphan")
    # No rows = available year-round. Only restricts automatic selection.
    seasons = db.relationship('RecipeSeason', backref='recipe', cascade="all, delete-orphan")
    plan_links = db.relationship('RecipePlanLink', backref='recipe', cascade="all, delete-orphan")


class RecipeSeason(db.Model):
    """An availability window as month/day without a year; end before start
    wraps around New Year (e.g. 12/1-2/28)."""
    id = db.Column(db.Integer, primary_key=True)
    recipe_id = db.Column(db.Integer, db.ForeignKey('recipe.id'), nullable=False)
    start_month = db.Column(db.Integer, nullable=False)
    start_day = db.Column(db.Integer, nullable=False)
    end_month = db.Column(db.Integer, nullable=False)
    end_day = db.Column(db.Integer, nullable=False)


class RecipePlanLink(db.Model):
    """Makes a recipe visible and editable in an additional plan. Linking to
    the owner plan itself is prevented by the route, not the database."""
    id = db.Column(db.Integer, primary_key=True)
    recipe_id = db.Column(db.Integer, db.ForeignKey('recipe.id'), nullable=False, index=True)
    plan_id = db.Column(db.Integer, db.ForeignKey('plan.id'), nullable=False, index=True)

    __table_args__ = (db.UniqueConstraint('recipe_id', 'plan_id', name='uq_recipe_plan_link_recipe_id_plan_id'),)

    plan = db.relationship('Plan')


class Ingredient(db.Model):
    """One ingredient line; amount is for Recipe.servings people and stored
    canonically (g/ml where convertible).

    category is one of services/shopping.py: SHOPPING_CATEGORIES (None =
    misc). is_pantry puts the line on the "check pantry" list instead of the
    shopping list - per line, since the same ingredient can be a staple in
    one recipe and a fresh purchase in another.
    """
    id = db.Column(db.Integer, primary_key=True)
    recipe_id = db.Column(db.Integer, db.ForeignKey('recipe.id'), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    unit = db.Column(db.String(20), nullable=False)
    category = db.Column(db.String(50), nullable=True)
    is_pantry = db.Column(db.Boolean, nullable=False, default=False)
