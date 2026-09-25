/**
 * Plan page core: shared state, day cards, main dish actions, day swapping
 * and the recipe detail window. plan-manual-select.js, plan-sides.js and
 * plan-shopping.js build on this state; all are classic scripts sharing
 * the global scope, and only the DOMContentLoaded handler calls across
 * files, so load order doesn't matter.
 *
 * Changes are sent to the server first; local state and DOM only update
 * after a successful response (no optimistic updates, except servings).
 */

// Index = day of the week (0 = Friday). dayDates never changes: a day swap
// swaps the contents at two indices, not the dates.
const dayLabels = window.PLAN_DATA.dayLabels;
const dayDates = window.PLAN_DATA.weekDates;

// Slim list of all visible recipes for the manual-selection search.
const allRecipes = window.PLAN_DATA.allRecipes || [];

// excluded and cooked move with the dish on a swap; servings belong to the
// weekday and stay.
let dayExcluded = window.PLAN_DATA.excludedDays;
let dayServings = window.PLAN_DATA.servingsList;
let dayCooked = window.PLAN_DATA.cookedMain;

// The source of truth for everything computed client-side (nutrition,
// shopping list); updated after every successful server change.
let weeklyPlanRecipes = window.PLAN_DATA.plan;

// A list of side dishes per day. Each carries side_id (the PlanDaySide id,
// used to address that slot) and its own cooked flag.
let weeklySideRecipes = window.PLAN_DATA.sidePlan;

// Manual shopping-list items for the whole week (not per day).
let weeklyExtraItems = window.PLAN_DATA.extraItems || [];

// Read-only dishes of the user's other plans; tied to the date, so they
// never move on a swap.
let otherPlanMeals = window.PLAN_DATA.otherPlanMeals || [[], [], [], [], [], [], []];

// The server renders empty card shells; everything is built here. Both
// functions are no-ops when the week has no plan yet.
document.addEventListener('DOMContentLoaded', () => {
    for (let i = 0; i < 7; i++) {
        refreshDayCard(i);
    }
    rebuildShoppingList();
    openRecipeDetailFromQueryParam();
});

/** ?open_day=<date> (from the home summary) opens that day's dish details. */
function openRecipeDetailFromQueryParam() {
    const openDay = new URLSearchParams(window.location.search).get('open_day');
    if (!openDay) return;
    const dayIndex = dayDates.indexOf(openDay);
    if (dayIndex === -1 || !weeklyPlanRecipes[dayIndex]) return;
    openRecipeDetail(dayIndex, null);
}

/** fetch() POST with the CSRF header; also used by the companion files. */
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

function rerollSingleDay(dayIndex) {
    const dayCard = document.getElementById(`day-card-${dayIndex}`);
    if (!dayCard) return;

    postWithCsrf(`/day/${dayDates[dayIndex]}/reroll-main`)
    .then(response => {
        if (!response.ok) return response.json().then(data => { throw new Error(data.error || window.I18N.no_alternative_recipe_available); });
        return response.json();
    })
    .then(newRecipe => {
        weeklyPlanRecipes[dayIndex] = newRecipe;
        dayCooked[dayIndex] = false;
        refreshDayCard(dayIndex);
        rebuildShoppingList();
    })
    .catch(err => {
        alert(window.I18N.note_prefix + ' ' + err.message);
    });
}

/**
 * The main dish area of a day card: the dish with its action buttons, or a
 * placeholder (excluded / nothing found) that still offers manual
 * selection and the exclude toggle.
 */
