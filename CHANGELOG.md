# Changelog

One line per change, newest first.

## 2026-10-13

- Swapping days or moving a side now checks follow-up dishes: one that
  ends up before the dish it is made from, or too many days after it,
  loses that coupling and looks for another fitting dish before it, like
  a follow-up you pick yourself. A follow-up dish moved onto a day where a
  fitting dish lies a few days before it is coupled to that one.
- A follow-up dish you pick yourself (as main dish or side, or as a fixed
  dish when creating a week) now finds the dish it is made from: the most
  recent one a few days before it (as set in the recipe) that isn't cooked
  yet and isn't in the past, even if that dish already feeds another
  follow-up. That dish is then bought for more servings: lines already
  ticked off stay ticked and only the extra amount shows up as a new
  open line. If there is no such dish, the follow-up stays a normal dish
  and all its ingredients are bought.
- Follow-up chains (e.g. roast -> ragout -> lasagne): a planned follow-up
  dish plans its own follow-up, whether it was placed by generating the
  week or picked by hand, and also while it still waits for its week:
  creating that week offers the waiting chain as fixed dishes and keeps
  it. A source dish is bought for its own servings plus the whole chain
  below it (lasagne 2, ragout 4, roast 6), waiting dishes included. Re-rolling, replacing,
  excluding or removing a dish releases every follow-up below it;
  replacing a dish in the middle also drops its own coupling.
- A side dish can be a source dish (e.g. boiled potatoes -> fried
  potatoes, rice -> fried rice): adding, rolling or replacing a side, or
  setting it as a fixed side when creating a week, plans one of its
  follow-ups (a main dish on a free day or an extra side), and the side is
  bought for the follow-up's servings too. Re-rolling, replacing or
  removing the side releases its follow-ups (a released main dish day gets
  a new dish), moving it keeps them. Side cards show where their
  follow-ups are planned.
- A follow-up dish can be a side dish (e.g. rice -> fried rice): the
  recipe form offers side dishes as follow-ups. When the source dish is
  planned, the side is added as an extra side on the earliest day of its
  window that isn't excluded, whatever main dish that day has; in a week
  not created yet it waits and is offered as a fixed side. The source dish
  is bought for the side's servings too and the side's pre-cooked
  ingredients are left off the shopping list. Re-rolling, replacing or
  removing the side drops the coupling, moving it keeps it; replacing the
  source removes the side. Rolling sides never draws a follow-up recipe.
