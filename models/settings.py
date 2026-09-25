from models import db


class AppSettings(db.Model):
    """Per-plan display units (created lazily by services/settings.py).
    Stored amounts stay canonical g/ml either way."""
    id = db.Column(db.Integer, primary_key=True)
    plan_id = db.Column(db.Integer, db.ForeignKey('plan.id'), unique=True, nullable=False, index=True)
    mass_unit = db.Column(db.String(10), nullable=False, default='g')
    volume_unit = db.Column(db.String(10), nullable=False, default='ml')


class IngredientAlias(db.Model):
    """Per-plan mapping of an ingredient spelling to a shared name, so the
    shopping list merges e.g. "Spaghetti" and "Fusilli" into "Nudeln".
    Recipes keep showing their own spelling. raw_name is stored normalized
    (.strip().title())."""
    id = db.Column(db.Integer, primary_key=True)
    plan_id = db.Column(db.Integer, db.ForeignKey('plan.id'), nullable=False, index=True)
    raw_name = db.Column(db.String(100), nullable=False, index=True)
    canonical_name = db.Column(db.String(100), nullable=False)

    __table_args__ = (db.UniqueConstraint('plan_id', 'raw_name', name='uq_ingredient_alias_plan_id_raw_name'),)


class IngredientNutrition(db.Model):
    """Per-plan nutrition reference for a canonical ingredient, per 100 g,
    100 ml or 1 piece (services/nutrition.py: REFERENCE_BASES). No calories
    column: calories are computed from protein/carbs/fat."""
    id = db.Column(db.Integer, primary_key=True)
    plan_id = db.Column(db.Integer, db.ForeignKey('plan.id'), nullable=False, index=True)
    canonical_name = db.Column(db.String(100), nullable=False, index=True)
    reference_amount = db.Column(db.Float, nullable=False, default=100)
    reference_unit = db.Column(db.String(20), nullable=False, default='g')
    protein = db.Column(db.Float, default=0.0)
    carbs = db.Column(db.Float, default=0.0)
    fat = db.Column(db.Float, default=0.0)

    __table_args__ = (db.UniqueConstraint('plan_id', 'canonical_name', name='uq_ingredient_nutrition_plan_id_canonical_name'),)