function renderMainDisplay(dayIndex) {
    const servingsHtml = renderServingsHtml(dayIndex);

    const recipe = weeklyPlanRecipes[dayIndex];
    if (recipe) {
        const cookedClass = dayCooked[dayIndex] ? ' dish-cooked' : '';
        return `
            <div class="d-flex justify-content-between align-items-start mb-2">
                <div class="dish-clickable${cookedClass}" role="button" title="${escapeHtml(window.I18N.show_details_title)}" onclick="openRecipeDetail(${dayIndex}, null)">
                    <h5 class="text-success fw-bold mb-0" style="color: var(--primary-food) !important;">${dayLabels[dayIndex]}</h5>
                    <span class="recipe-name fw-bold fs-5 text-dark d-block mt-1">${escapeHtml(recipe.name)}</span>
                </div>
                <div class="text-end">
                    ${servingsHtml}
                    <div class="d-flex align-items-center gap-1 justify-content-end mt-1">
                        <span class="badge badge-category recipe-category px-3 py-2 rounded-pill">${escapeHtml(recipe.category_name)}</span>
                        <button type="button" class="btn btn-sm btn-outline-secondary border-0 p-2 fs-5" title="${escapeHtml(window.I18N.reroll_this_day_title)}" onclick="rerollSingleDay(${dayIndex})">🎲</button>
                        <button type="button" class="btn btn-sm btn-outline-secondary border-0 p-2 fs-5" title="${escapeHtml(window.I18N.select_different_recipe_title)}" onclick="openMainManualSelect(${dayIndex})">✏️</button>
                        <button type="button" class="btn btn-sm btn-outline-secondary border-0 p-2 fs-5" title="${escapeHtml(window.I18N.exclude_day_title)}" onclick="toggleDayExclusion(${dayIndex})">🚫</button>
                    </div>
                </div>
            </div>
            <div class="text-muted small font-monospace bg-light p-2 rounded dish-clickable${cookedClass}" role="button" title="${escapeHtml(window.I18N.show_details_title)}" onclick="openRecipeDetail(${dayIndex}, null)">
                📊 <span class="recipe-kcal">${recipe.calories}</span> kcal |
                P: <span class="recipe-protein">${recipe.protein}</span>g |
                C: <span class="recipe-carbs">${recipe.carbs}</span>g |
                F: <span class="recipe-fat">${recipe.fat}</span>g
            </div>
        `;
    }
    const placeholderText = dayExcluded[dayIndex] ? window.I18N.excluded_from_planning : window.I18N.no_matching_recipe_available;
    const excludeBtnClass = dayExcluded[dayIndex] ? 'btn-danger' : 'btn-outline-secondary';
    const excludeBtnTitle = dayExcluded[dayIndex] ? window.I18N.include_day_title : window.I18N.exclude_day_title;
    return `
        <div class="d-flex justify-content-end mb-1">${servingsHtml}</div>
        <div class="text-center text-muted">
            <h5 class="fw-bold mb-1">${dayLabels[dayIndex]}</h5>
            <span>${escapeHtml(placeholderText)}</span>
            <div class="mt-1 d-flex gap-1 justify-content-center">
                <button type="button" class="btn btn-sm btn-outline-secondary" onclick="openMainManualSelect(${dayIndex})">${escapeHtml(window.I18N.select_recipe_label)}</button>
                <button type="button" class="btn btn-sm ${excludeBtnClass}" title="${escapeHtml(excludeBtnTitle)}" onclick="toggleDayExclusion(${dayIndex})">🚫</button>
            </div>
        </div>
    `;
}

/** Excluding also clears the main dish (taken from the server's answer). */
function toggleDayExclusion(dayIndex) {
    postWithCsrf(`/day/${dayDates[dayIndex]}/toggle-exclude`)
    .then(response => {
        if (!response.ok) throw new Error(window.I18N.could_not_be_saved);
        return response.json();
    })
    .then(data => {
        dayExcluded[dayIndex] = data.excluded;
        if (data.excluded) {
            weeklyPlanRecipes[dayIndex] = null;
            dayCooked[dayIndex] = false;
        }
        refreshDayCard(dayIndex);
        rebuildShoppingList();
    })
    .catch(err => {
        alert(window.I18N.note_prefix + ' ' + err.message);
    });
}

