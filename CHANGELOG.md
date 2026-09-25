# Changelog

One line per change, newest first.

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
