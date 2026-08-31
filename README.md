# 🍽️ Speiseplan

A self-hosted weekly meal planner with a persistent calendar: maintain
recipes with nutrition info and ingredients, assemble weeks by click or
drag-and-drop, let the rest fill in automatically in a balanced way, and
get a consolidated shopping list at the end.

## Features

- **User accounts & shared plans** – registration via name/email/password,
  login via email address. Every user can create any number of their own
  weekly plans (switcher in the sidebar, defaults to the starred plan) and
  share individual plans with others by email address – if an account
  already exists for that address, the plan is shared immediately,
  otherwise an invite to register is "sent" (currently only logged and
  shown as a link on the sharing page, since no SMTP is wired up yet).
  Recipes, categories, units, and ingredient aliasing each belong to ONE
  plan; a recipe can additionally be linked into further plans of your own
  (a real link, not a copy). Every day tile in the weekly plan additionally
  shows (togglable per plan) what's being cooked that day in your OTHER
  own plans.
- **Persistent plan calendar** – every planned week is stored per calendar
  day in the database, not just shown transiently. The home page shows the
  current week with navigation (previous/next week, date jump); unplanned
  weeks show a "Create new weekly plan" button.
- **Light/dark mode** – follows the OS setting by default, but can also be
  fixed to light or dark in account management (⚙️ → 🎨 Appearance). The
  choice is saved per browser/device.
- **Recipe management** – create, edit, and delete dishes with category,
  nutrition info (calories, protein, carbs, fat), serving count, an
  arbitrary ingredient list, a link, and preparation instructions.
- **Unit unification** – ingredient amounts are automatically brought into
  a canonical form when entered or imported (mass → grams, volume incl.
  tsp/tbsp/cup → milliliters; "1 kg" becomes "1000 g" internally). Account
  management (⚙️ → 📏 Units) lets you set whether amounts are shown in
  g/kg or ml/l – applies everywhere amounts are shown (recipe editing,
  import preview, shopping list).
- **Ingredient aliasing** – account management (⚙️ → 🔗 Merge Ingredients)
  lets you set, for example, that "spaghetti" and "fusilli" are combined
  as "pasta" on the shopping list. Only affects the shopping list –
  recipes still show their own ingredient name.
- **Recipe import from nine German-language cooking sites** – chefkoch.de,
  lecker.de, essen-und-trinken.de, EAT SMARTER, Küchengötter,
  gutekueche.de/.at, DasKochrezept, BRIGITTE, and Emmikochteinfach. Just a
  link: name, serving count, nutrition info (if given), ingredients, and
  instructions are read automatically and carried over into the create
  form; it's only saved after review/completion (especially the category)
  by the user.
- **Drag-and-drop weekly planning** – drag or click dishes from the live
  search onto individual weekdays, swap days completely via drag-and-drop
  (also on the finished plan page, side dishes travel along), exclude
  individual days from planning. On the finished plan page, every main
  dish and every side dish can also be manually chosen from all recipes
  via the ✏️ button instead of only rolled.
- **Extra dishes/side dishes** – recipes can be marked as a side dish.
  They don't occupy their own day slot, but are added in addition to the
  main dish – even on days without a main dish – either fixed before
  creating the plan or added afterward via the dice/select button. A day
  can have any number of side dishes at once; each one can independently
  be re-rolled, replaced, removed, or moved to another day via
  drag-and-drop.
- **Automatic, balanced filling** – days without a fixed assignment are
  filled randomly, but distributed as evenly as possible across all
  categories, without repeating the same category on two consecutive days
  (where avoidable).
- **Season assignment** – recipes can get several standard seasons and/or
  a custom date range; automatic selection prefers currently available
  dishes, but never restricts manual selection.
- **Favorites** – recipes marked as a favorite are drawn more often than
  others when rolling.
- **Serving count & amount scaling** – every weekday has its own serving
  count field, which scales that day's ingredient amounts up/down on the
  shopping list.
- **Weekly nutrition overview** – sum and average of calories and macros
  across the whole week.
- **Shopping list** – ingredients of all planned main and extra dishes are
  automatically totaled and can be checked off while shopping.

A running list of further ideas (implemented and planned) is in
[IDEAS.md](IDEAS.md).

## Tech Stack

