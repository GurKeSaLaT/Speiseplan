# Ideas for Extensions

Backlog for future features - not yet implemented, just collected.

## Implemented

- **Swap days on the finished plan.** Day cards on `plan.html` are now
  fully swappable via drag-and-drop (main dish, side dish, and exclusion
  status), purely client-side.
- **Side dish also on days without a main dish.** Side-dish assignment is
  decoupled from main-dish exclusion; "excluded" now only blocks the main
  dish.
- **No same category on two consecutive days.**
  `assign_balanced_categories()` in `services/planning.py` avoids the
  category of the direct predecessor/successor day during automatic
  filling and rerolling, but relaxes this instead of leaving a day empty.
- **Season assignment for recipes.** Recipes can get several standard
  seasons (spring/summer/autumn/winter) and/or a custom date range, empty
  = year-round. Automatic selection (`choose_recipe()`) prefers currently
  available recipes, but falls back to all if needed - manual selection is
  never restricted.
- **Serving count & amount scaling.** New `Recipe.servings` field: for how
  many people the entered ingredient amounts are sized. On the plan page,
  every weekday has its own serving-count field (default 2), which scales
  that day's ingredient amounts up/down on the shopping list. Nutrition
  values stay unscaled (they're per serving/person). The serving count is
  tied to the weekday, not the dish - so it doesn't travel along on a day
  swap.
- **Favorites.** New `Recipe.is_favorite` field. Favorites are drawn with
  `FAVORITE_WEIGHT` times the probability (currently 3x) during automatic
  selection/rolling (`weighted_recipe_choice()`), instead of an even draw
  - not a rating, just a yes/no bonus.
- **Weekly nutrition overview.** On the plan page, a card shows the weekly
  total and the average per planned day for calories/protein/carbs/fat
  (across all main and extra dishes), updated live on every change to the
  plan.
- **Persistent plan calendar.** New `PlanDay` model: one record per real
  calendar day (main dish, side dish, exclusion status, serving count), no
  longer a transient display. The plan page (`/plan/<Monday date>`) is now
  the main page, with week navigation (back/forward, date jump) at the
  top. Weeks without a plan show a "Create new weekly plan" button, which
  leads to the former day-assignment page (now `/plan/<date>/create`, only
  reachable that way). All live actions (roll, swap, remove side dish,
  change serving count) write directly to the database. Lays the
  groundwork for later analytics (e.g. how often which category/recipe
  came up), but still **without** a cross-week repetition block or a
  review/analytics view - both would now be easy to add on top of the
  existing data.
- **Ingredient categories for the shopping list.** New
  `Ingredient.category` field (fixed value range from
  `services/shopping.py: SHOPPING_CATEGORIES`, in shopping order:
  produce, dairy, toiletries, drinks, pasta/grains, canned goods, frozen
  goods, rest = misc). Chosen via dropdown when entering an ingredient,
  and groups/sorts the shopping list accordingly instead of purely
  alphabetically. Existing ingredients land in misc until next edited.
- **Manually add items to the shopping list.** New `ExtraShoppingItem`
  model (tied to a calendar week, no recipe needed) - e.g. for toiletries
  or drinks that don't belong to any dish. Own delete button per manual
  item, sorted into the same categorized order as recipe ingredients.
- **Soft repetition weighting (no hard block).** New function
  `services/planning.py: recent_usage_counts()` counts how often a recipe
  appeared in the plan calendar in the last `REPETITION_LOOKBACK_WEEKS`
  weeks (currently 8) BEFORE the day currently being planned.
  `weighted_recipe_choice()` reduces the draw probability per use by a
  factor of 1/(count+1) - never used = full chance, frequently used =
  small, but never zero chance. Multiplies with the existing favorite
  weighting. Since season pre-filtering in `choose_recipe()` already
  applies BEFORE this weighting, currently seasonal recipes are
  automatically favored too, without a separate third factor.
- **Manual recipe selection on the plan page.** Both the main dish and
  each individual side dish can be chosen directly from all recipes via
  the ✏️ button instead of rolled (search/select box, replaces the
  display in place). Deliberately WITHOUT any of the automatic rules that
  apply when rolling (category balance, neighborhood, weekly duplicates,
  repetition weighting) - a manual selection is an explicit user wish.
  Automatically resets `excluded` on an excluded day
  (`routes/plan/day_actions.py: set_main_day`).
- **Any number of side dishes per day.** New table `PlanDaySide` replaces
  the former single `PlanDay.side_recipe_id` column (migration in
  `migrations.py` including a table rebuild, since SQLite doesn't allow
  directly removing a column referenced by a foreign key via
  `DROP COLUMN`). A day can now have any number of side dishes at once,
  each individually rollable/manually replaceable/removable (`side/add`,
  `side/<id>/reroll`, `side/<id>/set`, `side/<id>/remove`) and
  individually movable to another day via drag-and-drop
  (`side/<id>/move/<date>`, `static/plan-sides.js: moveSideDish`) -
  without touching the rest of the target/source day. When the whole day
  card (main dish) is moved/swapped, all its side dishes travel along.
  When creating a new week (`create_week.html`) too, a day can be
  assigned several side dishes (automatically distributed to the day with
  the fewest so far).
- **Recipe import from chefkoch.de.** New fields `Recipe.source_url`
  (link) and `Recipe.instructions` (instructions as free text), both also
  usable by hand. New service `services/recipe_import.py`: reads the
  embedded schema.org/Recipe JSON-LD structured data of a chefkoch.de page
  (the same format search engines use to crawl recipes - more robust than
  HTML scraping, since it practically never changes) and delivers name,
  serving count, nutrition info (if present), ingredients (best-effort
  split into amount/unit/name), and preparation steps. The import button
  on the recipe-create page only fills in the form with this - the user
  reviews/completes it (especially the category, which can't be assigned
  automatically) and then saves normally. Deliberately restricted hard to
  an allowlist (`ALLOWED_HOSTS`) for SSRF security reasons - could be
  extended to further schema.org/Recipe-compatible cooking sites, since
  the parser itself isn't chefkoch-specific (see the following entry,
  which did exactly that).
