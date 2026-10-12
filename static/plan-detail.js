/**
 * Plan page: read-only recipe detail window. One reused modal, filled from
 * the recipe objects already in memory (plan.js state).
 */

// Which dish the open window belongs to, for toggleDetailCooked().
let detailDayIndex = null;
let detailSideId = null;

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
        ? `<h6 class="fw-bold text-dark mt-3 mb-1">${escapeHtml(window.I18N.instructions_heading)}</h6><p class="mb-0" style="white-space: pre-line;">${renderInstructionParts(recipe, factor)}</p>`
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
            📊 ${recipe.calories} kcal | ${escapeHtml(macroLine(recipe.protein, recipe.carbs, recipe.fat))} <span class="text-muted">${escapeHtml(window.I18N.per_serving)}</span>
        </div>
        <h6 class="fw-bold text-dark mb-1">🛒 ${escapeHtml(window.I18N.ingredients_word)}</h6>
        ${ingredientsHtml}
        ${instructionsHtml}
        ${sourceHtml}
    `;
}

// Units that read better as a bare count in running text ("2 Eier").
const COUNT_UNITS = new Set(['', 'st', 'st.', 'stk', 'stk.', 'stück']);

/** "200 g", "2" (count units), or "" when the line has no amount. */
function formatPlaceholderAmount(ingredient, factor) {
    const amount = roundedAmount({ amount: ingredient.amount * factor });
    if (!amount) return '';
    const unit = (ingredient.unit || '').trim();
    if (!unit) return `${amount}`;
    // A literal's unit is whatever was written ("{12 Stück}"), so keep it.
    return !ingredient.literal && COUNT_UNITS.has(unit.toLowerCase()) ? `${amount}` : `${amount} ${unit}`;
}

/** Instructions as escaped HTML with every placeholder replaced by its
 * ingredient's amount, scaled like the ingredient list (factor) and by the
 * placeholder's own share. Parts come from the server
 * (services/instruction_placeholders.py); unknown ones are plain text. */
function renderInstructionParts(recipe, factor) {
    const parts = recipe.instruction_parts || [{ text: recipe.instructions || '' }];
    return parts.map(part => {
        if (part.text !== undefined) return escapeHtml(part.text);
        // A literal amount like {500 ml}: scaled as written, unit kept.
        const ingredient = part.amount !== undefined
            ? { amount: part.amount, unit: part.unit, literal: true }
            : recipe.ingredients[part.ing];
        if (!ingredient) return escapeHtml(part.raw || '');
        const amount = formatPlaceholderAmount(ingredient, part.amount !== undefined ? factor : part.factor * factor);
        return amount ? `<strong class="instruction-amount">${escapeHtml(amount)}</strong>` : '';
    }).join('');
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
