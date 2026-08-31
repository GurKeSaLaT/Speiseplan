/**
 * plan-sides.js - everything related to side dishes on the plan page
 * (templates/plan.html): rendering the side dish section of a day card,
 * adding new side dishes (rolled randomly or manually selected),
 * rerolling/manually replacing/removing an existing side dish, as well
 * as moving A SINGLE side dish via drag-and-drop to another day
 * (independent of the full day swap, which lives in static/plan.js).
 *
 * Uses shared infrastructure from the other plan-*.js files:
 * weeklySideRecipes/dayDates/postWithCsrf (see static/plan.js),
 * buildManualSelectHtml/wireManualSelectBox (see
 * static/plan-manual-select.js) and rebuildShoppingList (see
 * static/plan-shopping.js) - all three must be included BEFORE or AFTER
 * this file (the order of the <script> tags in plan.html doesn't matter
 * here, since this file only declares its functions but doesn't CALL any
 * of them immediately on load - only later user interactions do, by
 * which point all scripts are long since loaded).
 */

/**
 * Builds the complete side dish section of a day card: one row per
 * currently assigned side dish (each with its own drag handle for
 * moveSideDish plus 🎲/✏️/❌ buttons for exactly THIS slot) plus a final
 * "add side dish" row (🎲 rolls a new random side dish, ✏️ opens manual
 * selection for a NEW slot). Each row gets its own id (side-item-<dayIndex>-<sideId>
 * or side-add-row-<dayIndex>), which openSideManualSelect() uses to
 * replace exactly that one row with the selection box.
 */
function renderSidesSection(dayIndex) {
    const sides = weeklySideRecipes[dayIndex] || [];
    let html = '';
    sides.forEach(side => {
        const cookedClass = side.cooked ? ' dish-cooked' : '';
        html += `
            <div class="d-flex justify-content-between align-items-center side-dish-card mb-1"
                 id="side-item-${dayIndex}-${side.side_id}"
                 draggable="true"
                 ondragstart="sideDragStart(event, ${dayIndex}, ${side.side_id})">
                <div class="dish-clickable${cookedClass}" role="button" title="Show details" onclick="openRecipeDetail(${dayIndex}, ${side.side_id})">
                    <span class="fw-bold text-dark side-dish-name">🥗 ${side.name}</span>
                    <span class="badge badge-category side-dish-category ms-1">${side.category_name}</span>
                    <span class="text-muted small side-dish-kcal">(${side.calories} kcal)</span>
                </div>
                <div class="d-flex align-items-center gap-1">
                    <button type="button" class="btn btn-sm btn-outline-secondary border-0 p-1" title="Reroll this side dish" onclick="rerollOneSide(${dayIndex}, ${side.side_id})">🎲</button>
                    <button type="button" class="btn btn-sm btn-outline-secondary border-0 p-1" title="Choose a different side dish" onclick="openSideManualSelect(${dayIndex}, ${side.side_id})">✏️</button>
                    <button type="button" class="btn btn-sm text-danger border-0 p-1" title="Remove side dish" onclick="removeOneSide(${dayIndex}, ${side.side_id})">❌</button>
                </div>
            </div>
        `;
    });
    html += `
        <div id="side-add-row-${dayIndex}" class="d-flex gap-1">
            <button type="button" class="btn btn-sm btn-outline-secondary flex-grow-1" onclick="addRandomSide(${dayIndex})">🎲 Roll a side dish</button>
            <button type="button" class="btn btn-sm btn-outline-secondary" title="Choose a side dish" onclick="openSideManualSelect(${dayIndex}, null)">✏️</button>
        </div>
    `;
    return html;
}

/** Re-renders only the side dish section of a day card (side-row-<dayIndex>), without touching the servings row/main dish. */
function refreshSidesSection(dayIndex) {
    const container = document.getElementById(`side-row-${dayIndex}`);
    if (container) container.innerHTML = renderSidesSection(dayIndex);
}

/**
 * Opens the manual side dish selection box: either IN PLACE OF an
 * existing side dish row (sideId set - replaces exactly that slot, see
 * setOneSide) or IN PLACE OF the "add" row (sideId null - creates a NEW
 * slot, see addSide). Both cases use the same mechanism: find the target
 * row by id, remember its current markup, swap it for the selection box
 * (see static/plan-manual-select.js). After a successful selection,
 * refreshSidesSection() re-renders the whole section anyway (see
 * addSide/setOneSide), so a manual restore on success isn't needed -
 * only on "Cancel".
 */
function openSideManualSelect(dayIndex, sideId) {
    const container = sideId
        ? document.getElementById(`side-item-${dayIndex}-${sideId}`)
        : document.getElementById(`side-add-row-${dayIndex}`);
    if (!container) return;

    const previousHtml = container.innerHTML;
    container.innerHTML = buildManualSelectHtml(true);
    wireManualSelectBox(
        container, true,
        (recipeId) => {
            if (sideId) {
                setOneSide(dayIndex, sideId, recipeId);
            } else {
                addSide(dayIndex, recipeId);
            }
        },
        () => { container.innerHTML = previousHtml; }
    );
}

/**
 * Creates a NEW side dish for a day (calls
 * routes/plan/day_actions.py: add_side() server-side) - in addition to
 * any already present, a day can have any number. recipeId is optional:
 * if set (manual selection via ✏️), exactly that recipe is used; if
 * missing (🎲 button), the server rolls one at random, taking weekly
 * duplicates and the soft repetition weighting into account.
 */
