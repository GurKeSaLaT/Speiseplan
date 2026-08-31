/**
 * ingredient_alias_hint.js - Live hint next to each ingredient-name field
 * when creating/editing a recipe (templates/recipe_form.html):
 * shows, as an ingredient is entered, whether an ingredient alias
 * (see services/ingredient_aliases.py, Management ->
 * 🔗 Ingredient aliases) already exists for it, and allows creating a
 * new one directly, without leaving the page. Exactly three cases:
 *
 * A) An alias already exists for the entered name
 *    (e.g. "Olive oil" -> "Oil") - shows what it's grouped under on the
 *    shopping list.
 * B) The entered name is itself the canonical name that OTHER
 *    ingredients point to ("base ingredient", e.g. "Oil" itself) - shows
 *    which ingredients it's the base ingredient for.
 * C) Neither A nor B: the name is so far entirely independent - offers
 *    a mini form to set an alias directly.
 *
 * Additionally (independent of A/B/C, see renderNutritionPart below):
 * checks whether nutrition data is already on file for the resolved
 * canonical ingredient (services/nutrition.py, Management ->
 * 🍎 Nutrition) - if not, offers a second mini form to add it directly,
 * without leaving the recipe page.
 *
 * window.INGREDIENT_ALIASES ({raw_name: canonical_name}, see
 * app.py: inject_ingredient_aliases()) and window.INGREDIENT_NUTRITION
 * ({canonical_name: {reference_amount, reference_unit, calories, protein,
 * carbs, fat}}, see app.py: inject_ingredient_nutrition()) must be
 * embedded in the DOM BEFORE this script. Works purely through event
 * delegation on document.body, so that both server-rendered rows and
 * rows added dynamically via JS (static/recipe_form.js:
 * rformAddIngredientRow) work without separate initialization.
 */