- Recipe trees are linked into other plans only as a whole: adding or
  removing a plan for any recipe of a tree does it for all of them (a plan
  that owns one of them can't be removed). A follow-up link that joins two
  trees links the joined tree into every plan either was in; the recipe
  form names those plans and, with autosave, asks before saving. Removing
  a follow-up link keeps both parts in all their plans.
- Follow-up links form recipe trees: a follow-up recipe has only one
  source recipe and links never form a cycle. The recipe form only offers
  follow-up dishes that have no source yet and aren't above the recipe in
  its tree; a save that breaks this (also via links in plans you can't
  see, or a link to the recipe itself) is refused with a message naming
  the recipes. Re-saving a recipe that keeps a follow-up dish no longer
  fails.

## 2026-10-12

- Linked recipes: a recipe can list follow-up dishes with a day window
  (default 2-3 days later). When it is planned (pinned, rolled, re-rolled
  or picked), one follow-up goes on the earliest free day of its window,
  ahead of normal filling; without a free day the dish stays alone.
  Follow-ups are never rolled on their own. The source dish is bought and
  shown for both days' servings, and follow-up ingredients marked "from the
  previous dish" are left off the shopping list. Re-rolling or removing the
  source re-rolls its follow-up's day; re-rolling the follow-up just drops
  the link; links move with swapped dishes. A follow-up in a week that
  doesn't exist yet is offered as a fixed dish when that week is created.
- Amount placeholders in recipe instructions: `{Name}`, `{Name*0.5}`,
  `{Name*1/4}`, `{Name#2}` show that ingredient line's amount, scaled to
  the day's servings, in the plan's recipe window. Names match exactly,
  by unique prefix or by whole word; the recipe form inserts them by
  click and warns about ones that match no ingredient. A placeholder
  starting with a number is a literal amount that scales on its own:
  `{500 ml}` water, `{12}` dumplings, `{½ TL}` salt.
- Leftovers: the create-week page takes leftovers from last week
  (ingredient, optional amount). Dishes using them go on the earliest free
  days, and they are subtracted from the shopping list (no amount = the
  whole line). The plan page lists them with the dishes that use them.

## 2026-10-02

- Shopping list keeps what was already bought: a tick stores its amount.
  More needed later -> the bought part stays ticked and the rest shows up
  as an open line; less or nothing needed -> the line stays ticked.
- Ingredient aliases share one shopping-list category: the target
  ingredient's category wins, and setting an alias writes it into the
  plan's own recipes.
- Fix: weekday names, the weekly nutrition summary and the macro
  abbreviations were English in the German UI (`pybabel extract` missed
  `_l()` strings; now `-k _l`, documented, and a test catches gaps).
- Fix: day card header overflowed on phones (servings field and exclude
  button outside the card); it now stacks below 576 px.
- Fix: on phones the shopping list was its own scroll area, trapping the
  page scroll and jumping on rotation; that is now desktop-only.

## 2026-10-01

- Fix: list searches matched far too much - the subsequence match ran over
  all names joined together; now each query word must match within one
  name (substring, or a typo-tolerant match inside one word).
- Fix: changing an ingredient's nutrition or alias did not update the
  stored nutrition of recipes using it until the recipe was saved again.
- Fix: ticked-off shopping-list lines were lost on reload; they are now
  saved per plan and week.

## 2026-09-25

- Refactor: trimmed comments across the codebase, split long files (recipe
  route tests, plan detail window, ingredients page script), shared
  recipe-form parsing; README and IDEAS rewritten, this changelog added.
- Fix: plan and recipe names from other plans were inserted unescaped (XSS).
- Fix: a status text on the create-week page was not translated.
- Recipe form autosaves existing recipes; new recipes open in edit mode
  after the first save.
- Ingredients page autosaves every field and links names to their recipes.
- Ingredients page refreshes rows in place, keeping scroll position, tab,
  filter and focus.
- Orphaned ingredient aliases are removed automatically.
- Fix: ingredients page took 34 s with real data (per-name queries).
- Fix: main ingredient headings had no recipe link.
- Fix: alias remove button broke on every name (`tojson` in an attribute).

## 2026-09-24

- Ingredient aliases and nutrition merged into one page.
- Login and registration replaced by Authelia forward-auth headers.
- JS strings localized via `window.I18N`; two more XSS spots fixed.
- Days can be excluded after a week was created.
- Demo data moved from the committed database to `fixtures/demo_data.json`
  (`SEED_DEMO_DATA=1`); dynamic migration SQL guarded.
- Fix: XSS on the create-week page, crash on malformed numbers, dangling
  recipe references, Enter key on the shopping list form.

## 2026-09-23

- Plan weeks run Friday to Thursday.

## 2026-09-09

- Pantry items are marked per ingredient instead of derived from category.
- Fix: invited members could end up without a starred plan.

## 2026-08-31

- English/German localization with Flask-Babel, English as default.
- Home page shows a weekly summary across all plans; plan pages have their
  own URLs.
- Code split into packages (models, routes/recipes, day actions, week
  generation, migrations).
- Fix: recipe link field, plan switcher, password confirmation.

## 2026-08-30

- User accounts with multiple plans each, shared by email invite.
- Recipes and settings belong to a plan; recipes can be linked into others.
- Account page, rename and leave plans, delete account.
- Recipe list as uniform tiles; create form picks the starred plan.

## 2026-08-29

- Recipe form rewritten as one page for create and edit.
- Global sidebar layout replaces the top navbar.
- Recipe detail window on the plan page with "cooked" marker and scaled
  amounts.
- Nutrition computed from ingredients (per 100 g / 100 ml / 1 pc);
  calories derived from macros.
- Ingredient aliases for the shopping list, with inline hints in the form.
- Pantry list separate from the shopping list; spice category added.
- Unit normalization (mass to g, volume to ml) with display setting.
- Recipe import from chefkoch.de and eight more sites.
- Manual recipe picking and any number of side dishes per day.
- Light/dark mode.
- Fuzzy search on recipe and category lists.
- Test suite (pytest).
- Fix: ingredient row performance (no pre-rendered modals, no datalist).
- Fix: mobile layout, umlauts in imports.

## 2026-08-28

- Persistent plan calendar as the main page, with week navigation.
- Shopping list categories and manual items.
- Favorites and soft repetition weighting.
- Seasons per recipe (standard seasons or custom range).
- Servings per recipe and per day, scaling the shopping list.
- Weekly nutrition overview.
- Day swapping, side dishes without main dish, no category twice in a row.
- Fixed and excluded days when creating a week; side dishes as own slots.
- CSRF protection and security headers.
- Docker deployment.

## 2026-08-27

- First version: recipes, categories, random weekly plan, shopping list.
