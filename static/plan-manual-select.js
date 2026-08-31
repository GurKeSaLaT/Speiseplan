/**
 * plan-manual-select.js - reusable "select manually" search box for the
 * plan page (templates/plan.html): a small live search across all
 * recipes that replaces a caller's location in the DOM (instead of a
 * separate modal/dialog) and calls a passed-in callback on
 * selection/cancel.
 *
 * Deliberately written as a generic component, independent of "main
 * dish" or "side dish": both the main dish selection (openMainManualSelect
 * in static/plan.js) and the side dish selection (openSideManualSelect in
 * static/plan-sides.js) call the same two functions here, instead of
 * each maintaining their own, nearly identical search boxes.
 *
 * Expects the global constant `allRecipes` (see static/plan.js) to
 * already be set by the time either function is called - under normal
 * page load order (this script included after plan.js) this is always
 * the case, since both functions are only triggered by a click, i.e.
 * long after the initial load.
 */

/**
 * Builds the HTML structure of the search box: a text field, a
 * (initially empty, hidden) results list, and a "Cancel" link. isSide
 * only determines the placeholder text ("Search side dish..." vs.
 * "Search recipe...") - the actual filtering by main dish/side dish
 * happens in wireManualSelectBox().
 */
function buildManualSelectHtml(isSide) {
    return `
        <div class="manual-select-box">
            <input type="text" class="form-control form-control-sm manual-select-input mb-1" placeholder="Search ${isSide ? 'side dish' : 'recipe'}..." autocomplete="off">
            <div class="list-group manual-select-results shadow-sm" style="max-height: 180px; overflow-y: auto; display: none;"></div>
            <button type="button" class="btn btn-sm btn-link p-0 mt-1 manual-select-cancel">Cancel</button>
        </div>
    `;
}

/**
 * Wires up a box created via buildManualSelectHtml(): filters allRecipes
 * on every keystroke by name/category (matching is_side_dish === isSide),
 * renders hits as clickable rows and calls onSelect(recipeId) on click.
 * The "Cancel" button calls onCancel() instead (typically: swapping the
 * box back for the previous display). container must already contain the
 * markup from buildManualSelectHtml().
 */
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