- **Recipe import extended to eight further German-language cooking
  sites.** `ALLOWED_HOSTS` in `services/recipe_import.py` now additionally
  covers, besides chefkoch.de: lecker.de, essen-und-trinken.de,
  eatsmarter.de, kuechengoetter.de, gutekueche.de AND gutekueche.at (two
  separate, structurally identical sites for Germany/Austria),
  daskochrezept.de, brigitte.de, and emmikochteinfach.de - each
  individually checked via a live fetch for whether it actually embeds a
  `"@type": "Recipe"` JSON-LD object BEFORE being added (no pure
  domain-guessing). Deliberately NOT included: kochbar.de (content is
  loaded purely client-side via JavaScript, `requests` sees none of it),
  ichkoche.at (no JSON-LD data at all), and springlane.de (marks its
  recipe pages as `"Article"`, not `"Recipe"`) - all three would need
  either HTML scraping or a real browser engine, both a substantially
  larger (and more fragile) undertaking than adding a domain.
  `KNOWN_UNITS` (see `_parse_ingredient_line`) extended with spelled-out
  units like "Gramm"/"Esslöffel" that chefkoch.de rarely uses but several
  of the new sites regularly use instead of abbreviations.
- **Light/dark mode.** Three settings (system/light/dark), switcher in
  account management as a `btn-check` radio group. `templates/base.html`
  applies the stored setting (localStorage, per browser/device) right at
  the start of `<head>`, before the CSS links, so no wrong theme flashes -
  via the same `data-bs-theme` attribute that Bootstrap 5.3 itself reacts
  to and automatically adapts almost all of its own components through.
  `static/style.css` redefines its own color tokens for this under
  `[data-bs-theme="dark"]`, plus targeted fixes for the few Bootstrap
  classes (`.text-dark`, `.bg-light`/`.bg-white`,
  `.btn-dark`/`.btn-outline-dark`, `.bg-dark`) that treat "dark"/"light"
  as a plain, non-themeable color name instead of adapting along with the
  rest of the page.
- **Unit unification.** New `services/units.py`: combines different
  spellings of the same unit (e.g. "g"/"Gramm"/"gr" or
  "kg"/"Kilo"/"Kilogramm") and converts amounts from two families with a
  clear base unit - mass -> grams, volume (incl. kitchen measures
  tsp/tbsp/cup, fixed approximations 5/15/250 ml) -> milliliters - ALWAYS
  onto this base when saving ("1 kg" becomes "1000 g", "2 tbsp" becomes
  "30 ml"). Applies both when manually creating/editing a recipe
  (`routes/recipes/crud.py`) and on import
  (`services/recipe_import.py: _parse_ingredient_line`), as well as once
  for existing data (`renormalize_existing_ingredients()`, runs
  idempotently on every app start in `migrations.py: init_db()` - an
  already canonical row stays unchanged). Non-convertible, piece-based
  units (pc, bunch, pinch, can, ...) are left untouched.

  New singleton model `AppSettings` (`services/settings.py`) stores which
  unit to DISPLAY per family (g or kg, ml or l) - own management page
  `/manage/units` (blueprint `settings`, tile "📏 Units" on `/manage`).
  The canonically stored values are unaffected by this;
  `convert_for_display()` converts ONLY for display, everywhere ingredient
  amounts are shown: `jsonify_recipe()` (shopping list, weekly plan page -
  since the client-side aggregation in `rebuildShoppingList()` groups
  identically named ingredients purely by "name+unit", it's essential
  that ALL occurrences of a family arrive server-side consistently in the
  same unit), the recipe-editing form (`recipe_edit_view()`), and the
  import preview (`import_recipe_preview()`). The conversion is exact and
  losslessly reversible (factor 1000); saving without changing a value
  displayed in kilograms yields, via `normalize_amount_unit()`, exactly
  the same canonical gram value again.
