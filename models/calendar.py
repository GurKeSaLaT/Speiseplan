from models import db


class CoupledDish:
    """A dish that can be coupled to its source dish (a Kopplung, CONTEXT.md):
    the main dish of a PlanDay or a PlanDaySide. The source dish is the main
    dish of source_day_id or the side source_side_id, at most one of them
    set; None/None means not coupled (services/follow_ups.py).

    Plain ids without a foreign key: plan_day and plan_day_side would
    reference each other, and SQLite doesn't enforce them here anyway."""
    source_day_id = db.Column(db.Integer, nullable=True)
    source_side_id = db.Column(db.Integer, nullable=True)

    @property
    def is_coupled(self):
        return self.source_day_id is not None or self.source_side_id is not None


class PlanDay(CoupledDish, db.Model):
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

    # source_day_id/source_side_id (CoupledDish) belong to the main dish:
    # cleared when it is replaced, carried along when days are swapped.

    main_recipe = db.relationship('Recipe', foreign_keys=[main_recipe_id])
    sides = db.relationship(
        'PlanDaySide', cascade="all, delete-orphan", order_by='PlanDaySide.id',
        foreign_keys='PlanDaySide.plan_day_id', back_populates='day',
    )


class PlanDaySide(CoupledDish, db.Model):
    """A side dish on a day. No unique (plan_day_id, recipe_id): avoiding
    duplicates in a week is an application rule, not a constraint.
    Its coupling (CoupledDish) stays when the side is moved to another day."""
    id = db.Column(db.Integer, primary_key=True)
    plan_day_id = db.Column(db.Integer, db.ForeignKey('plan_day.id'), nullable=False)
    recipe_id = db.Column(db.Integer, db.ForeignKey('recipe.id'), nullable=False)

    # Reset when the side is replaced, kept when it's moved to another day.
    cooked = db.Column(db.Boolean, default=False, nullable=False)

    recipe = db.relationship('Recipe')
    day = db.relationship('PlanDay', foreign_keys=[plan_day_id], back_populates='sides')


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


class ShoppingListCheck(db.Model):
    """A ticked-off shopping-list line for one week (week_start = that week's
    Friday). The list itself is built client-side, so a line is identified by
    plan-shopping.js's item key ("item:<name>|||<unit>" or "extra:<id>"),
    not by a row id.

    amount is how much was ticked off (in the display unit of the key), so
    plan changes keep what was already bought: more needed -> the rest shows
    up as an open line, less or nothing needed -> the line stays ticked.
    None means "the whole line, whatever its amount". category is a
    snapshot for lines no recipe needs anymore."""
    id = db.Column(db.Integer, primary_key=True)
    plan_id = db.Column(db.Integer, db.ForeignKey('plan.id'), nullable=False, index=True)
    week_start = db.Column(db.Date, nullable=False, index=True)
    item_key = db.Column(db.String(255), nullable=False)
    amount = db.Column(db.Float, nullable=True)
    category = db.Column(db.String(50), nullable=True)

    __table_args__ = (
        db.UniqueConstraint('plan_id', 'week_start', 'item_key', name='uq_shopping_list_check_plan_week_key'),
    )


class WeekLeftover(db.Model):
    """Something left over from the previous week, entered when (re)creating
    a week or later on the plan page (week_start = that week's Friday).

    Week generation prefers recipes that use it up, and the client-side
    shopping list subtracts it from the matching line. name is the
    canonical ingredient name (aliases resolved), amount/unit are stored
    canonically like Ingredient (g/ml where convertible). No amount means
    "enough for whatever the week needs": the whole line is dropped."""
    id = db.Column(db.Integer, primary_key=True)
    plan_id = db.Column(db.Integer, db.ForeignKey('plan.id'), nullable=False, index=True)
    week_start = db.Column(db.Date, nullable=False, index=True)
    name = db.Column(db.String(100), nullable=False)
    amount = db.Column(db.Float, nullable=True)
    unit = db.Column(db.String(20), nullable=True)



class PendingFollowUp(CoupledDish, db.Model):
    """A follow-up dish for a day whose week doesn't exist yet, coupled to its
    source dish (CoupledDish). Creating that week offers it as a fixed dish
    (and couples it); servings is what the source dish is bought for until
    then (PlanDay's default). is_side: it will be planned as a side dish
    rather than as the day's main dish. No unique date: a day can wait for
    a main dish and any number of sides (at most one main dish is an
    application rule, services/follow_ups.py: live_slot_free)."""
    id = db.Column(db.Integer, primary_key=True)
    plan_id = db.Column(db.Integer, db.ForeignKey('plan.id'), nullable=False, index=True)
    date = db.Column(db.Date, nullable=False, index=True)
    recipe_id = db.Column(db.Integer, db.ForeignKey('recipe.id'), nullable=False)
    is_side = db.Column(db.Boolean, default=False, nullable=False)
    servings = db.Column(db.Integer, nullable=False, default=2)

    recipe = db.relationship('Recipe')
