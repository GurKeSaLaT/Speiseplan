from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class Category(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)


class Recipe(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey('category.id'), nullable=False)
    is_side_dish = db.Column(db.Boolean, default=False, nullable=False)
    # Favoriten werden bei der automatischen Auswahl höher gewichtet (siehe
    # FAVORITE_WEIGHT in app.py), blockieren aber nichts - nur ein weicher Bonus.
    is_favorite = db.Column(db.Boolean, default=False, nullable=False)
    # Für wie viele Personen die eingetragenen Zutatenmengen ausgelegt sind.
    # Nährwerte bleiben davon unberührt (die sind pro Portion/Person), nur die
    # Zutatenmengen für die Einkaufsliste werden anhand dessen hoch-/runtergerechnet.
    servings = db.Column(db.Integer, nullable=False, default=2)

    # Nährwerte
    calories = db.Column(db.Integer, default=0)
    protein = db.Column(db.Float, default=0.0)
    carbs = db.Column(db.Float, default=0.0)
    fat = db.Column(db.Float, default=0.0)

    category = db.relationship('Category', backref=db.backref('recipes', lazy=True))
    ingredients = db.relationship('Ingredient', backref='recipe', cascade="all, delete-orphan")
    # Keine Einträge = ganzjährig verfügbar. Mit Einträgen: verfügbar, sobald das
    # heutige Datum (Monat/Tag, jahresunabhängig) in mindestens einen Zeitraum fällt.
    seasons = db.relationship('RecipeSeason', backref='recipe', cascade="all, delete-orphan")


class RecipeSeason(db.Model):
    """Ein Verfügbarkeitszeitraum eines Rezepts (Monat/Tag, jahresunabhängig).
    Ein Rezept kann mehrere davon haben (mehrere Standard-Saisons und/oder ein
    eigener Zeitraum) - siehe SEASON_PRESETS in app.py."""
    id = db.Column(db.Integer, primary_key=True)
    recipe_id = db.Column(db.Integer, db.ForeignKey('recipe.id'), nullable=False)
    start_month = db.Column(db.Integer, nullable=False)
    start_day = db.Column(db.Integer, nullable=False)
    end_month = db.Column(db.Integer, nullable=False)
    end_day = db.Column(db.Integer, nullable=False)


class Ingredient(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    recipe_id = db.Column(db.Integer, db.ForeignKey('recipe.id'), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    unit = db.Column(db.String(20), nullable=False)


class PlanDay(db.Model):
    """Der dauerhafte Wochenplan-Kalender: ein Datensatz pro echtem Kalendertag,
    der jemals geplant wurde (nicht mehr nur ein flüchtiger, serverseitig
    einmalig gerenderter Zustand)."""
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, unique=True, nullable=False, index=True)
    excluded = db.Column(db.Boolean, default=False, nullable=False)
    servings = db.Column(db.Integer, nullable=False, default=2)
    main_recipe_id = db.Column(db.Integer, db.ForeignKey('recipe.id'), nullable=True)
    side_recipe_id = db.Column(db.Integer, db.ForeignKey('recipe.id'), nullable=True)

    main_recipe = db.relationship('Recipe', foreign_keys=[main_recipe_id])
    side_recipe = db.relationship('Recipe', foreign_keys=[side_recipe_id])

