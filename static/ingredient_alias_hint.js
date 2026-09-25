/**
 * Live hint under the ingredient row being edited in the recipe form:
 *  A) the name has an alias -> show its group name
 *  B) the name is itself an alias target -> show which names point to it
 *  C) neither -> offer a mini form to set an alias
 * plus, if the resolved ingredient has no nutrition entry, a mini form to
 * add one.
 *
 * Needs window.INGREDIENT_ALIASES and window.INGREDIENT_NUTRITION. Uses
 * event delegation only, so rows added later work without setup.
 */

(function () {
    const ALIASES = window.INGREDIENT_ALIASES || {};
    const NUTRITION = window.INGREDIENT_NUTRITION || {};

    let canonicalNames = new Set(Object.values(ALIASES));

    /** Must match Python's str.title() exactly (the server's alias key):
     * every letter after a non-letter is uppercased, so
     * "(ca. 20 g) ginger" -> "(Ca. 20 G) Ginger". \p{L} covers umlauts. */
    function titleCase(value) {
        let result = '';
        let prevIsLetter = false;
        for (const ch of value.trim()) {
            const isLetter = /\p{L}/u.test(ch);
            result += isLetter ? (prevIsLetter ? ch.toLowerCase() : ch.toUpperCase()) : ch;
            prevIsLetter = isLetter;
        }
        return result;
    }

    function rawNamesFor(canonical) {
        return Object.entries(ALIASES)
            .filter(([, c]) => c === canonical)
            .map(([raw]) => raw);
    }

    function resolveNutritionCanonical(name) {
        return Object.prototype.hasOwnProperty.call(ALIASES, name) ? ALIASES[name] : name;
    }

    function renderHint(hintEl, name) {
        hintEl.innerHTML = '';
        hintEl.classList.remove('text-muted');
        if (!name) return;

        const aliasWrap = document.createElement('div');
        hintEl.appendChild(aliasWrap);
        renderAliasPart(aliasWrap, name, hintEl);

        const nutritionWrap = document.createElement('div');
        hintEl.appendChild(nutritionWrap);
        renderNutritionPart(nutritionWrap, name, hintEl);
    }

    function renderAliasPart(wrap, name, hintEl) {
        if (Object.prototype.hasOwnProperty.call(ALIASES, name)) {
            // Case A
            wrap.classList.add('text-muted');
            wrap.innerHTML = `→ ${escapeHtml(window.I18N.grouped_as_label)} „<b>${escapeHtml(ALIASES[name])}</b>"`;
            return;
        }

        if (canonicalNames.has(name)) {
            // Case B
            const examples = rawNamesFor(name).slice(0, 3).join(', ');
            wrap.classList.add('text-muted');
            wrap.innerHTML = `${escapeHtml(window.I18N.base_ingredient_label)}${examples ? ' (' + escapeHtml(window.I18N.example_for_label) + ' ' + escapeHtml(examples) + ')' : ''}`;
            return;
        }

        // Case C
        const group = document.createElement('div');
        group.className = 'input-group input-group-sm mt-1';
        group.innerHTML = `
            <input type="text" class="form-control form-control-sm alias-target-input" placeholder="${escapeHtml(window.I18N.set_alias_placeholder)}" list="canonical-names-datalist">
            <button type="button" class="btn btn-outline-secondary alias-set-btn">${escapeHtml(window.I18N.set_button_label)}</button>
        `;
        const input = group.querySelector('.alias-target-input');
        const button = group.querySelector('.alias-set-btn');
        button.addEventListener('click', () => submitAlias(name, input.value.trim(), hintEl));
        input.addEventListener('keydown', e => {
            if (e.key === 'Enter') { e.preventDefault(); submitAlias(name, input.value.trim(), hintEl); }
        });
        wrap.appendChild(group);
    }

    /** Only shown when the resolved ingredient has no nutrition entry yet.
     * No calories field: they are always computed. */
    function renderNutritionPart(wrap, name, hintEl) {
        const canonical = resolveNutritionCanonical(name);
        if (Object.prototype.hasOwnProperty.call(NUTRITION, canonical)) return;

        const box = document.createElement('div');
        box.className = 'mt-1 p-2 border rounded';
        box.innerHTML = `
            <div class="text-danger small fw-bold mb-2">${escapeHtml(window.I18N.no_nutrition_data_for)} „${escapeHtml(canonical)}"</div>
            <div class="row g-2">
                <div class="col-6 col-sm-3">
                    <label class="form-label small text-muted mb-1">${escapeHtml(window.I18N.reference_label)}</label>
                    <select class="form-select form-select-sm nutrition-ref-unit">
                        <option value="g" selected>${escapeHtml(window.I18N.per_100g_option)}</option>
                        <option value="ml">${escapeHtml(window.I18N.per_100ml_option)}</option>
                        <option value="Stk">${escapeHtml(window.I18N.per_1pc_option)}</option>
                    </select>
                </div>
                <div class="col-4 col-sm-3">
                    <label class="form-label small text-muted mb-1">${escapeHtml(window.I18N.protein_g_label)}</label>
                    <input type="number" step="0.1" class="form-control form-control-sm nutrition-protein" placeholder="0">
                </div>
                <div class="col-4 col-sm-3">
                    <label class="form-label small text-muted mb-1">${escapeHtml(window.I18N.carbs_g_label)}</label>
                    <input type="number" step="0.1" class="form-control form-control-sm nutrition-carbs" placeholder="0">
                </div>
                <div class="col-4 col-sm-3">
                    <label class="form-label small text-muted mb-1">${escapeHtml(window.I18N.fat_g_label)}</label>
                    <input type="number" step="0.1" class="form-control form-control-sm nutrition-fat" placeholder="0">
                </div>
            </div>
            <button type="button" class="btn btn-sm btn-outline-danger mt-2 nutrition-set-btn">${escapeHtml(window.I18N.save_nutrition_data_label)}</button>
        `;
        box.querySelector('.nutrition-set-btn').addEventListener('click', () => submitNutrition(canonical, box, name, hintEl));
        wrap.appendChild(box);
    }

    function submitAlias(rawName, canonicalName, hintEl) {
        if (!canonicalName) return;
        fetch('/api/ingredient-alias/set', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': window.CSRF_TOKEN },
            body: JSON.stringify({ raw_name: rawName, canonical_name: canonicalName }),
        })
        .then(response => response.json().then(data => ({ ok: response.ok, data })))
        .then(({ ok, data }) => {
            if (!ok) { alert(window.I18N.note_prefix + ' ' + (data.error || window.I18N.could_not_set_alias)); return; }
            ALIASES[data.raw_name] = data.canonical_name;
            canonicalNames = new Set(Object.values(ALIASES));
            fillUnitFromNutrition(hintEl, data.canonical_name);
            fillCategoryFromAlias(hintEl, data.category);
            fillPantryFromAlias(hintEl, data.is_pantry);
            renderHint(hintEl, data.raw_name);
        })
        .catch(() => alert(window.I18N.note_prefix + ' ' + window.I18N.could_not_set_alias));
    }

    // The three fill* helpers adopt what the merged ingredient already uses,
    // so merged spellings stay consistent on the shopping list. They only
    // fill empty/unset fields and never override the user's own choice.

    function fillCategoryFromAlias(hintEl, category) {
        if (!category) return;
        const categorySelect = hintEl.closest('.ingredient-row')?.querySelector('[name="ing_category[]"]');
        if (categorySelect && !categorySelect.value) {
            categorySelect.value = category;
        }
    }

    /** Only ever checks the box; the hidden mirror input is the submitted value. */
    function fillPantryFromAlias(hintEl, isPantry) {
        if (!isPantry) return;
        const checkbox = hintEl.closest('.ingredient-row')?.querySelector('.ing-pantry-checkbox');
        if (checkbox && !checkbox.checked) {
            checkbox.checked = true;
            const hiddenInput = checkbox.previousElementSibling;
            if (hiddenInput) hiddenInput.value = '1';
        }
    }

    function fillUnitFromNutrition(hintEl, canonicalName) {
        const entry = NUTRITION[canonicalName];
        if (!entry || !entry.reference_unit) return;
        const unitInput = hintEl.closest('.ingredient-row')?.querySelector('[name="ing_unit[]"]');
        if (unitInput && !unitInput.value.trim()) {
            unitInput.value = entry.reference_unit;
        }
    }

    function submitNutrition(canonicalName, box, name, hintEl) {
        const unit = box.querySelector('.nutrition-ref-unit').value;
        const protein = parseFloat(box.querySelector('.nutrition-protein').value) || 0;
        const carbs = parseFloat(box.querySelector('.nutrition-carbs').value) || 0;
        const fat = parseFloat(box.querySelector('.nutrition-fat').value) || 0;

        fetch('/api/ingredient-nutrition/set', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': window.CSRF_TOKEN },
            body: JSON.stringify({
                name: canonicalName, reference_unit: unit,
                protein, carbs, fat,
            }),
        })
        .then(response => response.json().then(data => ({ ok: response.ok, data })))
        .then(({ ok, data }) => {
            if (!ok) { alert(window.I18N.note_prefix + ' ' + (data.error || window.I18N.could_not_save_nutrition)); return; }
            NUTRITION[data.canonical_name] = data;
            renderHint(hintEl, name);
        })
        .catch(() => alert(window.I18N.note_prefix + ' ' + window.I18N.could_not_save_nutrition));
    }

    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    function hintContainerFor(input) {
        return input.closest('.ingredient-row')?.querySelector('.ingredient-alias-hint') || null;
    }

    document.body.addEventListener('input', event => {
        if (!event.target.matches('input[name="ing_name[]"]')) return;
        const hintEl = hintContainerFor(event.target);
        if (!hintEl) return;
        renderHint(hintEl, titleCase(event.target.value));
    });

    /** Limits DOM queries to the row's form rather than the whole page. */
    function formScopeOf(el) {
        return el.closest('form') || document.body;
    }

    /** Only the row being edited shows a hint. */
    function clearOtherHints(exceptHintEl) {
        formScopeOf(exceptHintEl).querySelectorAll('.ingredient-alias-hint').forEach(el => {
            if (el !== exceptHintEl && el.innerHTML) el.innerHTML = '';
        });
    }

    // focusin (focus doesn't bubble). Deliberately not cleared on blur:
    // blur fires before click, so the hint's own buttons would vanish
    // before they receive the click.
    document.body.addEventListener('focusin', event => {
        if (!event.target.matches('input[name="ing_name[]"]')) return;
        const hintEl = hintContainerFor(event.target);
        if (!hintEl) return;
        clearOtherHints(hintEl);
        renderHint(hintEl, titleCase(event.target.value));
    });

    // Existing rows show the alias name (.ing-name-display); clicking it
    // reveals the real input, whose value never changes on its own.
    // Closing uses a document click listener rather than blur, because
    // Safari doesn't move focus when a non-form element is clicked. A click
    // anywhere in the same row (including the hint buttons) keeps it open;
    // Tab is covered by the focusin listener.
    function ingNameInputFor(display) {
        const input = display.nextElementSibling;
        return (input && input.matches('.ing-name-input')) ? input : null;
    }
    function ingNameDisplayFor(input) {
        const display = input.previousElementSibling;
        return (display && display.matches('.ing-name-display')) ? display : null;
    }

    function revertIngredientNameField(input) {
        const display = ingNameDisplayFor(input);
        if (!display) return;
        display.textContent = ALIASES[titleCase(input.value)] || input.value;
        display.classList.remove('d-none');
        input.classList.add('d-none');
    }

    function revertAllOpenIngredientNames(exceptInput, scopeEl) {
        formScopeOf(scopeEl || exceptInput || document.body).querySelectorAll('.ing-name-input:not(.d-none)').forEach(openInput => {
            if (openInput !== exceptInput) revertIngredientNameField(openInput);
        });
    }

    function openIngredientNameField(display) {
        const input = ingNameInputFor(display);
        if (!input) return;
        revertAllOpenIngredientNames(input, input);
        display.classList.add('d-none');
        input.classList.remove('d-none');
        input.focus();
        input.select();
    }

    document.body.addEventListener('click', event => {
        const display = event.target.closest('.ing-name-display');
        if (display) openIngredientNameField(display);
    });
    document.body.addEventListener('keydown', event => {
        if (!event.target.matches('.ing-name-display')) return;
        if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); openIngredientNameField(event.target); }
    });
    document.addEventListener('click', event => {
        formScopeOf(event.target).querySelectorAll('.ing-name-input:not(.d-none)').forEach(openInput => {
            const row = openInput.closest('.ingredient-row');
            if (row && !row.contains(event.target)) revertIngredientNameField(openInput);
        });
    });
    document.body.addEventListener('focusin', event => {
        revertAllOpenIngredientNames(event.target.matches('.ing-name-input') ? event.target : null, event.target);
    });
})();
