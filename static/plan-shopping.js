/**
 * plan-shopping.js - weekly nutrition overview and shopping list on the
 * plan page (templates/plan.html): aggregates the nutrition/ingredients
 * of all planned main and side dishes for a week, groups the shopping
 * list by a fixed supermarket category order, and additionally manages
 * manually added shopping list items that don't belong to any recipe.
 *
 * Uses shared infrastructure from static/plan.js: the state arrays
 * (weeklyPlanRecipes/weeklySideRecipes/weeklyExtraItems/dayServings/
 * dayDates) and postWithCsrf(). rebuildShoppingList() is called by
 * practically EVERY plan-changing action on the page (see plan.js,
 * plan-sides.js) - it lives here because it belongs to the shopping list
 * in terms of content, not because it's only needed locally.
 */

/**
 * Sums up the nutrition values of all days (main + side dish, where
 * present) into a weekly summary and a daily average (averaged only over
 * days actually planned, not over all 7). The values deliberately remain
 * UNscaled with respect to the number of servings: nutrition values in
 * this project are always meant "per portion/person", regardless of how
 * many people are eating that day - the number of servings only affects
 * the ingredient amounts of the shopping list (see rebuildShoppingList).
 */
function rebuildWeeklyNutritionSummary() {
    const container = document.getElementById('weeklyNutritionSummary');
    if (!container) return;

    const totals = { calories: 0, protein: 0, carbs: 0, fat: 0 };
    let plannedDays = 0;

    for (let i = 0; i < 7; i++) {
        let dayHasSomething = false;
        [weeklyPlanRecipes[i], ...weeklySideRecipes[i]].forEach(recipe => {
            if (recipe) {
                totals.calories += recipe.calories || 0;
                totals.protein += recipe.protein || 0;
                totals.carbs += recipe.carbs || 0;
                totals.fat += recipe.fat || 0;
                dayHasSomething = true;
            }
        });
        if (dayHasSomething) plannedDays++;
    }

    if (plannedDays === 0) {
        container.innerHTML = '<span class="text-muted small">No dishes in the plan yet.</span>';
        return;
    }

    container.innerHTML = `
        <div class="text-muted small font-monospace bg-light p-2 rounded mb-1">
            Σ week: ${Math.round(totals.calories)} kcal | P: ${totals.protein.toFixed(1)}g | C: ${totals.carbs.toFixed(1)}g | F: ${totals.fat.toFixed(1)}g
        </div>
        <div class="text-muted small font-monospace bg-light p-2 rounded">
            Ø per day (${plannedDays} planned): ${Math.round(totals.calories / plannedDays)} kcal | P: ${(totals.protein / plannedDays).toFixed(1)}g | C: ${(totals.carbs / plannedDays).toFixed(1)}g | F: ${(totals.fat / plannedDays).toFixed(1)}g
        </div>
    `;
}

/**
 * Returns the sort position of a shopping list category according to the
 * fixed order in window.SHOPPING_CATEGORIES (see base.html/
 * services/shopping.py). Unknown or missing categories (null,
 * undefined, or a value that isn't in the list - e.g. because an
 * ingredient dates from before this field was introduced) get the
 * highest position number and therefore always end up at the VERY END
 * of the shopping list, in the "Other" catch-all group.
 */
function categorySortIndex(category) {
    const categories = window.SHOPPING_CATEGORIES || [];
    const idx = categories.indexOf(category);
    return idx === -1 ? categories.length : idx;
}

/**
 * Recomputes the entire shopping list for the week from the current
 * JavaScript state and renders it, grouped by the fixed shopping list
 * category order (see categorySortIndex) and alphabetically within a
 * group. Called after EVERY change to the plan (rerolling, swapping,
 * number of servings, removing a side dish, adding/removing an item),
 * since practically every one of these changes affects the required
 * ingredient amounts. Also calls rebuildWeeklyNutritionSummary() along
 * the way, since both overviews are always kept up to date together.
 *
 * Two sources feed into the list: items derived from recipe ingredients
 * (consolidated by name+unit across the whole week and scaled by the
 * respective day's number of servings, as before) as well as manually
 * added items from weeklyExtraItems (unscaled, each shown individually
 * with its own delete button, since they don't belong to any
 * recipe/day).
 *
 * Items originating from recipes whose category is in window.PANTRY_
 * CATEGORIES (spices/consumables, see services/shopping.py) are FILTERED
 * OUT here and instead displayed separately by renderPantryList() - as a
 * rule you already have these at home, they shouldn't fill up the actual
 * shopping list anew every week. A manually added item (isExtra) is
 * ALWAYS exempt from this, even with a pantry category: manually adding
 * it (including via the "→ Shopping list" button from the pantry list,
 * see pushPantryItemToShoppingList) is already the explicit "I really do
 * need to buy this" decision, which shouldn't be filtered out again.
 */
