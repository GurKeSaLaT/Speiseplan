/**
 * Weekly nutrition summary, shopping list, pantry list and manual shopping
 * items on the plan page. Uses plan.js's state and postWithCsrf();
 * rebuildShoppingList() is called after practically every plan change.
 */

/** Per-serving totals and a daily average over planned days only; servings
 * never scale nutrition, only shopping amounts. */
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
        container.innerHTML = `<span class="text-muted small">${escapeHtml(window.I18N.no_dishes_planned)}</span>`;
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

/** Position in window.SHOPPING_CATEGORIES; unknown/missing sorts last. */
function categorySortIndex(category) {
    const categories = window.SHOPPING_CATEGORIES || [];
    const idx = categories.indexOf(category);
    return idx === -1 ? categories.length : idx;
}

/**
 * Rebuilds the shopping list (and the nutrition summary) from state.
 *
 * Recipe ingredients are scaled to each day's servings and merged by
 * name+unit. Pantry ingredients go to the pantry list instead - except
 * manually added items, which always stay on the shopping list (adding
 * one is an explicit "I need to buy this").
 */
function rebuildShoppingList() {
    rebuildWeeklyNutritionSummary();

    const container = document.getElementById('shoppingListContainer');
    const counterBadge = document.getElementById('totalIngredientsCount');
    if (!container) return;

    container.innerHTML = '';
    let consolidated = {};

    for (let i = 0; i < 7; i++) {
        [weeklyPlanRecipes[i], ...weeklySideRecipes[i]].forEach(recipe => {
            if (recipe && recipe.ingredients) {
                const factor = recipe.servings ? dayServings[i] / recipe.servings : 1;
                recipe.ingredients.forEach(ing => {
                    // Different units are never added up.
                    const key = `${ing.name.trim()}|||${ing.unit.trim()}`;
                    const scaledAmount = ing.amount * factor;
                    if (consolidated[key]) {
                        consolidated[key].amount += scaledAmount;
                        // Last non-empty category wins; pantry is OR'd.
                        if (ing.category) consolidated[key].category = ing.category;
                        if (ing.is_pantry) consolidated[key].is_pantry = true;
                    } else {
                        consolidated[key] = {
                            name: ing.name, amount: scaledAmount, unit: ing.unit,
                            category: ing.category || null, is_pantry: !!ing.is_pantry,
                        };
                    }
                });
            }
        });
    }

    // isExtra marks manual items: deletable, and never moved to the pantry list.
    const allItems = Object.values(consolidated).map(item => ({ ...item, isExtra: false }));
    weeklyExtraItems.forEach(extra => {
        allItems.push({
            id: extra.id, name: extra.name, amount: extra.amount, unit: extra.unit,
            category: extra.category, isExtra: true,
        });
    });

    const pantryItems = allItems.filter(item => !item.isExtra && item.is_pantry);
    const items = allItems.filter(item => item.isExtra || !item.is_pantry);

    if (counterBadge) counterBadge.textContent = items.length;

    if (items.length === 0) {
        container.innerHTML = `<li class="list-group-item text-center text-muted my-3">${escapeHtml(window.I18N.no_ingredients_needed)}</li>`;
    } else {
        renderGroupedList(container, items, buildShoppingRow);
    }

    renderPantryList(pantryItems);
}

/** Two decimals (hides float artifacts from scaling); null stays null. */
function roundedAmount(item) {
    return (item.amount === null || item.amount === undefined) ? null : Math.round(item.amount * 100) / 100;
}

/** The amount pill, or null when there is no amount. */
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

/** Sorts by category order, then name, with a header per category. */
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
        deleteBtn.title = window.I18N.remove_item_title;
        deleteBtn.textContent = '❌';
        deleteBtn.onclick = () => removeExtraShoppingItem(item.id);
        right.appendChild(deleteBtn);
    }

    li.appendChild(label);
    li.appendChild(right);

    // Ticking off while shopping is visual only; the list is rebuilt on
    // every plan change anyway, so nothing is saved.
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

function renderPantryList(pantryItems) {
    const container = document.getElementById('pantryListContainer');
    const counterBadge = document.getElementById('pantryItemsCount');
    if (!container) return;

    container.innerHTML = '';
    if (counterBadge) counterBadge.textContent = pantryItems.length;

    if (pantryItems.length === 0) {
        container.innerHTML = `<li class="list-group-item text-center text-muted my-3">${escapeHtml(window.I18N.no_spices_planned)}</li>`;
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
    addBtn.title = window.I18N.add_to_shopping_list_title;
    addBtn.textContent = '→ 🛒';
    addBtn.onclick = () => pushPantryItemToShoppingList(item);
    right.appendChild(addBtn);

    li.appendChild(nameSpan);
    li.appendChild(right);
    return li;
}

/** Adds a pantry item as a manual shopping item. An amount of 0 (e.g. salt
 * "to taste") becomes no amount instead of "0 g". */
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
        if (!response.ok) throw new Error(window.I18N.adding_failed);
        return response.json();
    })
    .then(newItem => {
        weeklyExtraItems.push(newItem);
        rebuildShoppingList();
    })
    .catch(err => {
        alert(window.I18N.note_prefix + ' ' + err.message);
    });
}

/** The "add item" form; only the name is required. */
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
        if (!response.ok) throw new Error(window.I18N.adding_failed);
        return response.json();
    })
    .then(newItem => {
        weeklyExtraItems.push(newItem);
        rebuildShoppingList();
        // Ready for the next item right away.
        nameInput.value = '';
        amountInput.value = '';
        unitInput.value = '';
        categorySelect.value = '';
        nameInput.focus();
    })
    .catch(err => {
        alert(window.I18N.note_prefix + ' ' + err.message);
    });
}

function removeExtraShoppingItem(itemId) {
    postWithCsrf(`/shopping-item/${itemId}/delete`)
    .then(response => {
        if (!response.ok) throw new Error(window.I18N.removing_failed);
        weeklyExtraItems = weeklyExtraItems.filter(item => item.id !== itemId);
        rebuildShoppingList();
    })
    .catch(err => {
        alert(window.I18N.note_prefix + ' ' + err.message);
    });
}
