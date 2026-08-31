/**
 * plan.js - Core of the plan page (templates/plan.html): global state,
 * day-card construction (including the initial build when the page loads -
 * Jinja now only delivers empty card shells), rolling or manually picking
 * the main dish, changing the number of servings, and the complete
 * day-swap via drag-and-drop.
 *
 * This file is the "base" that three companion files build on (they use
 * its global state variables/functions, see below) - together they
 * replace the formerly single plan.js, which had grown to over 1000
 * lines:
 * - static/plan-manual-select.js: the reusable recipe-search box used
 *   both here (main dish) and in plan-sides.js (side dishes).
 * - static/plan-sides.js: everything related to side dishes (any number
 *   per day, add/roll/select/remove/move).
 * - static/plan-shopping.js: weekly nutrition overview, shopping list,
 *   manual shopping-list items.
 *
 * Since all four files are classic <script> tags (not loaded as
 * type="module"), they share the same global scope - the order in which
 * they're loaded in plan.html doesn't matter for correctness: none of
 * these files CALLS functions from another one while loading itself
 * (only the DOMContentLoaded handler below does that, and it only fires
 * after all scripts have fully loaded).
 *
 * Every action that changes the plan first sends a fetch() request to
 * the server (see routes/plan/), which persists the change in the
 * database - only once the response succeeds is the local JavaScript
 * state and the DOM updated. A failure (e.g. "no alternative available")
 * does NOT lead to an optimistic UI change that then gets rolled back,
 * but to an alert() and nothing else - the previous state remains
 * visible unchanged.
 *
 * Expects that window.PLAN_DATA (see plan.html, produced safely from
 * Python data via Jinja's tojson filter) has been set in the DOM BEFORE
 * this script.
 */

// Weekday labels ("Monday", "Tuesday", ...) and the corresponding ISO
// date strings (e.g. "2026-08-31") - both arrays are linked to each
// other and to the other arrays below via their index (0 = first day of
// the week) and no longer change after the initial load (only their
// content at the respective indices does, via dayServings/
// weeklyPlanRecipes/... - a day swap e.g. does NOT swap dayDates, but
// swaps the recipes at the existing date indices). dayDates is also used
// by the companion files (plan-sides.js, plan-shopping.js) for their
// own fetch() URLs.
const dayLabels = window.PLAN_DATA.dayLabels;
const dayDates = window.PLAN_DATA.weekDates;

// ALL recipes (independent of the current plan) in a lean form
// ({id, name, category_name, is_side_dish}) - the basis for the manual
// recipe-selection search (see static/plan-manual-select.js). Doesn't
// change after the page loads; a newly created recipe only shows up
// there after a reload.
const allRecipes = window.PLAN_DATA.allRecipes || [];

// Whether a day was deliberately excluded from automatic planning
// (checkbox on the create page). Gets swapped along with a day swap,
// since an "excluded day" is a property of the calendar day (e.g. "we
// always eat out on Tuesdays"), not of the dish that happened to land
// there.
let dayExcluded = window.PLAN_DATA.excludedDays;

// How many people to shop for on each weekday (index = weekday,
// pre-filled from the database). Stays bound to the weekday, not to the
// dish - so it does NOT move along with a day swap.
let dayServings = window.PLAN_DATA.servingsList;

// Whether a day's main dish has already been marked as cooked
// (index = weekday) - controls the "graying out" of the day card (see
// renderMainDisplay) and the pre-filled checkbox in the recipe detail
// window (see openRecipeDetail). Side dishes carry their own cooked
// field directly on the recipe object in weeklySideRecipes (see
// jsonify_side in services/planning.py), so they don't need a
// separate parallel array.
let dayCooked = window.PLAN_DATA.cookedMain;

// Recipes in JavaScript memory (index = weekday, null = no recipe).
// This is the "source of truth" for everything computed client-side
// from the plan (nutrition totals, shopping list, see
// static/plan-shopping.js) - after every successful server-side change
// this array is updated so these computations stay consistent without
// a page reload.
let weeklyPlanRecipes = window.PLAN_DATA.plan;

// Extra dishes/side dishes (index = weekday, value = LIST of recipe
// objects - a day can have any number of side dishes at once, see
// models.py: PlanDaySide). In addition to the normal recipe fields,
// each side-dish object has a side_id field: the ID of the
// PlanDaySide row itself (NOT of the recipe), used to specifically
// re-roll/replace/remove/move a single side dish - see
// static/plan-sides.js.
let weeklySideRecipes = window.PLAN_DATA.sidePlan;

