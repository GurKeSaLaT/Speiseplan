from models import db


class User(db.Model):
    """A user account - identity is no longer managed by this app at all
    (see services/auth.py module docstring): authentication happens
    entirely in Authelia, in front of the reverse proxy, which attaches
    the authenticated email/display name to every request as a header.
    This app never stores or checks a password.

    email (always lowercased) is the identity key - it's how
    services/auth.py: current_user() finds or auto-provisions the matching
    row for whatever email Authelia attaches to a request. name is kept in
    sync with Authelia's display name on every request (see there) rather
    than being independently editable here.

    language is the ISO 639-1 code Flask-Babel uses to pick this user's
    translation catalog (see app.py: get_locale()) - defaults to 'en'
    (English is the app's default language). This one IS still an
    app-level preference, changeable on /manage/account (see
    services/accounts.py: update_language())."""
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    language = db.Column(db.String(5), nullable=False, default='en')
    created_at = db.Column(db.DateTime, default=db.func.now())