- **Ingredient aliasing.** New model `IngredientAlias` (`raw_name` unique
  -> `canonical_name`) + `services/ingredient_aliases.py`: maps specific
  ingredient names (e.g. "spaghetti", "fusilli") to a shared name (e.g.
  "pasta"), ONLY for the shopping list - a single recipe's ingredient list
  always shows the originally entered name unchanged.
  `normalize_ingredient_name()` is called in `jsonify_recipe()` instead of
  the previous plain `.strip().title()` (still does that internally, plus
  alias replacement if present) - an ingredient name with no entry simply
  stays itself, no grouping is the default case. Own management page
  `/manage/ingredient-aliases` (blueprint `settings`, tile on `/manage`):
  one row per ingredient name currently used in any recipe with an
  editable "counts as" field, all savable at once via form (parallel
  `raw_name[]`/`canonical_name[]` lists, analogous to the ingredient rows
  of the recipe forms) instead of one round trip per row - impractical
  otherwise with potentially hundreds of ingredients. A field left
  unchanged (still counts only as itself) creates no alias record.
- **DE/EN localization.** Flask-Babel-based, with English as the default
  UI language and German as a fully translated second language,
  switchable per account under ⚙️ → 👤 Account (`User.language`, see
  `app.py: get_locale()`) - not per browser/device like the theme switch
  above, since real accounts already exist. Every user-facing string is
  wrapped in `gettext`/`lazy_gettext`; the German catalog lives in
  `translations/de/LC_MESSAGES/messages.po`, compiled to `.mo` via
  `pybabel compile`. JS strings are outside Flask-Babel's reach (it only
  extracts from `.py`/`.html`) and stay hardcoded English for now - a
  known, accepted gap (see "Known gaps" below).

## Proposed

1. **Compute nutrition from the ingredients.** Instead of entering
   calories/protein/carbs/fat manually per recipe, compute them directly
   from the stored ingredients and their amount. Needs a nutrition
   reference per ingredient (e.g. values per 100g on `Ingredient`/a
   dedicated ingredient master-data table). Unit conversion (g/ml) has
   existed since `services/units.py` - only piece-based units (pc, bunch,
   ...) would still need an ingredient-specific weight for exact
   nutrition values.
2. **Extend recipe import to even more cooking sites.** The import now
   supports 9 sites (see "Implemented" above) - further schema.org/Recipe-
   compatible sites (e.g. international portals, blogs) can be added the
   same way, via a live check + domain addition to `ALLOWED_HOSTS`.
   Kptncook, for example, is an app without public recipe web pages and
   therefore couldn't be supported this way.

## Known gaps

- **Some German constants deliberately left untranslated.** A few
  module-level constants are matched by equality against values ALREADY
  STORED in the database, or represent a parser's German-word-recognition
  vocabulary, rather than being pure display text - translating them
  without an accompanying data migration would silently break existing
  categorization/matching for anyone with pre-existing data:
  `services/plans.py: DEFAULT_CATEGORIES` (the starter category set seeded
  for new plans), `services/shopping.py: SHOPPING_CATEGORIES`/
  `PANTRY_CATEGORIES`, `services/units.py`'s unit-recognition vocabulary,
  and `services/seasons.py: SEASONS`/`SEASON_PRESETS`. Translating these
  properly would need a one-time data migration that rewrites any
  matching stored values (`Category.name`, `Ingredient.category`,
  `ExtraShoppingItem.category`, season labels) alongside the constant
  itself.
- **JS strings aren't localized.** Flask-Babel only extracts from
  `.py`/`.html` files - user-facing strings in `static/*.js` (mostly
  `alert()`/`confirm()` calls and a handful of status messages) are
  therefore plain, hardcoded English regardless of the account's chosen
  language. Small, low-traffic surface; building a second i18n path for
  JS wasn't judged worth it yet.

## Waiting on real email delivery

Everything here only becomes worth implementing once `services/mail.py`
actually sends emails instead of just logging them (see the docstring
there - no SMTP credentials in place yet).

1. **Notification on plan invite.** Currently an invited user only
   notices a share if they check `/manage/sharing` themselves - the
   actual invite email (`send_invite_email()`) is only logged and
   additionally shown as a copyable link on the sharing page (see
   `templates/sharing.html`: "Pending invites").
2. **Password reset via email.** There is currently no "forgot password"
   feature - a forgotten password can't be reset anywhere by yourself.
   Would need a time-limited reset link sent by email (analogous to the
   invite-link mechanism).
3. **Email verification on registration.** `routes/auth.py: register()`
   currently only checks the entered address for rough shape
   (`services/auth.py: EMAIL_PATTERN`), not actual deliverability - a
   confirmation link wouldn't be worth implementing without real email
   delivery.
