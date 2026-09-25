# 🍽️ Speiseplan

A self-hosted weekly meal planner. Keep recipes with ingredients and
nutrition, plan weeks by click or drag-and-drop, let the rest fill itself
in, and get a combined shopping list.

## Features

- **Plans and sharing**: any number of weekly plans per user, shared with
  others by email. Recipes belong to one plan and can be linked into more.
- **Plan calendar**: every week is stored per day (Friday to Thursday).
  The home page summarizes the current week across all your plans.
- **Automatic filling**: open days get a random recipe, balanced across
  categories, no category on two days in a row, favorites and seasonal
  recipes preferred, recently cooked ones less likely.
- **Manual control**: fix recipes per day before generating, re-roll or
  pick by hand afterwards, swap days by drag-and-drop, exclude days, any
  number of side dishes per day.
- **Shopping list**: ingredients summed across the week, scaled to each
  day's servings and grouped by shop category. Pantry items are listed
  separately. Manual items can be added.
- **Ingredients and nutrition**: spelling variants merge into one shopping
  list entry ("Spaghetti", "Fusilli" → "Noodles"). Nutrition per 100 g,
  100 ml or 1 piece; recipe nutrition is computed from it unless entered
  by hand.
- **Units**: amounts are stored in g/ml and shown in g/kg or ml/l as
  configured.
- **Recipe import** from chefkoch.de, lecker.de, essen-und-trinken.de,
  eatsmarter.de, kuechengoetter.de, gutekueche.de/.at, daskochrezept.de,
  brigitte.de and emmikochteinfach.de (schema.org JSON-LD).
- **Autosave** on the recipe form and the ingredients page.
- English and German UI, light and dark mode.

Changes are listed in [CHANGELOG.md](CHANGELOG.md), open ideas in
[IDEAS.md](IDEAS.md).

## Stack

Flask, Flask-SQLAlchemy (SQLite), Flask-Babel, Flask-WTF (CSRF), Jinja
templates with vanilla JS, Bootstrap 5 (vendored, works offline).

## Authentication

The app has no login of its own. It runs behind
[Authelia](https://www.authelia.com/) as forward auth (here behind SWAG),
and trusts two request headers:

- `Remote-Email`: identifies the user; a user is created on first sight.
- `Remote-Name`: display name, updated on every request.

**Never expose the app port directly.** Anyone who can reach it without
the proxy can set these headers and act as any user.

For local development, send the header yourself:

```bash
curl -H "Remote-Email: you@example.com" -H "Remote-Name: You" http://127.0.0.1:5000/
```

## Running locally

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
HOST=127.0.0.1 python3 app.py        # http://127.0.0.1:5000, debug mode
```

The database is created in `instance/speiseplan.db`; migrations run on
every start. `SEED_DEMO_DATA=1` loads about 100 sample recipes from
`fixtures/demo_data.json` into an empty database (no effect once any user
exists).

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `AUTHELIA_LOGOUT_URL` | unset | Shows a "Log out" link pointing there |
| `AUTHELIA_EMAIL_HEADER` | `Remote-Email` | Identity header name |
| `AUTHELIA_NAME_HEADER` | `Remote-Name` | Display name header name |
| `SECRET_KEY` | generated in `instance/secret_key` | Session/CSRF key |
| `DATABASE_URL` | `sqlite:///instance/speiseplan.db` | Database |
| `SEED_DEMO_DATA` | unset | `1` seeds demo data into an empty DB |
| `HOST` / `PORT` | `0.0.0.0` / `5000` | Listen address (Docker: port 80) |
| `FLASK_DEBUG` | `1` | `0` in Docker; never expose debug mode |

## Docker

```bash
docker build -t speiseplan .
docker run -d -p 8080:80 -v /path/to/data:/app/instance \
  -e AUTHELIA_LOGOUT_URL=https://auth.example.com/logout speiseplan
```

`instance/` holds the database and secret key; mount it as a volume.
Back it up before deploying a new version.

## Tests

```bash
pip install -r requirements.txt -r requirements-dev.txt
pytest
```

Tests use their own temporary SQLite database.

## Project structure

```
app.py              App setup, blueprints, template context
migrations.py       Schema migrations, one function per step, run on start
models/             SQLAlchemy models: user, plan, recipe, calendar, settings
routes/             Blueprints
  plan/               Week pages, day actions (main/sides), shopping items
  recipes/            Recipe CRUD and import, links to other plans
  plans.py, sharing.py, account.py, auth.py, categories.py, settings.py, manage.py
services/           Logic without HTTP: auth, planning, week generation,
                    nutrition, units, aliases, seasons, recipe import, ...
templates/          Jinja templates, one per page plus base.html
static/             Page scripts (plan*.js, create_week.js, recipe_form.js,
                    ingredient_aliases.js, ...), style.css, Bootstrap
translations/       German catalog (pybabel)
fixtures/           Demo data as JSON
tests/              pytest suite
```

## License

[MIT](LICENSE)
