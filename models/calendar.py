from models import db


class PlanDay(db.Model):
    """One calendar day of a plan. A week without any PlanDay rows was never
    created; once created, all 7 days get a row.

    One optional main dish, any number of side dishes (PlanDaySide).
    excluded only affects the main dish.
    """
    id = db.Column(db.Integer, primary_key=True)
    plan_id = db.Column(db.Integer, db.ForeignKey('plan.id'), nullable=False, index=True)
    date = db.Column(db.Date, nullable=False, index=True)
    excluded = db.Column(db.Boolean, default=False, nullable=False)
    servings = db.Column(db.Integer, nullable=False, default=2)
    main_recipe_id = db.Column(db.Integer, db.ForeignKey('recipe.id'), nullable=True)

    __table_args__ = (db.UniqueConstraint('plan_id', 'date', name='uq_plan_day_plan_id_date'),)

    # Refers to the current assignment: reset when the dish is replaced,
    # carried along when days are swapped.
    cooked = db.Column(db.Boolean, default=False, nullable=False)

    main_recipe = db.relationship('Recipe', foreign_keys=[main_recipe_id])
    sides = db.relationship('PlanDaySide', cascade="all, delete-orphan", order_by='PlanDaySide.id')


class PlanDaySide(db.Model):
    """A side dish on a day. No unique (plan_day_id, recipe_id): avoiding
    duplicates in a week is an application rule, not a constraint."""
    id = db.Column(db.Integer, primary_key=True)
    plan_day_id = db.Column(db.Integer, db.ForeignKey('plan_day.id'), nullable=False)
    recipe_id = db.Column(db.Integer, db.ForeignKey('recipe.id'), nullable=False)

    # Reset when the side is replaced, kept when it's moved to another day.
    cooked = db.Column(db.Boolean, default=False, nullable=False)

    recipe = db.relationship('Recipe')


class ExtraShoppingItem(db.Model):
    """A manually added shopping-list item for one week (week_start = that
    week's Friday; there is no Week model). Not scaled by servings."""
    id = db.Column(db.Integer, primary_key=True)
    plan_id = db.Column(db.Integer, db.ForeignKey('plan.id'), nullable=False, index=True)
    week_start = db.Column(db.Date, nullable=False, index=True)
    name = db.Column(db.String(100), nullable=False)
    amount = db.Column(db.Float, nullable=True)
    unit = db.Column(db.String(20), nullable=True)
    category = db.Column(db.String(50), nullable=True)
