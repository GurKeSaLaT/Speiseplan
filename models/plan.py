from models import db


class Plan(db.Model):
    """A household: its own calendar, shopping list, recipes, categories and
    settings. Access is purely via PlanMembership; owner_user_id is only
    informational and grants nothing extra."""
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    owner_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=db.func.now())

    owner = db.relationship('User', foreign_keys=[owner_user_id])


class PlanMembership(db.Model):
    """Full access for a user to a plan.

    is_starred (per user) marks the default plan; "only one starred" is
    enforced in the application, not the schema. show_in_week_overview (per
    user) shows this plan's dishes read-only in the user's other plans.
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
    """Invite for an email without a User yet; becomes a PlanMembership on
    that email's first login (services/plans.py: accept_pending_invites)."""
    id = db.Column(db.Integer, primary_key=True)
    plan_id = db.Column(db.Integer, db.ForeignKey('plan.id'), nullable=False, index=True)
    email = db.Column(db.String(255), nullable=False, index=True)
    invited_at = db.Column(db.DateTime, default=db.func.now())

    __table_args__ = (db.UniqueConstraint('plan_id', 'email', name='uq_pending_plan_invite_plan_id_email'),)

    plan = db.relationship('Plan')