function renderServingsHtml(dayIndex) {
    return `
        <div class="d-flex align-items-center justify-content-end gap-1">
            <label class="small text-muted mb-0" for="servings-${dayIndex}">${escapeHtml(window.I18N.servings_label)}</label>
            <input type="number" id="servings-${dayIndex}" class="form-control form-control-sm servings-input" style="width: 60px;" min="1" step="1" value="${dayServings[dayIndex]}" onchange="updateDayServings(${dayIndex}, this.value)">
        </div>
    `;
}

/** Swaps the main dish display for the search box; Cancel restores it. */
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

/** A manual pick also un-excludes the day (server does the same). */
function setMainRecipe(dayIndex, recipeId) {
    postWithCsrf(`/day/${dayDates[dayIndex]}/set-main`, {
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ recipe_id: recipeId }),
    })
    .then(response => {
        if (!response.ok) return response.json().then(data => { throw new Error(data.error || window.I18N.selection_failed); });
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
        alert(window.I18N.note_prefix + ' ' + err.message);
    });
}

/** Full card content, built only from state (never read back from the DOM). */
function renderDayCardBody(dayIndex) {
    const mainDisplayHtml = `<div class="main-dish-display" id="main-dish-display-${dayIndex}">${renderMainDisplay(dayIndex)}</div>`;
    const sidesHtml = `<div class="side-dish-row mt-2 pt-2 border-top" id="side-row-${dayIndex}">${renderSidesSection(dayIndex)}</div>`;
    const otherPlansHtml = renderOtherPlanMeals(dayIndex);

    return mainDisplayHtml + sidesHtml + otherPlansHtml;
}

/** Read-only row with the user's other plans' dishes for this day. */
function renderOtherPlanMeals(dayIndex) {
    const meals = otherPlanMeals[dayIndex] || [];
    if (meals.length === 0) return '';

    const rows = meals.map(meal => `
        <div class="small text-muted d-flex align-items-center gap-2">
            <span class="badge bg-light text-dark border">${escapeHtml(meal.planName)}</span>
            <span>${escapeHtml(meal.recipeName)}</span>
        </div>
    `).join('');
    return `<div class="other-plan-meals mt-2 pt-2 border-top">${rows}</div>`;
}

/** Optimistic: updates the shopping list right away and only reports a
 * failed save, without resetting the typed value. */
function updateDayServings(dayIndex, value) {
    const n = parseInt(value);
    const servings = (isNaN(n) || n < 1) ? 1 : n;
    dayServings[dayIndex] = servings;
    rebuildShoppingList();

    postWithCsrf(`/day/${dayDates[dayIndex]}/servings`, {
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ servings: servings })
    }).catch(() => {
        alert(window.I18N.note_prefix + ' ' + window.I18N.could_not_save_servings);
    });
}

function refreshDayCard(dayIndex) {
    const card = document.getElementById(`day-card-${dayIndex}`);
    if (!card) return;

    const recipe = weeklyPlanRecipes[dayIndex];
    card.setAttribute('data-recipe-id', recipe ? recipe.id : '');
    card.setAttribute('data-category-id', recipe ? recipe.category_id : '');
    card.innerHTML = renderDayCardBody(dayIndex);
}

// --- Drag and drop ---
// Dragging a whole day card swaps two days (main dish, sides, excluded,
// cooked); dragging a single side row (plan-sides.js) moves just that side.
// The browser drags the innermost draggable element, so the two don't
// conflict. The payload is JSON: {type: 'day'|'side', ...}.

function dayCardDragStart(event) {
    const dayIndex = parseInt(event.currentTarget.getAttribute('data-day-index'));
    event.dataTransfer.setData('text/plain', JSON.stringify({ type: 'day', dayIndex: dayIndex }));
}

/** preventDefault is required, or the browser ignores the drop. */
function dayCardAllowDrop(event) {
    event.preventDefault();
    event.currentTarget.classList.add('drag-over');
}

