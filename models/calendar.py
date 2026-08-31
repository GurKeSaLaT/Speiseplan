from models import db


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
    # Which plan (see models/plan.py: Plan/PlanMembership) this calendar
    # day belongs to - each plan has its own, independent calendar. The
    # former unique=True directly on date (a day could have at most ONE
    # row in the ENTIRE app) has therefore given way to a composite unique
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
