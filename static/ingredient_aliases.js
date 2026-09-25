/** Ingredients & nutrition page (ingredient_aliases_manage.html). */
// Explicit plan_id: this page may show a plan that isn't the active one.
function postJson(url, body) {
    return fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': window.CSRF_TOKEN },
        body: JSON.stringify({ ...body, plan_id: INGREDIENTS_PLAN_ID }),
    }).then(response => response.json().then(data => ({ ok: response.ok, data })));
}

function showAutosaveResult(indicatorEl, ok) {
    indicatorEl.textContent = ok ? '✓' : '⚠️';
    indicatorEl.className = 'autosave-indicator ' + (ok ? 'autosave-ok' : 'autosave-error');
    setTimeout(() => { indicatorEl.textContent = ''; indicatorEl.className = 'autosave-indicator'; }, 2000);
}

// Tabs and filter live outside the rows, so they are never re-rendered.
document.querySelectorAll('.ingredient-subtab-btn').forEach(btn => {
    btn.addEventListener('click', () => {
        document.querySelectorAll('.ingredient-subtab-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        const isMain = btn.dataset.subtab === 'main';
        document.getElementById('mainSubtabContent')?.classList.toggle('d-none', !isMain);
        document.getElementById('otherSubtabContent')?.classList.toggle('d-none', isMain);
    });
});
wireFuzzyFilter(
    document.getElementById('ingredientFilter'), '.ingredient-card',
    row => row.dataset.search
);

// Server markup each row was rendered from. Refreshes compare against this,
// not the live outerHTML, which user interaction (typed values, classes,
// indicators) changes.
const serverHtmlByRow = new WeakMap();

/** Wires one card's autosave handlers. Unchanged rows are never passed
 * through here again, so listeners are never attached twice. */
function wireIngredientCard(card) {
    serverHtmlByRow.set(card, card.outerHTML);

    const block = card.querySelector('.nutrition-block');
    if (block) wireNutritionBlock(block);

    card.querySelectorAll('.alias-remove-btn').forEach(wireAliasRemoveButton);

    const countsAsInput = card.querySelector('.counts-as-input');
    if (countsAsInput) wireCountsAsInput(countsAsInput);
}

// Saves on change, not per keystroke; live kcal uses 4/4/9 like
// services/nutrition.py. Never moves a row between tabs, so no refresh.
function wireNutritionBlock(block) {
    const name = block.dataset.nutritionName;
    const referenceSelect = block.querySelector('.nutrition-reference');
    const proteinInput = block.querySelector('.nutrition-protein');
    const carbsInput = block.querySelector('.nutrition-carbs');
    const fatInput = block.querySelector('.nutrition-fat');
    const caloriesDisplay = block.querySelector('.nutrition-calories-display');
    const indicator = block.querySelector('.autosave-indicator');

    function recalcCalories() {
        const protein = parseFloat(proteinInput.value) || 0;
        const carbs = parseFloat(carbsInput.value) || 0;
        const fat = parseFloat(fatInput.value) || 0;
        caloriesDisplay.textContent = Math.round(protein * 4 + carbs * 4 + fat * 9);
    }

    function save() {
        recalcCalories();
        postJson('/api/ingredient-nutrition/set', {
            name: name,
            reference_unit: referenceSelect.value,
            protein: proteinInput.value,
            carbs: carbsInput.value,
            fat: fatInput.value,
        }).then(({ ok }) => showAutosaveResult(indicator, ok))
          .catch(() => showAutosaveResult(indicator, false));
    }

    proteinInput.addEventListener('input', recalcCalories);
    carbsInput.addEventListener('input', recalcCalories);
    fatInput.addEventListener('input', recalcCalories);
    [referenceSelect, proteinInput, carbsInput, fatInput].forEach(el => el.addEventListener('change', save));
}

// "×": pointing an alias at itself deletes the mapping. The row (and maybe
// its group) moves tabs, so refresh from the server.
//
// The name comes from data-raw-name, not tojson inside onclick="...":
// tojson output is marked safe and its double quotes break out of the
// attribute (this broke every × button once).
function wireAliasRemoveButton(button) {
    button.addEventListener('click', () => {
        const rawName = button.dataset.rawName;
        button.disabled = true;
        postJson('/api/ingredient-alias/set', { raw_name: rawName, canonical_name: rawName })
            .then(({ ok }) => {
                if (ok) { refreshIngredientsContent(); return; }
                button.disabled = false;
                alert(window.I18N.note_prefix + ' ' + window.I18N.could_not_set_alias);
            })
            .catch(() => {
                button.disabled = false;
                alert(window.I18N.note_prefix + ' ' + window.I18N.could_not_set_alias);
            });
    });
}

// May move the row under "Main Ingredients", hence the refresh.
function wireCountsAsInput(input) {
    const indicator = input.nextElementSibling;
    input.addEventListener('change', () => {
        const rawName = input.dataset.rawName;
        const canonicalName = input.value.trim() || rawName;
        postJson('/api/ingredient-alias/set', { raw_name: rawName, canonical_name: canonicalName })
            .then(({ ok }) => {
                if (ok && canonicalName !== rawName) { refreshIngredientsContent(); return; }
                showAutosaveResult(indicator, ok);
            })
            .catch(() => showAutosaveResult(indicator, false));
    });
}

/** Reconciles one sub-tab with a freshly fetched page: identical rows keep
 * their live node (and focus/cursor); only new, removed or changed rows are
 * swapped. When either side has no row list (empty placeholder), the whole
 * sub-tab content is replaced instead. */
function reconcileIngredientSubtab(containerId, freshDoc) {
    const currentContainer = document.getElementById(containerId);
    const freshContainer = freshDoc.getElementById(containerId);
    if (!currentContainer || !freshContainer) return;

    const currentList = currentContainer.querySelector(':scope > .d-flex');
    const freshList = freshContainer.querySelector(':scope > .d-flex');

    if (!currentList || !freshList) {
        currentContainer.innerHTML = freshContainer.innerHTML;
        currentContainer.querySelectorAll('.ingredient-card').forEach(wireIngredientCard);
        return;
    }

    const freshRows = Array.from(freshList.querySelectorAll(':scope > .ingredient-card'));
    const freshKeys = new Set(freshRows.map(row => row.dataset.rowKey));
    const currentRowsByKey = new Map();
    currentList.querySelectorAll(':scope > .ingredient-card').forEach(row => {
        if (freshKeys.has(row.dataset.rowKey)) currentRowsByKey.set(row.dataset.rowKey, row);
        else row.remove();
    });

    // Never move an unchanged row: any DOM move (replaceChildren,
    // insertBefore) blurs focus inside it. Stale rows are already removed,
    // so survivors are in order; only changed rows are replaced in place and
    // new ones inserted after their predecessor.
    let previous = null;
    freshRows.forEach(freshRow => {
        const existingRow = currentRowsByKey.get(freshRow.dataset.rowKey);
        let node = existingRow;

        if (!existingRow || serverHtmlByRow.get(existingRow) !== freshRow.outerHTML) {
            wireIngredientCard(freshRow);
            if (existingRow) existingRow.replaceWith(freshRow);
            else if (previous) previous.after(freshRow);
            else currentList.prepend(freshRow);
            node = freshRow;
        } else if (node.previousElementSibling !== previous) {
            // Only if the server order changed; can't happen with sorted lists.
            if (previous) previous.after(node);
            else currentList.prepend(node);
        }
        previous = node;
    });
}

const FOCUSABLE_FIELD_CLASSES = ['nutrition-reference', 'nutrition-protein', 'nutrition-carbs', 'nutrition-fat', 'counts-as-input'];

/** For when the focused row itself changed on the server and had to be
 * replaced: restores focus, unsaved value and cursor on the new field. */
function captureFocusedField() {
    const el = document.activeElement;
    const row = el && el.closest ? el.closest('.ingredient-card') : null;
    const fieldClass = el && FOCUSABLE_FIELD_CLASSES.find(cls => el.classList.contains(cls));
    if (!row || !fieldClass) return null;
    let selection = null;
    try { selection = [el.selectionStart, el.selectionEnd]; } catch (e) { /* e.g. type="number" */ }
    return { el, rowKey: row.dataset.rowKey, fieldClass, value: el.value, selection };
}

function restoreFocusedField(captured) {
    if (!captured || (captured.el.isConnected && document.activeElement === captured.el)) return;
    const row = document.querySelector(`.ingredient-card[data-row-key="${CSS.escape(captured.rowKey)}"]`);
    const field = row && row.querySelector('.' + captured.fieldClass);
    if (!field) return;
    field.value = captured.value;
    field.focus();
    if (captured.selection && captured.selection[0] != null) {
        try { field.setSelectionRange(captured.selection[0], captured.selection[1]); } catch (e) { /* not supported */ }
    }
}

/** Re-fetches the page and reconciles both sub-tabs. A real reload would
 * lose scroll position, active tab and filter; replacing all rows would
 * lose focus in unrelated fields. */
function refreshIngredientsContent() {
    return fetch(window.location.href)
        .then(response => {
            if (!response.ok) throw new Error('refresh failed');
            return response.text();
        })
        .then(html => {
            const freshDoc = new DOMParser().parseFromString(html, 'text/html');
            const focused = captureFocusedField();
            reconcileIngredientSubtab('mainSubtabContent', freshDoc);
            reconcileIngredientSubtab('otherSubtabContent', freshDoc);
            restoreFocusedField(focused);

            // Re-apply the search filter to inserted/replaced rows.
            document.getElementById('ingredientFilter')?.dispatchEvent(new Event('input'));

            const freshMainBadge = freshDoc.querySelector('.ingredient-subtab-btn[data-subtab="main"] .badge');
            const freshOtherBadge = freshDoc.querySelector('.ingredient-subtab-btn[data-subtab="other"] .badge');
            const mainBadge = document.querySelector('.ingredient-subtab-btn[data-subtab="main"] .badge');
            const otherBadge = document.querySelector('.ingredient-subtab-btn[data-subtab="other"] .badge');
            if (freshMainBadge && mainBadge) mainBadge.textContent = freshMainBadge.textContent;
            if (freshOtherBadge && otherBadge) otherBadge.textContent = freshOtherBadge.textContent;
        })
        // On network/server errors, reload rather than show stale data.
        .catch(() => window.location.reload());
}

document.querySelectorAll('.ingredient-card').forEach(wireIngredientCard);
