/**
 * Inline recipe search box used for manually picking main dishes and
 * sides on the plan page. It replaces part of the card instead of
 * opening a dialog. Searches plan.js's allRecipes.
 */
function buildManualSelectHtml(isSide) {
    const placeholder = isSide ? window.I18N.search_placeholder_side : window.I18N.search_placeholder_recipe;
    return `
        <div class="manual-select-box">
            <input type="text" class="form-control form-control-sm manual-select-input mb-1" placeholder="${placeholder}" autocomplete="off">
            <div class="list-group manual-select-results shadow-sm" style="max-height: 180px; overflow-y: auto; display: none;"></div>
            <button type="button" class="btn btn-sm btn-link p-0 mt-1 manual-select-cancel">${window.I18N.cancel_label}</button>
        </div>
    `;
}

/** Filters by name/category within main dishes or sides (isSide); calls
 * onSelect(recipeId) or onCancel(). */
function wireManualSelectBox(container, isSide, onSelect, onCancel) {
    const input = container.querySelector('.manual-select-input');
    const results = container.querySelector('.manual-select-results');
    const cancelBtn = container.querySelector('.manual-select-cancel');

    input.addEventListener('input', () => {
        const query = input.value.toLowerCase().trim();
        results.innerHTML = '';
        if (!query) {
            results.style.display = 'none';
            return;
        }
        const matches = allRecipes.filter(r =>
            r.is_side_dish === isSide &&
            (r.name.toLowerCase().includes(query) || r.category_name.toLowerCase().includes(query))
        ).slice(0, 20);

        matches.forEach(r => {
            const item = document.createElement('button');
            item.type = 'button';
            item.className = 'list-group-item list-group-item-action d-flex justify-content-between align-items-center py-1 px-2';
            const nameSpan = document.createElement('span');
            nameSpan.className = 'fw-bold text-dark small';
            nameSpan.textContent = r.name;
            const catBadge = document.createElement('span');
            catBadge.className = 'badge badge-category';
            catBadge.textContent = r.category_name;
            item.appendChild(nameSpan);
            item.appendChild(catBadge);
            item.addEventListener('click', () => onSelect(r.id));
            results.appendChild(item);
        });
        results.style.display = matches.length ? 'block' : 'none';
    });

    cancelBtn.addEventListener('click', onCancel);
    input.focus();
}