// Items manually added to this week's shopping list that don't belong
// to any recipe (e.g. toiletries) - each entry is an object
// {id, name, amount, unit, category} and has already been persisted
// server-side (see routes/plan/shopping.py: add_shopping_item). Unlike
// weeklyPlanRecipes/weeklySideRecipes, NOT indexed by weekday, but a
// flat list - a manual item belongs to the week as a whole, not to any
// particular day. Managed in static/plan-shopping.js.
let weeklyExtraItems = window.PLAN_DATA.extraItems || [];

// Main dishes of the USER'S OTHER plans (index = weekday, value = LIST
// of {planId, planName, recipeId, recipeName}) - purely informational,
// see renderOtherPlanMeals() further below. Bound to this day's fixed
// calendar date, not to weeklyPlanRecipes[dayIndex] - so it NEVER
// changes on a day swap (daySwap only swaps weeklyPlanRecipes/
// weeklySideRecipes between two indices; this array is left untouched).
let otherPlanMeals = window.PLAN_DATA.otherPlanMeals || [[], [], [], [], [], [], []];

// On the first page load, build all 7 day cards (see renderDayCardBody
// further below - Jinja now only delivers empty card shells in
// plan.html) as well as the shopping list (and via that, the weekly
// nutrition overview, see static/plan-shopping.js: rebuildShoppingList)
// from the data already delivered by the server - from then on, each
// individual action takes over recomputing things on every change.
// refreshDayCard/rebuildShoppingList themselves bail out early if the
// respective containers don't exist in the DOM at all (e.g. because
// this week doesn't have a plan yet) - so this call is safe in that
// case too.
document.addEventListener('DOMContentLoaded', () => {
    for (let i = 0; i < 7; i++) {
        refreshDayCard(i);
    }
    rebuildShoppingList();
});

/**
 * Performs a POST fetch() request and automatically adds the
 * X-CSRFToken header (from window.CSRF_TOKEN, see base.html) - all
 * write endpoints are protected server-side via Flask-WTF CSRFProtect
 * (see app.py) and reject POSTs without a valid token. Additional
 * fetch() options (e.g. a JSON body with its own Content-Type header)
 * can be added via extraOptions, without having to write out the CSRF
 * header by hand each time. Also used by the plan-*.js companion files
 * for their own fetch() calls.
 */
function postWithCsrf(url, extraOptions = {}) {
    return fetch(url, {
        method: 'POST',
        ...extraOptions,
        headers: {
            'X-CSRFToken': window.CSRF_TOKEN,
            ...(extraOptions.headers || {}),
        },
    });
}

/**
 * Re-rolls the main dish of a single day (calls
 * routes/plan/day_actions.py: reroll_day() server-side, which picks a
 * random alternative from the same category that doesn't already
 * appear elsewhere this week or on category-neighboring days). On
 * success, both the day card in the DOM (via refreshDayCard - a
 * newly-rolled dish is automatically no longer "cooked" server-side,
 * see reroll_day() there, and that must be reflected in the card's
 * grayed-out state too) and the local weeklyPlanRecipes state plus the
 * shopping list are updated; on failure (no alternative available)
 * everything stays unchanged and the user gets an error message.
 */
function rerollSingleDay(dayIndex) {
    const dayCard = document.getElementById(`day-card-${dayIndex}`);
    if (!dayCard) return;

    postWithCsrf(`/day/${dayDates[dayIndex]}/reroll-main`)
    .then(response => {
        if (!response.ok) return response.json().then(data => { throw new Error(data.error || 'No alternative recipe available.'); });
        return response.json();
    })
    .then(newRecipe => {
        weeklyPlanRecipes[dayIndex] = newRecipe;
        dayCooked[dayIndex] = false;
        refreshDayCard(dayIndex);
        rebuildShoppingList();
    })
    .catch(err => {
        alert('Note: ' + err.message);
    });
}

/**
 * Builds the main-dish display area of a day card: either the assigned
 * recipe with 🎲 (re-roll) + ✏️ (manually select), or placeholder text
 * (excluded, or no matching recipe found) with its own "Select recipe"
 * button - manual selection stays reachable even when automatic
 * planning found nothing for this day or the day was excluded (the
 * selection automatically lifts an exclusion, see
 * routes/plan/day_actions.py: set_main_day).
 */
