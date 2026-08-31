from models import db


class AppSettings(db.Model):
    """Display settings for ONE plan - currently only the preferred units
    for mass (g/kg) and volume (ml/l) in which ingredient amounts should be
    displayed (see services/units.py: convert_for_display,
    routes/settings.py). One row PER plan (plan_id unique) instead of a
    single global singleton row like before - services/settings.py:
    get_settings(plan_id) creates it lazily with these defaults when
    needed, no dedicated migration step needed for NEW plans (only for
    already-existing legacy data, see migrations.py: init_db()). Does NOT
    change the values stored canonically in Ingredient.amount/.unit
    (always grams/milliliters), only how they're converted when
    displayed."""
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
