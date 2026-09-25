from models import db


class User(db.Model):
    """Identity comes from Authelia: email (lowercase) is the key, name is
    synced from Authelia on every request. language is the only
    app-level preference."""
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    language = db.Column(db.String(5), nullable=False, default='en')
    created_at = db.Column(db.DateTime, default=db.func.now())
