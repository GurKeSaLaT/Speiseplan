from models import db


class User(db.Model):
    """A user account - see services/auth.py for login/session handling.

    password_hash NEVER stores the plaintext password, but a hash produced
    via werkzeug.security.generate_password_hash() (PBKDF2 with salt) -
    services/auth.py: check_password() compares against it on login via
    werkzeug.security.check_password_hash(), without ever being able to
    reconstruct the password itself.

    Login happens via email (always stored lowercased, see
    routes/auth.py: login()/register()) - name is a pure display name
    WITHOUT uniqueness, so two users are allowed to have the same name.
    Registration runs via routes/auth.py: register() (button on the login
    page); at app start, migrations.py: init_db() additionally still seeds
    two generic demo accounts ("Nutzer1"/"Nutzer2") (placeholder emails
    following the pattern <name>@example.com, see there).

    language is the ISO 639-1 code Flask-Babel uses to pick this user's
    translation catalog (see app.py: get_locale()) - defaults to 'en'
    (English is the app's default language). Changeable on /manage/account
    (see services/accounts.py: update_profile())."""
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    language = db.Column(db.String(5), nullable=False, default='en')
    created_at = db.Column(db.DateTime, default=db.func.now())
