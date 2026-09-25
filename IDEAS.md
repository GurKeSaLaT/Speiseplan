# Ideas

Open ideas and known gaps. Finished work goes to [CHANGELOG.md](CHANGELOG.md).

## Backlog

- **More import sites.** Any site that embeds schema.org `Recipe` JSON-LD
  can be added to `ALLOWED_HOSTS` in `services/recipe_import.py` after a
  live check. Not possible this way: kochbar.de (client-side rendering),
  ichkoche.at (no JSON-LD), springlane.de (marked as `Article`), KptnCook
  (app only).
- **Statistics.** The plan calendar keeps every past day, so views like
  "how often was this recipe/category planned" need no new data.

## Waiting on email delivery

`services/mail.py` only logs so far (no SMTP configured).

- **Invite notification.** Invitees currently only see a share on
  `/manage/sharing`; the invite link is shown there for copying.

## Known gaps

- **Some German constants stay untranslated** because they are compared
  against stored data or are parser vocabulary:
  `services/plans.py: DEFAULT_CATEGORIES`,
  `services/shopping.py: SHOPPING_CATEGORIES`, the unit
  words in `services/units.py`, and `services/seasons.py: SEASONS`/
  `SEASON_PRESETS`. Translating them needs a data migration for
  `Category.name`, `Ingredient.category`, `ExtraShoppingItem.category` and
  the season labels.