function rebuildShoppingList() {
    rebuildWeeklyNutritionSummary();

    const container = document.getElementById('shoppingListContainer');
    const counterBadge = document.getElementById('totalIngredientsCount');
    if (!container) return;

    container.innerHTML = '';
    let consolidated = {};

    // Ingredient amounts are scaled up per day to the number of servings
    // set there (relative to the respective recipe's serving count) -
    // nutrition values are unaffected by this, they are always per
    // portion/person.
    for (let i = 0; i < 7; i++) {
        [weeklyPlanRecipes[i], ...weeklySideRecipes[i]].forEach(recipe => {
            if (recipe && recipe.ingredients) {
                const factor = recipe.servings ? dayServings[i] / recipe.servings : 1;
                recipe.ingredients.forEach(ing => {
                    // Consolidation key made of name+unit: the same
                    // ingredient in a different unit (e.g. "flour" in g
                    // on one day, in tbsp on another) is deliberately NOT
                    // added together, since the amounts wouldn't be
                    // comparable otherwise.
                    const key = `${ing.name.trim()}|||${ing.unit.trim()}`;
                    const scaledAmount = ing.amount * factor;
                    if (consolidated[key]) {
                        consolidated[key].amount += scaledAmount;
                        // If the same ingredient was categorized slightly
                        // differently across multiple recipes, the
                        // last-seen non-empty category wins - not a hard
                        // error case, barely occurs in practice.
                        if (ing.category) consolidated[key].category = ing.category;
                    } else {
                        consolidated[key] = { name: ing.name, amount: scaledAmount, unit: ing.unit, category: ing.category || null };
                    }
                });
            }
        });
    }

    // Merge consolidated recipe ingredients and manual items into one
    // shared list, so both are sorted and grouped together for display -
    // isExtra later determines whether an entry gets a delete button
    // (only manual items can be individually removed, recipe ingredients
    // follow automatically from the plan) AND whether it stays on the
    // shopping list despite having a pantry category (see the function
    // comment above).
    const allItems = Object.values(consolidated).map(item => ({ ...item, isExtra: false }));
    weeklyExtraItems.forEach(extra => {
        allItems.push({
            id: extra.id, name: extra.name, amount: extra.amount, unit: extra.unit,
            category: extra.category, isExtra: true,
        });
    });

    const pantryCategories = window.PANTRY_CATEGORIES || [];
    const pantryItems = allItems.filter(item => !item.isExtra && pantryCategories.includes(item.category));
    const items = allItems.filter(item => item.isExtra || !pantryCategories.includes(item.category));

    if (counterBadge) counterBadge.textContent = items.length;

    if (items.length === 0) {
        container.innerHTML = '<li class="list-group-item text-center text-muted my-3">No ingredients needed for this week.</li>';
    } else {
        renderGroupedList(container, items, buildShoppingRow);
    }

    renderPantryList(pantryItems);
}

/**
 * Rounds an amount value to 2 decimal places (avoids floating-point
 * artifacts from the servings scaling, e.g. 133.33333333333334 ->
 * 133.33) and passes null through unchanged - a manual item is allowed
 * to exist with no amount at all, see addExtraShoppingItem.
 */
function roundedAmount(item) {
    return (item.amount === null || item.amount === undefined) ? null : Math.round(item.amount * 100) / 100;
}

/**
 * Builds the green amount pill (e.g. "250 g") - shared by the shopping
 * list and the pantry list. Returns null when there's nothing to display
 * (roundedAmount() is null), instead of an empty element.
 */
function buildAmountBadge(item) {
    const displayAmount = roundedAmount(item);
    if (displayAmount === null) return null;
    const badge = document.createElement('span');
    badge.className = 'badge bg-success px-3 py-2 rounded-pill font-monospace';
    badge.style.backgroundColor = 'var(--primary-food)';
    badge.style.fontSize = '0.9rem';
    badge.textContent = item.unit ? `${displayAmount} ${item.unit}` : `${displayAmount}`;
    return badge;
}

