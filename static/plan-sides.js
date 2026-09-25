/**
 * Side dishes on the plan page: rendering, adding (random or manual),
 * rerolling, replacing, removing and moving a single side to another day.
 * Uses plan.js's state, plan-manual-select.js and rebuildShoppingList().
 */

/** One row per side (addressed by side_id) plus the "add side" row. */
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
                <div class="dish-clickable${cookedClass}" role="button" title="${escapeHtml(window.I18N.show_details_title)}" onclick="openRecipeDetail(${dayIndex}, ${side.side_id})">
                    <span class="fw-bold text-dark side-dish-name">🥗 ${escapeHtml(side.name)}</span>
                    <span class="badge badge-category side-dish-category ms-1">${escapeHtml(side.category_name)}</span>
                    <span class="text-muted small side-dish-kcal">(${side.calories} kcal)</span>
                </div>
                <div class="d-flex align-items-center gap-1">
                    <button type="button" class="btn btn-sm btn-outline-secondary border-0 p-1" title="${escapeHtml(window.I18N.reroll_side_title)}" onclick="rerollOneSide(${dayIndex}, ${side.side_id})">🎲</button>
                    <button type="button" class="btn btn-sm btn-outline-secondary border-0 p-1" title="${escapeHtml(window.I18N.choose_different_side_title)}" onclick="openSideManualSelect(${dayIndex}, ${side.side_id})">✏️</button>
                    <button type="button" class="btn btn-sm text-danger border-0 p-1" title="${escapeHtml(window.I18N.remove_side_title)}" onclick="removeOneSide(${dayIndex}, ${side.side_id})">❌</button>
                </div>
            </div>
        `;
    });
    html += `
        <div id="side-add-row-${dayIndex}" class="d-flex gap-1">
            <button type="button" class="btn btn-sm btn-outline-secondary flex-grow-1" onclick="addRandomSide(${dayIndex})">🎲 ${escapeHtml(window.I18N.roll_side_dish_label)}</button>
            <button type="button" class="btn btn-sm btn-outline-secondary" title="${escapeHtml(window.I18N.choose_side_title)}" onclick="openSideManualSelect(${dayIndex}, null)">✏️</button>
        </div>
    `;
    return html;
}

function refreshSidesSection(dayIndex) {
    const container = document.getElementById(`side-row-${dayIndex}`);
    if (container) container.innerHTML = renderSidesSection(dayIndex);
}

/** Replaces a side's row (sideId) or the "add" row (sideId null) with the
 * search box. Success re-renders the section; Cancel restores the row. */
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

/** Adds a side; without recipeId the server picks one at random. */
function addSide(dayIndex, recipeId) {
    postWithCsrf(`/day/${dayDates[dayIndex]}/side/add`, {
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ recipe_id: recipeId || null }),
    })
    .then(response => {
        if (!response.ok) return response.json().then(data => { throw new Error(data.error || window.I18N.no_side_dish_available); });
        return response.json();
    })
    .then(newSide => {
        weeklySideRecipes[dayIndex].push(newSide);
        refreshSidesSection(dayIndex);
        rebuildShoppingList();
    })
    .catch(err => {
        alert(window.I18N.note_prefix + ' ' + err.message);
    });
}

function addRandomSide(dayIndex) {
    addSide(dayIndex, null);
}

function rerollOneSide(dayIndex, sideId) {
    postWithCsrf(`/day/${dayDates[dayIndex]}/side/${sideId}/reroll`)
    .then(response => {
        if (!response.ok) return response.json().then(data => { throw new Error(data.error || window.I18N.no_alternative_available); });
        return response.json();
    })
    .then(newSide => {
        const idx = weeklySideRecipes[dayIndex].findIndex(s => s.side_id === sideId);
        if (idx !== -1) weeklySideRecipes[dayIndex][idx] = newSide;
        refreshSidesSection(dayIndex);
        rebuildShoppingList();
    })
    .catch(err => {
        alert(window.I18N.note_prefix + ' ' + err.message);
    });
}

function setOneSide(dayIndex, sideId, recipeId) {
    postWithCsrf(`/day/${dayDates[dayIndex]}/side/${sideId}/set`, {
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ recipe_id: recipeId }),
    })
    .then(response => {
        if (!response.ok) return response.json().then(data => { throw new Error(data.error || window.I18N.selection_failed); });
        return response.json();
    })
    .then(newSide => {
        const idx = weeklySideRecipes[dayIndex].findIndex(s => s.side_id === sideId);
        if (idx !== -1) weeklySideRecipes[dayIndex][idx] = newSide;
        refreshSidesSection(dayIndex);
        rebuildShoppingList();
    })
    .catch(err => {
        alert(window.I18N.note_prefix + ' ' + err.message);
    });
}

function removeOneSide(dayIndex, sideId) {
    postWithCsrf(`/day/${dayDates[dayIndex]}/side/${sideId}/remove`)
    .then(response => {
        if (!response.ok) throw new Error(window.I18N.removing_failed);
    })
    .then(() => {
        weeklySideRecipes[dayIndex] = weeklySideRecipes[dayIndex].filter(s => s.side_id !== sideId);
        refreshSidesSection(dayIndex);
        rebuildShoppingList();
    })
    .catch(err => {
        alert(window.I18N.note_prefix + ' ' + err.message);
    });
}

// --- Moving a single side (dropped via plan.js: dayCardDrop) ---

/** stopPropagation keeps the surrounding day card from starting its own drag. */
function sideDragStart(event, dayIndex, sideId) {
    event.dataTransfer.setData('text/plain', JSON.stringify({ type: 'side', dayIndex: dayIndex, sideId: sideId }));
    event.stopPropagation();
}

/** One-way move; the target day keeps everything it had. */
function moveSideDish(sourceDayIndex, sideId, targetDayIndex) {
    if (sourceDayIndex === targetDayIndex) return;

    postWithCsrf(`/day/${dayDates[sourceDayIndex]}/side/${sideId}/move/${dayDates[targetDayIndex]}`)
    .then(response => {
        if (!response.ok) throw new Error(window.I18N.moving_failed);
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
        alert(window.I18N.note_prefix + ' ' + err.message);
    });
}