(function () {
    const ALIASES = window.INGREDIENT_ALIASES || {};
    const NUTRITION = window.INGREDIENT_NUTRITION || {};

    // Set of all canonical target names, for a fast "is this itself a
    // base ingredient?" check (case B). Kept up to date whenever a new
    // alias is set (see submitAlias below).
    let canonicalNames = new Set(Object.values(ALIASES));

    /** Python .title() equivalent for a client-side pre-check - MUST
     * produce exactly the same result as Python's str.title() (see
     * services/ingredient_aliases.py: normalize_name), otherwise
     * ALIASES lookups fail for names with punctuation (e.g. Python's
     * "(ca. 20 g) ginger".title() == "(Ca. 20 G) Ginger" - every
     * letter directly AFTER a non-letter is capitalized, not just
     * the first of each space-separated "word"). An earlier, simpler
     * version here only split on space/hyphen and got the wrong
     * capitalization for parentheses/periods as above - which meant
     * neither finding the existing alias nor, when collapsing the name
     * field back, showing the alias instead of the raw name. \p{L}
     * (Unicode "is a letter") instead of a fixed plain-ASCII pattern, so
     * this also works correctly for umlauts & accents, just like
     * Python's own Unicode-aware .title(). */
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

    /** Which canonical name the nutrition lookup for "name" runs
     * against: for an existing alias (case A) its target, otherwise the
     * name itself (case B/C - server-side, normalize_ingredient_name()
     * behaves the same way for a non-aliased name, see
     * services/nutrition.py: get_nutrition_entry). */
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
            wrap.innerHTML = `→ grouped as „<b>${escapeHtml(ALIASES[name])}</b>"`;
            return;
        }

        if (canonicalNames.has(name)) {
            // Case B
            const examples = rawNamesFor(name).slice(0, 3).join(', ');
            wrap.classList.add('text-muted');
            wrap.innerHTML = `🧺 Base ingredient${examples ? ' (e.g. for ' + escapeHtml(examples) + ')' : ''}`;
            return;
        }

        // Case C: neither alias nor base ingredient - offer a mini form to set one
        const group = document.createElement('div');
        group.className = 'input-group input-group-sm mt-1';
        group.innerHTML = `
            <input type="text" class="form-control form-control-sm alias-target-input" placeholder="Set alias, e.g. Pasta" list="canonical-names-datalist">
            <button type="button" class="btn btn-outline-secondary alias-set-btn">Set</button>
        `;
        const input = group.querySelector('.alias-target-input');
        const button = group.querySelector('.alias-set-btn');
        button.addEventListener('click', () => submitAlias(name, input.value.trim(), hintEl));
        input.addEventListener('keydown', e => {
            if (e.key === 'Enter') { e.preventDefault(); submitAlias(name, input.value.trim(), hintEl); }
        });
        wrap.appendChild(group);
    }

    /** Shows a mini form for adding nutrition data right away, provided
     * the resolved canonical ingredient does NOT yet have a nutrition
     * entry (POST /api/ingredient-nutrition/set, see
     * routes/settings.py: api_set_ingredient_nutrition). If an entry
     * already exists, nothing is shown. */
    function renderNutritionPart(wrap, name, hintEl) {
        const canonical = resolveNutritionCanonical(name);
        if (Object.prototype.hasOwnProperty.call(NUTRITION, canonical)) return;

        const box = document.createElement('div');
        box.className = 'mt-1 p-2 border rounded';
        box.innerHTML = `
            <div class="text-danger small fw-bold mb-2">⚠️ No nutrition data on file for „${escapeHtml(canonical)}"</div>
            <div class="row g-2">
                <div class="col-6 col-sm-3">
                    <label class="form-label small text-muted mb-1">Reference</label>
                    <select class="form-select form-select-sm nutrition-ref-unit">
                        <option value="g" selected>per 100 g</option>
                        <option value="ml">per 100 ml</option>
                        <option value="Stk">per 1 pc</option>
                    </select>
                </div>
                <div class="col-4 col-sm-3">
                    <label class="form-label small text-muted mb-1">Protein (g)</label>
                    <input type="number" step="0.1" class="form-control form-control-sm nutrition-protein" placeholder="0">
                </div>
                <div class="col-4 col-sm-3">
                    <label class="form-label small text-muted mb-1">Carbs (g)</label>
                    <input type="number" step="0.1" class="form-control form-control-sm nutrition-carbs" placeholder="0">
                </div>
                <div class="col-4 col-sm-3">
                    <label class="form-label small text-muted mb-1">Fat (g)</label>
                    <input type="number" step="0.1" class="form-control form-control-sm nutrition-fat" placeholder="0">
                </div>
            </div>
            <button type="button" class="btn btn-sm btn-outline-danger mt-2 nutrition-set-btn">Save nutrition data</button>
        `;
        // Calories are never entered directly, only computed from
        // protein/carbs/fat (services/nutrition.py: compute_calories()) -
        // so there is deliberately no input field for it here, and no
        // live display either (the compact inline box has no room for
        // one; the computed calories can be seen on the nutrition
        // management page).
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
            if (!ok) { alert('Note: ' + (data.error || 'Could not set alias.')); return; }
            ALIASES[data.raw_name] = data.canonical_name;
            canonicalNames = new Set(Object.values(ALIASES));
            fillUnitFromNutrition(hintEl, data.canonical_name);
            fillCategoryFromAlias(hintEl, data.category);
            renderHint(hintEl, data.raw_name);
        })
        .catch(() => alert('Note: Could not set alias.'));
    }

    /** When setting an alias, automatically takes over the shopping-list
     * category already in use for the canonical ingredient (guessed
     * server-side from existing ingredient rows, see
     * routes/settings.py: api_set_ingredient_alias/services/shopping.py:
     * infer_category) into the category field of THIS ingredient row -
     * only if it's still on the default selection "Other" (empty value);
     * a category the user already deliberately chose is never
     * overwritten. This keeps all ingredients aliased to the same name
     * (e.g. "Spaghetti"/"Fusilli" -> "Pasta") consistently grouped
     * together on the shopping list, instead of being sorted
     * differently depending on the recipe. */
    function fillCategoryFromAlias(hintEl, category) {
        if (!category) return;
        const categorySelect = hintEl.closest('.ingredient-row')?.querySelector('[name="ing_category[]"]');
        if (categorySelect && !categorySelect.value) {
            categorySelect.value = category;
        }
    }

    /** When setting an alias, automatically takes over the unit already
     * on file for the canonical ingredient (reference_unit from
     * window.INGREDIENT_NUTRITION) into the unit field of THIS
     * ingredient row - only if the field is still empty (a value
     * already entered is never overwritten) and only if a nutrition
     * entry exists at all. Prevents exactly the problem of aliased
     * ingredients with inconsistent units showing up as multiple
     * separate entries on the shopping list (see
     * services/ingredient_aliases.py). */
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
            if (!ok) { alert('Note: ' + (data.error || 'Could not save nutrition data.')); return; }
            NUTRITION[data.canonical_name] = data;
            renderHint(hintEl, name);
        })
        .catch(() => alert('Note: Could not save nutrition data.'));
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

    /** Nearest shared scope of an ingredient row: the enclosing <form>
     * (on recipe_form.html the only form on the page - unlike before,
     * when recipe_edit_list.html kept up to 50+ edit modals in the DOM
     * at once and an unthrottled document.querySelectorAll(...) on
     * EVERY focus change was noticeably visible as jank; the dedicated
     * page per recipe now makes this scoping unnecessary, but it
     * doesn't hurt as an extra safeguard). */
    function formScopeOf(el) {
        return el.closest('form') || document.body;
    }

    /** Clears the alias/nutrition hint of EVERY ingredient row of THE
     * SAME recipe except the one passed in - the hint (including any
     * "add nutrition data" box it may contain) should always be shown
     * on exactly ONE row at a time, namely the one currently
     * focused/being edited, instead of on all of them simultaneously
     * (which would quickly get confusing for an ingredient list with
     * many rows). */
    function clearOtherHints(exceptHintEl) {
        formScopeOf(exceptHintEl).querySelectorAll('.ingredient-alias-hint').forEach(el => {
            if (el !== exceptHintEl && el.innerHTML) el.innerHTML = '';
        });
    }

    /** Shows the hint for the currently focused name field (and clears
     * all others, see above) - both on an actual click into it and
     * when a click on the alias display (.ing-name-display, see
     * openIngredientNameField further below) programmatically focuses
     * the underlying <input>. 'focusin' instead of 'focus', since the
     * latter doesn't bubble and thus couldn't be delegated to
     * document.body. Deliberately NOT cleared on leaving the field
     * (blur/focusout): the hint box itself contains clickable buttons
     * ("Set alias", "Save nutrition data") - clearing on blur would
     * cause their click (blur fires BEFORE click) to hit nothing. The
     * hint therefore stays put until a DIFFERENT ingredient row is
     * focused. */
    document.body.addEventListener('focusin', event => {
        if (!event.target.matches('input[name="ing_name[]"]')) return;
        const hintEl = hintContainerFor(event.target);
        if (!hintEl) return;
        clearOtherHints(hintEl);
        renderHint(hintEl, titleCase(event.target.value));
    });

    /** For already-existing ingredient rows (recipe_form.html in edit
     * mode) shows by default the resolved alias name (pre-filled
     * server-side as .ing-name-display-<span>, see there) instead of
     * the actually stored name - only a click/keyboard activation
     * reveals the actual, editable <input> (whose value therefore
     * NEVER changes on its own).
     *
     * Entirely via event delegation on document/document.body (like
     * the rest of this file) instead of direct listeners per row - this
     * way a handful of listeners suffice for the ENTIRE page,
     * regardless of how many ingredient rows a recipe has or how many
     * of them are added later via rformAddIngredientRow().
     *
     * To close (revert back to the alias display) we deliberately do
     * NOT rely on the <input>'s blur event: that would require a click
     * on another element to take over focus - but some browsers
     * (especially Safari) only move keyboard focus on a click to actual
     * form fields, not to a plain <span>, so the previous field would
     * never reliably blur there. Instead, a genuine 'click' listener on
     * the entire document closes EVERY still-open field whose
     * ingredient row (.ingredient-row - deliberately the WHOLE row
     * including the alias/nutrition hint, not just the name column, so
     * a click on "Set alias"/"Save nutrition data" for the same row
     * doesn't accidentally close it too) does NOT contain the click -
     * regardless of whether the browser even considers a focus change
     * necessary for that. Via keyboard (Tab), the focusin listener
     * further below additionally covers the same case reliably, since
     * Tab triggers real focus events in every browser. */
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
        // formScopeOf() instead of document.querySelectorAll(...): this
        // listener fires on EVERY click anywhere on the page (not just
        // on ingredient fields), see comment at formScopeOf.
        formScopeOf(event.target).querySelectorAll('.ing-name-input:not(.d-none)').forEach(openInput => {
            const row = openInput.closest('.ingredient-row');
            if (row && !row.contains(event.target)) revertIngredientNameField(openInput);
        });
    });
    document.body.addEventListener('focusin', event => {
        revertAllOpenIngredientNames(event.target.matches('.ing-name-input') ? event.target : null, event.target);
    });
})();