function addSide(dayIndex, recipeId) {
    postWithCsrf(`/day/${dayDates[dayIndex]}/side/add`, {
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ recipe_id: recipeId || null }),
    })
    .then(response => {
        if (!response.ok) return response.json().then(data => { throw new Error(data.error || 'No side dish available.'); });
        return response.json();
    })
    .then(newSide => {
        weeklySideRecipes[dayIndex].push(newSide);
        refreshSidesSection(dayIndex);
        rebuildShoppingList();
    })
    .catch(err => {
        alert('Notice: ' + err.message);
    });
}

/** Short alias for the 🎲 button of the "add side dish" row - rolls a new side dish without manual selection. */
function addRandomSide(dayIndex) {
    addSide(dayIndex, null);
}

/**
 * Rerolls A SINGLE existing side dish (replaces it with a different,
 * randomly chosen recipe - unlike addSide, which creates an ADDITIONAL
 * slot). sideId identifies the PlanDaySide row, not the recipe.
 */
function rerollOneSide(dayIndex, sideId) {
    postWithCsrf(`/day/${dayDates[dayIndex]}/side/${sideId}/reroll`)
    .then(response => {
        if (!response.ok) return response.json().then(data => { throw new Error(data.error || 'No alternative available.'); });
        return response.json();
    })
    .then(newSide => {
        const idx = weeklySideRecipes[dayIndex].findIndex(s => s.side_id === sideId);
        if (idx !== -1) weeklySideRecipes[dayIndex][idx] = newSide;
        refreshSidesSection(dayIndex);
        rebuildShoppingList();
    })
    .catch(err => {
        alert('Notice: ' + err.message);
    });
}

/** Replaces A SINGLE existing side dish with a recipe manually chosen by the user (the manual counterpart to rerollOneSide). */
function setOneSide(dayIndex, sideId, recipeId) {
    postWithCsrf(`/day/${dayDates[dayIndex]}/side/${sideId}/set`, {
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ recipe_id: recipeId }),
    })
    .then(response => {
        if (!response.ok) return response.json().then(data => { throw new Error(data.error || 'Selection failed.'); });
        return response.json();
    })
    .then(newSide => {
        const idx = weeklySideRecipes[dayIndex].findIndex(s => s.side_id === sideId);
        if (idx !== -1) weeklySideRecipes[dayIndex][idx] = newSide;
        refreshSidesSection(dayIndex);
        rebuildShoppingList();
    })
    .catch(err => {
        alert('Notice: ' + err.message);
    });
}

/** Permanently removes A SINGLE existing side dish, without touching the other side dishes of the same day. */
function removeOneSide(dayIndex, sideId) {
    postWithCsrf(`/day/${dayDates[dayIndex]}/side/${sideId}/remove`)
    .then(response => {
        if (!response.ok) throw new Error('Removing failed.');
    })
    .then(() => {
        weeklySideRecipes[dayIndex] = weeklySideRecipes[dayIndex].filter(s => s.side_id !== sideId);
        refreshSidesSection(dayIndex);
        rebuildShoppingList();
    })
    .catch(err => {
        alert('Notice: ' + err.message);
    });
}

// --- MOVING A SINGLE SIDE DISH VIA DRAG-AND-DROP ---
// See static/plan.js for the full day swap (dragging the whole card) and
// the shared dayCardDrop() handler, which branches here (moveSideDish)
// based on the {type: 'side', ...} payload encoded in the DataTransfer.

/** Remembers the origin (day + PlanDaySide ID) of A SINGLE side dish row in the DataTransfer when dragging starts. stopPropagation prevents the enclosing card's dayCardDragStart from ALSO (redundantly) firing. */
function sideDragStart(event, dayIndex, sideId) {
    event.dataTransfer.setData('text/plain', JSON.stringify({ type: 'side', dayIndex: dayIndex, sideId: sideId }));
    event.stopPropagation();
}

/**
 * Moves A SINGLE side dish from sourceDayIndex to targetDayIndex (calls
 * routes/plan/day_actions.py: move_one_side() server-side) - a one-way
 * move, not a swap: the target day keeps everything it already had, and
 * gets the side dish in addition. On success, updates both affected side
 * dish sections (not the whole card, the main dish stays untouched after
 * all). Called by static/plan.js: dayCardDrop().
 */
function moveSideDish(sourceDayIndex, sideId, targetDayIndex) {
    if (sourceDayIndex === targetDayIndex) return;

    postWithCsrf(`/day/${dayDates[sourceDayIndex]}/side/${sideId}/move/${dayDates[targetDayIndex]}`)
    .then(response => {
        if (!response.ok) throw new Error('Moving failed.');
        return response.json();
    })
    .then(movedSide => {
        weeklySideRecipes[sourceDayIndex] = weeklySideRecipes[sourceDayIndex].filter(s => s.side_id !== sideId);
        weeklySideRecipes[targetDayIndex].push(movedSide);
        refreshSidesSection(sourceDayIndex);
        refreshSidesSection(targetDayIndex);
        rebuildShoppingList();
    })
    .catch(err => {
        alert('Notice: ' + err.message);
    });
}