function renderMainDisplay(dayIndex) {
    // Top right next to the dish instead of its own full-width row (see
    // renderServingsHtml() further below for the reason) - this way
    // date/dish name keep starting at the very top left, without the
    // number of servings ending up between the nutrition row and the
    // side dishes instead.
    const servingsHtml = renderServingsHtml(dayIndex);

    const recipe = weeklyPlanRecipes[dayIndex];
    if (recipe) {
        const cookedClass = dayCooked[dayIndex] ? ' dish-cooked' : '';
        return `
            <div class="d-flex justify-content-between align-items-start mb-2">
                <div class="dish-clickable${cookedClass}" role="button" title="Show details" onclick="openRecipeDetail(${dayIndex}, null)">
                    <h5 class="text-success fw-bold mb-0" style="color: var(--primary-food) !important;">${dayLabels[dayIndex]}</h5>
                    <span class="recipe-name fw-bold fs-5 text-dark d-block mt-1">${recipe.name}</span>
                </div>
                <div class="text-end">
                    ${servingsHtml}
                    <div class="d-flex align-items-center gap-1 justify-content-end mt-1">
                        <span class="badge badge-category recipe-category px-3 py-2 rounded-pill">${recipe.category_name}</span>
                        <button type="button" class="btn btn-sm btn-outline-secondary border-0 p-2 fs-5" title="Re-roll this day" onclick="rerollSingleDay(${dayIndex})">🎲</button>
                        <button type="button" class="btn btn-sm btn-outline-secondary border-0 p-2 fs-5" title="Select a different recipe" onclick="openMainManualSelect(${dayIndex})">✏️</button>
                    </div>
                </div>
            </div>
            <div class="text-muted small font-monospace bg-light p-2 rounded dish-clickable${cookedClass}" role="button" title="Show details" onclick="openRecipeDetail(${dayIndex}, null)">
                📊 <span class="recipe-kcal">${recipe.calories}</span> kcal |
                P: <span class="recipe-protein">${recipe.protein}</span>g |
                C: <span class="recipe-carbs">${recipe.carbs}</span>g |
                F: <span class="recipe-fat">${recipe.fat}</span>g
            </div>
        `;
    }
    // Two possible reasons for an empty main dish: the day was
    // deliberately excluded (checkbox), or automatic planning simply
    // found no matching recipe (e.g. category exhausted) - both cases
    // get their own, distinguishable hint text instead of an
    // uninformatively empty card.
    const placeholderText = dayExcluded[dayIndex] ? '🚫 Excluded from planning' : 'No matching recipe available';
    return `
        <div class="d-flex justify-content-end mb-1">${servingsHtml}</div>
        <div class="text-center text-muted">
            <h5 class="fw-bold mb-1">${dayLabels[dayIndex]}</h5>
            <span>${placeholderText}</span>
            <div class="mt-1">
                <button type="button" class="btn btn-sm btn-outline-secondary" onclick="openMainManualSelect(${dayIndex})">✏️ Select recipe</button>
            </div>
        </div>
    `;
}

/** Servings input field for a day card - its own function instead of a
 * fixed HTML block in renderDayCardBody, since it's now embedded
 * directly in renderMainDisplay() (see the comment there), but looks
 * identical for BOTH branches (recipe present/placeholder). */
function renderServingsHtml(dayIndex) {
    return `
        <div class="d-flex align-items-center justify-content-end gap-1">
            <label class="small text-muted mb-0" for="servings-${dayIndex}">👥 Servings</label>
            <input type="number" id="servings-${dayIndex}" class="form-control form-control-sm servings-input" style="width: 60px;" min="1" step="1" value="${dayServings[dayIndex]}" onchange="updateDayServings(${dayIndex}, this.value)">
        </div>
    `;
}

/**
 * Opens the manual recipe-selection box (see
 * static/plan-manual-select.js) in place of the current main-dish
 * display (main-dish-display-<dayIndex>, see renderDayCardBody).
 * previousHtml is remembered so that "Cancel" can restore exactly the
 * previous state, without needing an extra server round-trip.
 */