/**
 * Shared basis for the shopping and pantry lists: sorts first by fixed
 * shopping category order (see categorySortIndex), then alphabetically
 * by name, inserts group headers whenever the category changes from the
 * previous item, and delegates building EACH individual row to
 * buildRowFn(item) (see buildShoppingRow/buildPantryRow) - the two lists
 * only differ in what controls a row gets (checkbox+delete button vs. a
 * plain "→ shopping list" button), not in sorting/grouping.
 */
function renderGroupedList(container, items, buildRowFn) {
    items.sort((a, b) => {
        const catDiff = categorySortIndex(a.category) - categorySortIndex(b.category);
        return catDiff !== 0 ? catDiff : a.name.localeCompare(b.name);
    });

    let lastCategoryLabel = undefined;
    items.forEach(item => {
        const categoryLabel = item.category || window.SHOPPING_UNCATEGORIZED;
        if (categoryLabel !== lastCategoryLabel) {
            const header = document.createElement('li');
            header.className = 'list-group-item bg-light text-muted small fw-bold text-uppercase py-1 px-3';
            header.textContent = categoryLabel;
            container.appendChild(header);
            lastCategoryLabel = categoryLabel;
        }
        container.appendChild(buildRowFn(item));
    });
}

/** One row of the actual shopping list: a checkbox to tick off while
 * shopping (purely visual, not saved) + name, on the right the amount
 * pill and - only for manually added items - a delete button. */
function buildShoppingRow(item) {
    const li = document.createElement('li');
    li.className = 'list-group-item d-flex justify-content-between align-items-center py-2 px-3';

    const label = document.createElement('label');
    label.className = 'd-flex align-items-center m-0 flex-grow-1';
    label.style.cursor = 'pointer';

    const checkbox = document.createElement('input');
    checkbox.type = 'checkbox';
    checkbox.className = 'form-check-input me-3';
    checkbox.style.transform = 'scale(1.15)';

    const nameSpan = document.createElement('span');
    nameSpan.className = 'text-dark fs-5';
    // textContent instead of innerHTML: item.name can be user input
    // (both an ingredient name from a recipe and the freely typed name
    // of a manual item), textContent thereby avoids any HTML/script
    // injection risk from the outset.
    nameSpan.textContent = item.name;

    label.appendChild(checkbox);
    label.appendChild(nameSpan);

    const right = document.createElement('div');
    right.className = 'd-flex align-items-center';

    const badge = buildAmountBadge(item);
    if (badge) right.appendChild(badge);

    if (item.isExtra) {
        const deleteBtn = document.createElement('button');
        deleteBtn.type = 'button';
        deleteBtn.className = 'btn btn-sm text-danger border-0 p-1 ms-1';
        deleteBtn.title = 'Remove item';
        deleteBtn.textContent = '❌';
        deleteBtn.onclick = () => removeExtraShoppingItem(item.id);
        right.appendChild(deleteBtn);
    }

    li.appendChild(label);
    li.appendChild(right);

    // The checkbox is purely for display while shopping (struck through +
    // greyed out once ticked) - the state is deliberately NOT saved
    // (neither server-side nor in localStorage), since the list is
    // rebuilt from scratch on every plan change anyway.
    checkbox.addEventListener('change', function() {
        if (this.checked) {
            nameSpan.style.textDecoration = 'line-through';
            nameSpan.style.opacity = '0.5';
        } else {
            nameSpan.style.textDecoration = 'none';
            nameSpan.style.opacity = '1';
        }
    });

    return li;
}

/**
 * Renders the "check your pantry" list (spices/consumables from this
 * week's planned recipes, see rebuildShoppingList) - NO checkbox
 * (there's nothing to tick off here, only possibly to re-buy), instead a
 * button that pulls exactly this item onto the actual shopping list via
 * pushPantryItemToShoppingList().
 */
function renderPantryList(pantryItems) {
    const container = document.getElementById('pantryListContainer');
    const counterBadge = document.getElementById('pantryItemsCount');
    if (!container) return;

    container.innerHTML = '';
    if (counterBadge) counterBadge.textContent = pantryItems.length;

    if (pantryItems.length === 0) {
        container.innerHTML = '<li class="list-group-item text-center text-muted my-3">No spices/consumables planned this week.</li>';
        return;
    }

    renderGroupedList(container, pantryItems, buildPantryRow);
}