/** Shared drop handler; payloads from outside the page are ignored. */
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

function daySwap(i, j) {
    if (i === j) return;

    postWithCsrf(`/day/${dayDates[i]}/swap/${dayDates[j]}`)
    .then(response => {
        if (!response.ok) throw new Error(window.I18N.swap_failed);
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
        alert(window.I18N.note_prefix + ' ' + err.message);
    });
}

// Week jump: a dd.mm.yyyy text field that opens the hidden native date
// picker (whose own display format depends on the browser language).
(function() {
    const display = document.getElementById('weekDateDisplay');
    const picker = document.getElementById('weekDatePicker');
    if (!display || !picker) return;

    display.addEventListener('click', () => {
        if (picker.showPicker) {
            picker.showPicker();
        } else {
            picker.focus();
        }
    });

    picker.addEventListener('change', () => {
        if (picker.value) {
            location.href = '/plan/' + picker.value + '?plan_id=' + window.PLAN_DATA.planId;
        }
    });
})();

// --- Recipe detail window ---
// One reused modal, filled from the recipe objects already in memory.

// Which dish the open window belongs to, for toggleDetailCooked().
let detailDayIndex = null;
let detailSideId = null;

/** Use for every user-provided string that goes into innerHTML. */
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text ?? '';
    return div.innerHTML;
}

/** sideId null = the day's main dish. */
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

/** Ingredient amounts are scaled to the day's servings like on the shopping
 * list; nutrition stays per serving. */
function renderRecipeDetailBody(recipe, targetServings) {
    const factor = recipe.servings ? targetServings / recipe.servings : 1;
    const ingredientsHtml = recipe.ingredients.length
        ? `<ul class="mb-0 ps-3">${recipe.ingredients.map(ing =>
            `<li>${escapeHtml(roundedAmount({ amount: ing.amount * factor }))} ${escapeHtml(ing.unit)} ${escapeHtml(ing.name)}</li>`
          ).join('')}</ul>`
        : `<span class="text-muted">${escapeHtml(window.I18N.no_ingredients_on_file)}</span>`;

    const instructionsHtml = recipe.instructions
        ? `<h6 class="fw-bold text-dark mt-3 mb-1">${escapeHtml(window.I18N.instructions_heading)}</h6><p class="mb-0" style="white-space: pre-line;">${escapeHtml(recipe.instructions)}</p>`
        : '';

    const sourceHtml = recipe.source_url
        ? `<a href="${escapeHtml(recipe.source_url)}" target="_blank" rel="noopener noreferrer" class="badge bg-light text-dark border px-2 py-1 text-decoration-none mt-2 d-inline-block">${escapeHtml(window.I18N.open_source_link)}</a>`
        : '';

    return `
        <div class="d-flex flex-wrap gap-2 align-items-center mb-3">
            <span class="badge badge-category px-3 py-2 rounded-pill">${escapeHtml(recipe.category_name)}</span>
            <span class="text-muted small">👥 ${targetServings} ${escapeHtml(window.I18N.servings_word)}</span>
        </div>
        <div class="text-muted small font-monospace bg-light p-2 rounded mb-3">
            📊 ${recipe.calories} kcal | P: ${recipe.protein}g | C: ${recipe.carbs}g | F: ${recipe.fat}g <span class="text-muted">${escapeHtml(window.I18N.per_serving)}</span>
        </div>
        <h6 class="fw-bold text-dark mb-1">🛒 ${escapeHtml(window.I18N.ingredients_word)}</h6>
        ${ingredientsHtml}
        ${instructionsHtml}
        ${sourceHtml}
    `;
}

/** Saves the cooked checkbox; the window stays open. */
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
        if (!response.ok) throw new Error(window.I18N.could_not_be_saved);
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
        alert(window.I18N.note_prefix + ' ' + err.message);
        document.getElementById('recipeDetailCookedCheckbox').checked = !cooked;
    });
}