function openMainManualSelect(dayIndex) {
    const area = document.getElementById(`main-dish-display-${dayIndex}`);
    if (!area) return;
    const previousHtml = area.innerHTML;
    area.innerHTML = buildManualSelectHtml(false);
    wireManualSelectBox(
        area, false,
        (recipeId) => setMainRecipe(dayIndex, recipeId),
        () => { area.innerHTML = previousHtml; }
    );
}

/**
 * Sets a day's main dish to a recipe manually chosen by the user (calls
 * routes/plan/day_actions.py: set_main_day() server-side - NONE of
 * rerollSingleDay's balance/neighbor/repeat rules apply here, see its
 * docstring). Also resets dayExcluded locally, since a manual
 * assignment automatically lifts the exclusion server-side.
 */
function setMainRecipe(dayIndex, recipeId) {
    postWithCsrf(`/day/${dayDates[dayIndex]}/set-main`, {
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ recipe_id: recipeId }),
    })
    .then(response => {
        if (!response.ok) return response.json().then(data => { throw new Error(data.error || 'Selection failed.'); });
        return response.json();
    })
    .then(newRecipe => {
        weeklyPlanRecipes[dayIndex] = newRecipe;
        dayExcluded[dayIndex] = false;
        dayCooked[dayIndex] = false;
        refreshDayCard(dayIndex);
        rebuildShoppingList();
    })
    .catch(err => {
        alert('Note: ' + err.message);
    });
}

/**
 * Builds the complete inner area of a day card: the main-dish display
 * area (in its own main-dish-display-<i> div, which openMainManualSelect
 * specifically replaces - also contains the servings input, see
 * renderMainDisplay) and the side-dish area (renderSidesSection, see
 * static/plan-sides.js). Reads exclusively from the current JavaScript
 * state (weeklyPlanRecipes/weeklySideRecipes/dayServings/dayExcluded),
 * not from the DOM - called completely fresh for both days involved
 * after a day swap, instead of updating individual DOM nodes
 * selectively, because potentially every field changes in a swap.
 */
function renderDayCardBody(dayIndex) {
    // The servings input is part of renderMainDisplay() itself (top
    // right next to the dish) instead of its own row here - this way
    // date/dish name start at the very top left of the card, without
    // the number of servings ending up between the nutrition row and
    // the side dishes (see the comment there).
    const mainDisplayHtml = `<div class="main-dish-display" id="main-dish-display-${dayIndex}">${renderMainDisplay(dayIndex)}</div>`;
    const sidesHtml = `<div class="side-dish-row mt-2 pt-2 border-top" id="side-row-${dayIndex}">${renderSidesSection(dayIndex)}</div>`;
    const otherPlansHtml = renderOtherPlanMeals(dayIndex);

    return mainDisplayHtml + sidesHtml + otherPlansHtml;
}

/**
 * Purely read-only extra row below the side dishes: what's being cooked
 * on this day in the USER'S OTHER plans (see otherPlanMeals above,
 * routes/plan/pages.py: week_view()) - one badge with the plan name plus
 * the dish name per entry, WITHOUT roll/edit/drag/cooked-toggle (the
 * active plan's main dish above remains the card's only interactive
 * spot). Returns an empty string for this day if no other plan has a
 * dish on that day - the tile then stays exactly as it was before this
 * function ran.
 */
function renderOtherPlanMeals(dayIndex) {
    const meals = otherPlanMeals[dayIndex] || [];
    if (meals.length === 0) return '';

    const rows = meals.map(meal => `
        <div class="small text-muted d-flex align-items-center gap-2">
            <span class="badge bg-light text-dark border">${meal.planName}</span>
            <span>${meal.recipeName}</span>
        </div>
    `).join('');
    return `<div class="other-plan-meals mt-2 pt-2 border-top">${rows}</div>`;
}

/**
 * Applies a changed servings count for a weekday immediately to the
 * local display (optimistic, for a snappy feel while typing) and sends
 * it to the server in parallel for permanent storage. Unlike the
 * roll/swap actions, this does NOT wait for the server response before
 * the UI reacts - a failure only results in a subsequent error message,
 * but the input value stays as entered (rolling back the number in the
 * input field would be more confusing for the user than a brief error
 * message for a rare network failure).
 */
