from models import db


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
    created (owner_user_id, see migrations.py: init_db()); via
    PlanMembership (below), further users can be added to a plan with full
    access (see routes/sharing.py: invite_member).

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