- [Flask](https://flask.palletsprojects.com/) + [Flask-SQLAlchemy](https://flask-sqlalchemy.palletsprojects.com/),
  routes organized as blueprints (see project structure)
- [Flask-Babel](https://python-babel.github.io/flask-babel/) for DE/EN
  localization (English is the default language; the UI language is
  changeable per account under ⚙️ → 👤 Account)
- SQLite as the database (lives in `instance/speiseplan.db`)
- [Bootstrap 5](https://getbootstrap.com/) (bundled locally, no CDN)
- Vanilla JavaScript for drag-and-drop, live search, and dynamic
  plan/shopping-list updates; server data is made available to the
  frontend via a `window.PLAN_DATA` JSON object (Jinja `tojson`)

## Setup

```bash
git clone git@github.com:GurKeSaLaT/Speiseplan.git
cd Speiseplan

python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

python3 app.py
```

The app then runs at `http://127.0.0.1:5000` and redirects to the login
page. `instance/speiseplan.db` is version-controlled in the repo with
sample data (around 100 imported recipes including ingredient aliasing)
plus two generic demo accounts, so the app can be tried out meaningfully
right after setup instead of starting with an empty database:

| Email                     | Password  |
|----------------------------|-----------|
| `nutzer1@example.com`    | `Nutzer1` |
| `nutzer2@example.com`    | `Nutzer2` |

The "Create account" button on the login page lets you create another,
separate account at any time. On later updates, missing tables/columns
are migrated automatically. This sample-data detail is irrelevant for
the Docker deployment - there, `instance/` is mounted as a volume onto a
directory outside the container (see below), which always takes
precedence over the database state included in the image.

By default the server listens on all network interfaces (`0.0.0.0`) -
for a purely local test run that shouldn't be reachable from the LAN,
use `HOST=127.0.0.1 python3 app.py`.

### With Docker

```bash
docker build -t speiseplan .
docker run -p 5000:5000 speiseplan
```

## Tests

```bash
pip install -r requirements.txt -r requirements-dev.txt
pytest
```

Runs entirely against its own, temporary SQLite database (see
`tests/conftest.py` and `DATABASE_URL` in `app.py`) - `instance/speiseplan.db`
stays untouched.

## Project Structure

```
app.py                        App setup, blueprint registration, Babel/security wiring
migrations.py                 Database migrations, one named function per step, run on startup
models/                       SQLAlchemy models, split by domain:
  user.py                       User
  plan.py                       Plan, PlanMembership, PendingPlanInvite
  recipe.py                     Category, Recipe, RecipePlanLink, RecipeSeason, Ingredient
  calendar.py                   PlanDay, PlanDaySide, ExtraShoppingItem
  settings.py                   AppSettings, IngredientAlias, IngredientNutrition
routes/
  auth.py                     Login, registration, logout, switch active plan (blueprint "auth")
  account.py                  Change own profile/password, delete account (blueprint "account")
  plans.py                    Create/rename/delete a plan (blueprint "plans")
  sharing.py                  Members/invites/star of a plan, leave a plan (blueprint "sharing")
  plan/                       Calendar week view, create plan, roll/swap/manual selection,
                               side dishes, shopping list (blueprint "plan", split across four
                               files that share the same blueprint):
    pages.py                    Page routes (/, /plan/<start>, .../create, .../generate)
    day_actions.py              AJAX: main dish roll/select, whole-day swap/servings/cooked
    day_actions_sides.py        AJAX: side dish add/roll/select/remove/move/cooked
    shopping.py                 AJAX: manual shopping-list items
  recipes/                    Recipe CRUD + recipe import + plan linking (blueprint "recipes",
                               split across two files that share the same blueprint):
    crud.py                     Create/edit/delete/list views + import-preview endpoint
    links.py                    Link/unlink a recipe to/from another plan
  categories.py                Category CRUD (blueprint "categories")
  manage.py                    Management home page (blueprint "manage")
  settings.py                  Unit + ingredient-aliasing settings (blueprint "settings")
services/
  auth.py                      Login/session, active plan, tab-selection helpers (current_plan(),
                                selected_plan_id(), default_plan_id())
  accounts.py                  Change own profile/password, delete account
  plans.py                     Plan lifecycle (create/delete, accept invites)
  mail.py                      Invite email sending (currently only logged, no SMTP wired up)
  recipe_visibility.py         Which recipes are visible for a plan (owner + links)
  planning.py                  Week/date helpers, category balance, recipe selection,
                                favorite/repetition weighting
  week_generation.py           Balanced-category-assignment + recipe-selection orchestration
                                behind "(re-)create a whole week"
  seasons.py                   Season assignment (standard seasons + custom date ranges)
  shopping.py                  Fixed shopping-list category order
  recipe_import.py             Recipe import from 9 cooking sites (reads schema.org/Recipe JSON-LD)
  units.py                     Unit normalization/conversion (mass -> g, volume -> ml)
  settings.py                  Storage of the display-unit setting (AppSettings)
  ingredient_aliases.py        Ingredient aliasing for the shopping list (IngredientAlias)
translations/                 Flask-Babel German catalog (translations/de/LC_MESSAGES/messages.po)
templates/                    Jinja2 templates (login/registration, plan calendar,
                               create weekly plan, account management, sharing, profile)
static/
  plan.js                       Plan page: state, day cards, main dish, day swap
  plan-manual-select.js          Reusable recipe-search box (main dish + side dishes)
  plan-sides.js                  Side dishes: add/roll/select/remove/move
  plan-shopping.js               Weekly nutrition overview + shopping list
  create_week.js                Live search & drag-and-drop when creating a weekly plan
  ingredient_category_select.js Option markup shared by the recipe forms
  bootstrap.*, style.css        Local Bootstrap 5 + custom stylesheet
instance/speiseplan.db        SQLite database
```

## License

Published under the [MIT License](LICENSE).