function updateDayServings(dayIndex, value) {
    const n = parseInt(value);
    const servings = (isNaN(n) || n < 1) ? 1 : n;
    dayServings[dayIndex] = servings;
    rebuildShoppingList();

    postWithCsrf(`/day/${dayDates[dayIndex]}/servings`, {
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ servings: servings })
    }).catch(() => {
        alert('Note: Could not save number of servings.');
    });
}

/**
 * Rewrites the data-* attributes and the complete content of a day card
 * from the current JavaScript state (see renderDayCardBody). Called for
 * both affected days after a day swap, since potentially all fields
 * change at once there and selectively updating individual DOM nodes
 * (as rerollSingleDay does) would be needlessly error-prone here. Also
 * called for all 7 days on the initial page load (see DOMContentLoaded
 * above).
 */
function refreshDayCard(dayIndex) {
    const card = document.getElementById(`day-card-${dayIndex}`);
    if (!card) return;

    const recipe = weeklyPlanRecipes[dayIndex];
    card.setAttribute('data-recipe-id', recipe ? recipe.id : '');
    card.setAttribute('data-category-id', recipe ? recipe.category_id : '');
    card.innerHTML = renderDayCardBody(dayIndex);
}

// --- SWAP DAYS / MOVE SIDE DISHES VIA DRAG-AND-DROP ---
// Uses the native HTML5 drag-and-drop API. TWO different things can be
// dragged on this page, both ending at the same drop handler
// (dayCardDrop) on the day card:
//
// 1. The whole day card (draggable="true" on the outer
//    .recipe-day-card element, see plan.html) - swaps the main dish,
//    ALL side dishes, and exclusion status of two days completely with
//    each other (daySwap). "If the main dish moves, the side dishes
//    come along."
//
// 2. A single side-dish row (draggable="true" on .side-dish-card,
//    see static/plan-sides.js: renderSidesSection) - moves ONLY that
//    one side dish to the target day, without touching the rest of the
//    source or target day (moveSideDish, see static/plan-sides.js).
//
// Since a side-dish row is nested INSIDE a day card and both have
// draggable="true", the browser automatically picks the innermost
// draggable element under the cursor when dragging starts - so dragging
// from a side-dish row only drags it, not the whole card, with no
// conflict handling of our own needed. Which of the two cases applies
// is stored as a JSON-encoded {type: 'day'|'side', ...} object in the
// DataTransfer (see dayCardDragStart here and sideDragStart in
// static/plan-sides.js).

/** Remembers the index of a WHOLE day card in the DataTransfer when dragging starts. */
function dayCardDragStart(event) {
    const dayIndex = parseInt(event.currentTarget.getAttribute('data-day-index'));
    event.dataTransfer.setData('text/plain', JSON.stringify({ type: 'day', dayIndex: dayIndex }));
}

/** Allows dropping on this card (otherwise the browser ignores drop events by default) and highlights it visually. */
function dayCardAllowDrop(event) {
    event.preventDefault();
    event.currentTarget.classList.add('drag-over');
}

/**
 * Shared drop handler for both drag kinds (see explanation above):
 * reads the JSON-encoded payload from the DataTransfer and dispatches
 * to daySwap() (whole card, below) or moveSideDish() (a single side
 * dish, see static/plan-sides.js) depending on "type". Invalid/missing
 * payloads (e.g. a drag from outside this page) are silently ignored.
 */
function dayCardDrop(event) {
    event.preventDefault();
    const targetCard = event.currentTarget;
    targetCard.classList.remove('drag-over');

    const raw = event.dataTransfer.getData('text/plain');
    if (!raw) return;
    let payload;
    try {
        payload = JSON.parse(raw);
    } catch (e) {
        return;
    }

    const targetDayIndex = parseInt(targetCard.getAttribute('data-day-index'));

    if (payload.type === 'side') {
        moveSideDish(payload.dayIndex, payload.sideId, targetDayIndex);
    } else if (payload.type === 'day') {
        daySwap(payload.dayIndex, targetDayIndex);
    }
}

/**
 * Swaps two whole day cards completely with each other (calls
 * routes/plan/day_actions.py: swap_days() server-side) and only swaps
 * the three affected arrays (weeklyPlanRecipes, weeklySideRecipes,
 * dayExcluded) via destructuring swap after its confirmation, before
 * both cards are re-rendered.
 */
