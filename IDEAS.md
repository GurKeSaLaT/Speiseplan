# Ideas for Extensions

Backlog for future features - not yet implemented, just collected.

## Implemented

- **Merged "Merge Ingredients" and "Nutrition" into one page, fully
  autosaving, with a jump-to-recipe link.**
  `/manage/ingredient-aliases` (routes/settings.py: ingredient_aliases_view(),
  templates/ingredient_aliases_manage.html) now covers both what used to
  be two separate pages: two sub-tabs, "Main Ingredients" (every
  canonical name at least one other ingredient is aliased to, each with
  its own nutrition editor and, nested underneath, every merged spelling
  - removable via "×") and "Everything Else" (every other known
  ingredient, ALSO with its own nutrition editor - previously only
  settable via the recipe form's inline hint - plus a "Counts as" field
  to promote it into a main ingredient). The former
  `/manage/ingredient-nutrition` page/route is gone; its sidebar tile
  and rail link were merged into one "🔗 Ingredients & Nutrition" entry.

  Every field on the page saves itself immediately (`fetch()` on
  change/blur, small "✓"/"⚠" `.autosave-indicator`) - there is no Save
  button and no batch-submit endpoint anymore. Nutrition edits reuse
  `/api/ingredient-nutrition/set`; alias removal ("×") and "Counts as"
  reuse `/api/ingredient-alias/set` - the exact same AJAX endpoints the
  recipe form's inline hint already called, now also accepting an
  explicit `plan_id` in the request body (`routes/settings.py:
  _resolve_ajax_plan_id()`), since this page's own plan tab-switcher may
  be showing a plan other than the currently active one. Removing an
  alias or changing "Counts as" to a genuinely different name reloads the
  page (the row may need to move between sub-tabs, simplest to get right
  server-side); pure nutrition edits never reload.

  Clicking an ingredient or alias name jumps straight to a recipe it's
  part of (`services/ingredient_aliases.py: recipes_by_ingredient_name()`,
  one query in the whole view, not one per name - see the performance
  note below): a name used in exactly one recipe links directly there, a
  name used in several shows a small dropdown to pick one.

  While merging the two pages' ingredient sets onto this one page, an
  existing per-name query in `services/nutrition.py: infer_reference_unit()`
  (previously only ever called for the small number of alias-target main
  ingredients) started also running once per "Everything Else" row -
  turning what used to be a handful of calls into one per known
  ingredient (hundreds), each doing its own ingredient-table scan. Caused
  a real production page load of 34.5 seconds. Fixed with a bulk
  counterpart, `infer_reference_units_for_plan()`, that computes every
  name's guess in a single pass over an already-fetched alias dict
  instead of one query per name - reduced the same page to roughly
  100ms. A regression test asserts the query count stays bounded
  (`tests/test_services_nutrition.py`, via SQLAlchemy's
  `before_cursor_execute` event) so a future per-name query creeping back
  into a loop over all known ingredients gets caught before it reaches
  production again.

  Two more issues surfaced live once real production data hit this
  rewrite. First, a main group's heading linked via `recipe_link()` only
  looked itself up in `recipes_by_ingredient_name()`'s result - but a
  canonical name is usually an invented umbrella (e.g. "Noodles" for
  "Spaghetti"/"Fusilli") that was never itself typed as an ingredient
  anywhere, so the heading came back with no recipe link at all even
  though its merged aliases obviously belong to one; many main
  ingredients appeared "unassigned". Fixed by linking to the union of
  recipes across the canonical name AND every alias merged into it
  (`routes/settings.py: _merged_recipes()`). Second, the alias-removal
  "×" button broke for literally every alias (not just ones with special
  characters) with `Uncaught SyntaxError: expected expression, got '}'`:
  it built `onclick="removeAlias(this, {{ alias.name | tojson }})"`, but
  Flask's `tojson` filter returns its result PRE-MARKED SAFE for a
  `<script>` context - it does not escape the double quotes JSON itself
  always wraps a string in, so that quote closed the `onclick="..."`
  attribute early and corrupted the rest of the tag. Fixed by moving the
  raw name into a plain, auto-escaped `data-raw-name` attribute and
  wiring the click via `addEventListener` instead, the same pattern the
  "Counts as" input on the same page already used safely - and a good
  reminder that `tojson` is only safe inside `<script>...</script>`,
  never inline in an HTML attribute.

  A third issue was UX rather than a bug: removing an alias or
  re-pointing "Counts as" used `window.location.reload()` to get a fresh
  server render of which sub-tab/group a row now belongs to - a REAL page
  navigation, which reset the scroll position to the top and lost
  whichever sub-tab/search filter was active, defeating the point of
  autosaving in the first place. An in-between fix (fetch the page in the
  background and swap the WHOLE `.card-body` in place instead of
  navigating) removed the scroll-jump but introduced a second live-
  reported issue of its own: jumping from the field that triggered the
  save into a completely unrelated NEXT field still lost focus/cursor
  there, since replacing that much markup destroys and recreates every
  row regardless of whether it actually changed.

  Fixed properly with row-level reconciliation instead
  (`reconcileIngredientSubtab()`): each `.ingredient-card` now carries a
  stable `data-row-key` (`main:<canonical name>` / `other:<raw name>`);
  `refreshIngredientsContent()` fetches the page, and for each sub-tab
  compares every row's `outerHTML` between the current DOM and the fresh
  fetch - a row that comes back byte-for-byte identical keeps its
  EXISTING, already-wired DOM node completely untouched (so any field a
  user has focused, cursor position included, survives if that row
  itself didn't change), and only rows that are new, removed, or
  genuinely different get swapped for the freshly rendered version and
  re-wired. Since nothing here is an actual navigation either, scroll
  position was never at risk in the first place, on top of now also
  preserving focus in every row unrelated to whatever triggered the
  save.

- **Automatic cleanup of orphaned ingredient aliases.** An `IngredientAlias`
  row is a plain string mapping (`raw_name` -> `canonical_name`),
  independent of any `Ingredient` row - so once a recipe's ingredient line
  is retyped/renamed or the recipe itself is edited/deleted, the old
  mapping simply lingers forever with nothing to clean it up. Real case
  that surfaced this: an alias "Ananasstücke" -> "Ananas" survived after
  the ingredient was retyped to "Ananasstücke (ca. 200g Abtropfgewicht)",
  so the old spelling no longer matched anything and the management page
  showed it as an unlinkable, orphaned row (see the "jump to recipe" link
  entry above). New `services/ingredient_aliases.py:
  prune_orphaned_aliases()` deletes any alias whose `raw_name` isn't used
  by any recipe currently visible to the plan - it reuses the
  `recipes_by_name` dict `ingredient_aliases_view()` already computes for
  the recipe links, so no extra query. Runs automatically on every view
  of the page (self-healing, no separate maintenance step); a real
  in-use alias is never touched.
- **Autosave for the recipe form.** No more explicit "Save changes"
  button for an EXISTING recipe: `static/recipe_form.js: rformAutosave()`
  resubmits the whole form via `fetch()` to the same `edit_recipe()`
  endpoint a traditional submit would use, debounced (800ms after the
  last change) and delegated on the form itself so it catches every
  field - name, category, servings, side dish/favorite/pantry toggles,
  nutrition override + values, season chips/custom range, source link,
  instructions. Ingredient rows added/removed via their own buttons don't
  fire a native `input`/`change` event, so
  `rformUpdateIngredientCount()` (already called after both) explicitly
  schedules a save too. `edit_recipe()` tells autosave calls apart from a
  traditional submit via an `X-Requested-With: XMLHttpRequest` header and
  answers with JSON (recalculated calories/protein/carbs/fat) instead of
  redirecting the page out from under whatever the user is still typing;
  a real, non-JS form submit still gets the normal redirect.

  Confirmed design for a brand NEW recipe: there's no id to autosave into
  before it exists, so creating one still needs exactly one explicit
  click ("Save recipe") - `add_recipe()` now redirects straight into
  `recipe_edit_view()` for the freshly created recipe (previously back to
  a blank create form, to enter the next recipe quickly) rather than the
  overview list, so autosave takes over immediately from there. The
  create-mode page keeps its Save button; the edit-mode page replaces it
  with a small "✓"/"⚠" status indicator, matching the ingredients &
  nutrition page's autosave pattern.
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
  stays itself, no grouping is the default case. Management page: see
  "Merged 'Merge Ingredients' and 'Nutrition' into one page, fully
  autosaving, with a jump-to-recipe link" above for its current form -
  superseded twice since this entry was first written.
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
## Implemented (continued)

- **Demo data moved out of the committed binary database.**
  `instance/speiseplan.db` is no longer version-controlled at all (see
  `.gitignore`) - it changed 34 times over the project's history, each
  time as an opaque, undiffable binary commit, and carried a real risk of
  a genuine deployment's actual data accidentally ending up committed
  through the same tracked path. The same sample content (recipes,
  categories, ingredient aliases, two example accounts, in FK-dependency
  order) now lives in `fixtures/demo_data.json` - plain, diffable JSON,
  loaded on demand by `services/demo_seed.py: seed_demo_data_if_requested()`
  via `SEED_DEMO_DATA=1` (see README.md: "Trying it out with sample
  data"). Deliberately opt-in rather than "seed whenever the database
  happens to be empty" - that condition is also exactly what a brand new
  production deployment looks like before its first real Authelia login.
  Loads via SQLAlchemy Core's `Table.insert()` rather than hand-written
  SQL text, so a fixture row that predates a later-added column (e.g. an
  ingredient from before `Ingredient.is_pantry` existed) still gets that
  column's normal default applied automatically. Added a `.dockerignore`
  at the same time - without one, `docker build` from a local working
  directory would happily bake in whatever real `instance/speiseplan.db`
  happens to sit there, independent of what git tracks.
- **Exclude/re-include a day AFTER the week already exists.** Previously
  `PlanDay.excluded` could only be set while first creating a week
  (`static/create_week.js`, `templates/create_week.html`) - there was no
  way back once the week was already created (see the plan page,
  `templates/plan.html`). New endpoint `routes/plan/day_actions.py:
  toggle_day_exclusion()` (`POST /day/<date>/toggle-exclude`) toggles it
  for a single calendar day, clearing the main dish when excluding (side
  dishes are untouched, matching the existing "excluded only applies to
  the main dish" rule) - a new 🚫 button next to the 🎲/✏️ actions on
  each day card calls it.
- **JS strings localized.** Closed the previous "JS strings aren't
  localized" gap: Flask-Babel only extracts from `.py`/`.html` files, so
  user-facing strings in `static/*.js` (status labels, button titles,
  `alert()` messages) are now routed through `window.I18N` - a single
  JSON blob rendered server-side in `templates/base.html` via `_(...)`,
  keyed by a short stable name rather than the English text itself. JS
  call sites reference `window.I18N.<key>` instead of hardcoded English;
  the German catalog (`translations/de/LC_MESSAGES/messages.po`) covers
  every one of them. While auditing this, found and fixed two more spots
  (`static/plan.js`: `renderMainDisplay()`, `static/plan-sides.js`:
  `renderSidesSection()`) that interpolated a recipe/category name
  straight into `innerHTML` without the app's own `escapeHtml()` -
  the same stored-XSS pattern already fixed once in `create_week.js`.

- **Authelia-based authentication.** This app no longer has its own login/
  registration/password (see `services/auth.py` module docstring) - it
  runs behind Authelia as a forward-auth check in front of the reverse
  proxy (SWAG/nginx on the home server), which attaches the authenticated
  identity to every request via `Remote-Email`/`Remote-Name` headers.
  `current_user()` auto-provisions a `User` row the first time a given
  email is seen and keeps the display name in sync on every request.
  `User.password_hash` was dropped entirely (`migrations.py:
  _migrate_drop_user_password_hash_column()`). This retires two of the
  three items previously listed below under "waiting on real email
  delivery" - password reset and email verification are now Authelia's
  problem, not this app's.

## Waiting on real email delivery

Everything here only becomes worth implementing once `services/mail.py`
actually sends emails instead of just logging them (see the docstring
there - no SMTP credentials in place yet).

1. **Notification on plan invite.** Currently an invited user only
   notices a share if they check `/manage/sharing` themselves - the
   actual invite email (`send_invite_email()`) is only logged and
   additionally shown as a copyable link on the sharing page (see
   `templates/sharing.html`: "Pending invites").
