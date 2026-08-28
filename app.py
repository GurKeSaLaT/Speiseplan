import os

from sqlalchemy import text
from flask import Flask

from models import db, Category, RecipeSeason
from services.seasons import SEASON_PRESETS
from routes.plan import plan_bp
from routes.manage import manage_bp
from routes.recipes import recipes_bp
from routes.categories import categories_bp

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(app.instance_path, 'speiseplan.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

os.makedirs(app.instance_path, exist_ok=True)
db.init_app(app)

app.register_blueprint(plan_bp)
app.register_blueprint(manage_bp)
app.register_blueprint(recipes_bp)
app.register_blueprint(categories_bp)


def init_db():
    db.create_all()

    # Migration: bestehende Datenbanken hatten noch keine is_side_dish-Spalte
    existing_columns = {row[1] for row in db.session.execute(text("PRAGMA table_info(recipe)"))}
    if 'is_side_dish' not in existing_columns:
        db.session.execute(text("ALTER TABLE recipe ADD COLUMN is_side_dish BOOLEAN NOT NULL DEFAULT 0"))
        db.session.commit()
    if 'servings' not in existing_columns:
        db.session.execute(text("ALTER TABLE recipe ADD COLUMN servings INTEGER NOT NULL DEFAULT 2"))
        db.session.commit()
    if 'is_favorite' not in existing_columns:
        db.session.execute(text("ALTER TABLE recipe ADD COLUMN is_favorite BOOLEAN NOT NULL DEFAULT 0"))
        db.session.commit()

    # Migration: die frühere einzelne season-Spalte gibt es nicht mehr (ersetzt durch
    # die recipe_season-Tabelle, die mehrere Zeiträume pro Rezept erlaubt). Bestehende
    # Werte einmalig in die neue Tabelle übernehmen, dann die alte Spalte entfernen.
    if 'season' in existing_columns:
        old_seasons = db.session.execute(text("SELECT id, season FROM recipe WHERE season IS NOT NULL")).fetchall()
        for recipe_id, season_name in old_seasons:
            preset = SEASON_PRESETS.get(season_name)
            if preset:
                db.session.add(RecipeSeason(
                    recipe_id=recipe_id,
                    start_month=preset[0], start_day=preset[1],
                    end_month=preset[2], end_day=preset[3]
                ))
        db.session.commit()
        db.session.execute(text("ALTER TABLE recipe DROP COLUMN season"))
        db.session.commit()

    if not Category.query.first():
        default_categories = ["Fleisch", "Fisch", "Vegetarisch", "Vegan", "Nudeln/Pasta", "Suppe/Eintopf", "Schnelle Küche"]
        for cat_name in default_categories:
            db.session.add(Category(name=cat_name))
        db.session.commit()


with app.app_context():
    init_db()


@app.context_processor
def inject_css_version():
    # Cache-Bremse für style.css: Änderungsdatum der Datei als Query-Parameter,
    # damit Browser nach einem Update nicht die alte Version aus dem Cache laden
    css_path = os.path.join(app.static_folder, 'style.css')
    try:
        css_version = int(os.path.getmtime(css_path))
    except OSError:
        css_version = 0
    return {'css_version': css_version}


if __name__ == '__main__':
    # FLASK_DEBUG=0 und PORT=80 im Docker-Deployment gesetzt (siehe Dockerfile) -
    # lokal ohne gesetzte Variablen bleiben Debug-/Autoreload-Modus und Port 5000
    # (kein Root fuer privilegierte Ports noetig) wie gewohnt.
    # Im Container: 0.0.0.0-Bindung noetig, sonst ist die App von aussen nicht erreichbar.
    debug_mode = os.environ.get('FLASK_DEBUG', '1') == '1'
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=debug_mode)