function daySwap(i, j) {
    if (i === j) return;

    postWithCsrf(`/day/${dayDates[i]}/swap/${dayDates[j]}`)
    .then(response => {
        if (!response.ok) throw new Error('Swap failed.');
        return response.json();
    })
    .then(() => {
        [weeklyPlanRecipes[i], weeklyPlanRecipes[j]] = [weeklyPlanRecipes[j], weeklyPlanRecipes[i]];
        [weeklySideRecipes[i], weeklySideRecipes[j]] = [weeklySideRecipes[j], weeklySideRecipes[i]];
        [dayExcluded[i], dayExcluded[j]] = [dayExcluded[j], dayExcluded[i]];
        [dayCooked[i], dayCooked[j]] = [dayCooked[j], dayCooked[i]];

        refreshDayCard(i);
        refreshDayCard(j);
        rebuildShoppingList();
    })
    .catch(err => {
        alert('Note: ' + err.message);
    });
}

// Date display/jump: a dedicated dd.mm.yyyy text field instead of the
// browser-localized <input type="date"> display text (which, in Chrome
// for instance, can show mm/dd/yyyy depending on system language). The
// native picker is kept for the calendar popup, but is invisible (see
// CSS in plan.html) and is opened programmatically (showPicker()) by
// clicking the visible text field. When the user picks a date in the
// popup, the change event navigates directly to the plan page of the
// week that date falls in.
(function() {
    const display = document.getElementById('weekDateDisplay');
    const picker = document.getElementById('weekDatePicker');
    if (!display || !picker) return;

    display.addEventListener('click', () => {
        if (picker.showPicker) {
            picker.showPicker();
        } else {
            // Fallback for browsers without showPicker() support: focus
            // the (invisible) native field so that at least keyboard
            // input/native operation remains possible.
            picker.focus();
        }
    });

    picker.addEventListener('change', () => {
        if (picker.value) {
            location.href = '/plan/' + picker.value;
        }
    });
})();

// --- RECIPE DETAIL WINDOW ---
// A single, reused modal (#recipeDetailModal, see plan.html) instead of
// one per dish: it always shows exactly ONE dish at a time, its content
// is refilled via JS every time it opens. Opened by clicking a main
// dish (dish-clickable in renderMainDisplay above) or a side dish
// (dish-clickable in static/plan-sides.js: renderSidesSection) - in
// both cases reads from the weeklyPlanRecipes/weeklySideRecipes objects
// already present in the frontend, no separate server round-trip needed
// (see services/planning.py: jsonify_recipe() docstring for the
// additional fields is_favorite/source_url/instructions delivered for
// exactly this purpose).

// Remembers which day/side dish the detail window is currently open
// for - toggleDetailCooked() below needs this to know where the
// checkbox change should be saved server-side, without every caller
// having to pass that through itself.
let detailDayIndex = null;
let detailSideId = null;

/** Escapes text for safe embedding in innerHTML (prevents, e.g., a
 * recipe name containing "<"/"&" from breaking the detail window's
 * markup or - since unlike renderMainDisplay/renderSidesSection this
 * also displays longer free text like the instructions - executing
 * referenced HTML). */
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text ?? '';
    return div.innerHTML;
}

/**
 * Opens the recipe detail window for a day's main dish (sideId null) or
 * a specific side dish (sideId set) - builds the complete, purely
 * read-only content from the recipe object already available and shows
 * the Bootstrap modal.
 */
function openRecipeDetail(dayIndex, sideId) {
    const recipe = sideId
        ? (weeklySideRecipes[dayIndex] || []).find(s => s.side_id === sideId)
        : weeklyPlanRecipes[dayIndex];
    if (!recipe) return;

    detailDayIndex = dayIndex;
    detailSideId = sideId;
    const cooked = sideId ? !!recipe.cooked : !!dayCooked[dayIndex];

    document.getElementById('recipeDetailTitle').textContent = (recipe.is_favorite ? '⭐ ' : '') + recipe.name;
    document.getElementById('recipeDetailEditLink').href = `/manage/recipe/edit/${recipe.id}`;
    document.getElementById('recipeDetailBody').innerHTML = renderRecipeDetailBody(recipe, dayServings[dayIndex]);

    const checkbox = document.getElementById('recipeDetailCookedCheckbox');
    checkbox.checked = cooked;
    checkbox.onchange = () => toggleDetailCooked(checkbox.checked);

    bootstrap.Modal.getOrCreateInstance(document.getElementById('recipeDetailModal')).show();
}