function buildPantryRow(item) {
    const li = document.createElement('li');
    li.className = 'list-group-item d-flex justify-content-between align-items-center py-2 px-3';

    const nameSpan = document.createElement('span');
    nameSpan.className = 'text-dark fs-5';
    nameSpan.textContent = item.name;

    const right = document.createElement('div');
    right.className = 'd-flex align-items-center';

    const badge = buildAmountBadge(item);
    if (badge) right.appendChild(badge);

    const addBtn = document.createElement('button');
    addBtn.type = 'button';
    addBtn.className = 'btn btn-sm btn-outline-secondary ms-1';
    addBtn.title = 'Add to shopping list';
    addBtn.textContent = '→ 🛒';
    addBtn.onclick = () => pushPantryItemToShoppingList(item);
    right.appendChild(addBtn);

    li.appendChild(nameSpan);
    li.appendChild(right);
    return li;
}

/**
 * Pulls a single item from the pantry list onto the actual shopping list
 * - technically identical to addExtraShoppingItem() (same server
 * endpoint, creates an ExtraShoppingItem entry), only that the values
 * here already come from the clicked pantry item instead of the mini
 * form. An amount of 0 (e.g. salt "to taste", with no real amount) is
 * deliberately turned into null here, so the shopping list doesn't
 * pointlessly show "0 g" - the new entry is an isExtra item and
 * therefore stays on the shopping list even with a pantry category (see
 * rebuildShoppingList).
 */
function pushPantryItemToShoppingList(item) {
    postWithCsrf(`/plan/${dayDates[0]}/shopping-item/add`, {
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            name: item.name,
            amount: item.amount ? item.amount : null,
            unit: item.unit || '',
            category: item.category || '',
        }),
    })
    .then(response => {
        if (!response.ok) throw new Error('Adding failed.');
        return response.json();
    })
    .then(newItem => {
        weeklyExtraItems.push(newItem);
        rebuildShoppingList();
    })
    .catch(err => {
        alert('Notice: ' + err.message);
    });
}

/**
 * Reads out the "add item" mini form (see plan.html), creates the item
 * server-side for the currently displayed week (dayDates[0] is this
 * week's Monday) and, on success, appends it to weeklyExtraItems before
 * the shopping list is rebuilt. name is the only required field - if the
 * field is empty, nothing happens (no error needed, the button/Enter
 * press simply has no effect).
 */
function addExtraShoppingItem() {
    const nameInput = document.getElementById('extraItemName');
    const amountInput = document.getElementById('extraItemAmount');
    const unitInput = document.getElementById('extraItemUnit');
    const categorySelect = document.getElementById('extraItemCategory');
    if (!nameInput) return;

    const name = nameInput.value.trim();
    if (!name) return;

    postWithCsrf(`/plan/${dayDates[0]}/shopping-item/add`, {
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            name: name,
            amount: amountInput.value ? parseFloat(amountInput.value) : null,
            unit: unitInput.value.trim(),
            category: categorySelect.value,
        }),
    })
    .then(response => {
        if (!response.ok) throw new Error('Adding failed.');
        return response.json();
    })
    .then(newItem => {
        weeklyExtraItems.push(newItem);
        rebuildShoppingList();
        // Reset the form for the next item and immediately return focus
        // to the name field, so several items can be entered quickly in
        // a row via Enter.
        nameInput.value = '';
        amountInput.value = '';
        unitInput.value = '';
        categorySelect.value = '';
        nameInput.focus();
    })
    .catch(err => {
        alert('Notice: ' + err.message);
    });
}

/**
 * Removes a manually added item from the shopping list again (deleted
 * permanently server-side, not just hidden).
 */
function removeExtraShoppingItem(itemId) {
    postWithCsrf(`/shopping-item/${itemId}/delete`)
    .then(response => {
        if (!response.ok) throw new Error('Removing failed.');
        weeklyExtraItems = weeklyExtraItems.filter(item => item.id !== itemId);
        rebuildShoppingList();
    })
    .catch(err => {
        alert('Notice: ' + err.message);
    });
}