/** Builds the read-only content of the detail window (category/servings,
 * nutrition, ingredient list, instructions/source if present) from a
 * recipe object - deliberately a different, more compact presentation
 * than the create/edit form, showing everything at a glance instead of
 * individual form fields.
 *
 * targetServings is the number of servings set for THIS day
 * (dayServings[dayIndex], see openRecipeDetail) - ingredient amounts are
 * scaled to it (instead of showing the base amount laid out for
 * recipe.servings unchanged, as before), using exactly the same ratio
 * the shopping list uses (see static/plan-shopping.js:
 * rebuildShoppingList - roundedAmount() from there is reused here for
 * the same round-up-rather-than-truncate rounding). Nutrition values are
 * deliberately left untouched by this: they always apply PER SERVING,
 * regardless of the planned number of servings. */
function renderRecipeDetailBody(recipe, targetServings) {
    const factor = recipe.servings ? targetServings / recipe.servings : 1;
    const ingredientsHtml = recipe.ingredients.length
        ? `<ul class="mb-0 ps-3">${recipe.ingredients.map(ing =>
            `<li>${escapeHtml(roundedAmount({ amount: ing.amount * factor }))} ${escapeHtml(ing.unit)} ${escapeHtml(ing.name)}</li>`
          ).join('')}</ul>`
        : '<span class="text-muted">No ingredients on file.</span>';

    const instructionsHtml = recipe.instructions
        ? `<h6 class="fw-bold text-dark mt-3 mb-1">📝 Instructions</h6><p class="mb-0" style="white-space: pre-line;">${escapeHtml(recipe.instructions)}</p>`
        : '';

    const sourceHtml = recipe.source_url
        ? `<a href="${escapeHtml(recipe.source_url)}" target="_blank" rel="noopener noreferrer" class="badge bg-light text-dark border px-2 py-1 text-decoration-none mt-2 d-inline-block">🔗 Open source</a>`
        : '';

    return `
        <div class="d-flex flex-wrap gap-2 align-items-center mb-3">
            <span class="badge badge-category px-3 py-2 rounded-pill">${escapeHtml(recipe.category_name)}</span>
            <span class="text-muted small">👥 ${targetServings} servings</span>
        </div>
        <div class="text-muted small font-monospace bg-light p-2 rounded mb-3">
            📊 ${recipe.calories} kcal | P: ${recipe.protein}g | C: ${recipe.carbs}g | F: ${recipe.fat}g <span class="text-muted">(per serving)</span>
        </div>
        <h6 class="fw-bold text-dark mb-1">🛒 Ingredients</h6>
        ${ingredientsHtml}
        ${instructionsHtml}
        ${sourceHtml}
    `;
}

/**
 * Saves the changed "cooked" checkbox of the currently open detail
 * window server-side (routes/plan/day_actions.py: set_day_cooked()/
 * routes/plan/day_actions_sides.py: set_side_cooked()) and, on success, updates both the local state
 * (dayCooked, or the cooked field directly on the side-dish object) and
 * - via refreshDayCard()/refreshSidesSection() - the grayed-out state of
 * the affected day card, without closing the detail window for it.
 */
function toggleDetailCooked(cooked) {
    const dayIndex = detailDayIndex;
    const sideId = detailSideId;
    const url = sideId
        ? `/day/${dayDates[dayIndex]}/side/${sideId}/cooked`
        : `/day/${dayDates[dayIndex]}/cooked`;

    postWithCsrf(url, {
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ cooked: cooked }),
    })
    .then(response => {
        if (!response.ok) throw new Error('Could not be saved.');
        return response.json();
    })
    .then(data => {
        if (sideId) {
            const side = (weeklySideRecipes[dayIndex] || []).find(s => s.side_id === sideId);
            if (side) side.cooked = data.cooked;
            refreshSidesSection(dayIndex);
        } else {
            dayCooked[dayIndex] = data.cooked;
            refreshDayCard(dayIndex);
        }
    })
    .catch(err => {
        alert('Note: ' + err.message);
        // Reset the checkbox to its last known state, since the change
        // was not applied server-side.
        document.getElementById('recipeDetailCookedCheckbox').checked = !cooked;
    });
}
