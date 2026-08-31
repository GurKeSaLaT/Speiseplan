/**
 * fuzzy_search.js - small, dependency-free fuzzy search for the
 * client-side list filters (edit recipes, manage categories, equate
 * ingredients): checks whether all characters of the search input occur
 * in the target text in THE SAME ORDER, but not necessarily contiguous -
 * e.g. "ptt" matches "Potatoes", "rcpsp" matches "Recipe Soup".
 * An empty search input always matches everything (no filter active).
 *
 * Deliberately no scoring/ranking (the order of the list stays
 * unchanged, only non-matching rows are hidden) - for a simple "type
 * something similar and the list shrinks" this is enough; real ranking
 * would be unnecessary effort for these list sizes.
 */
function fuzzyMatch(text, query) {
    if (!query) return true;
    text = text.toLowerCase();
    query = query.toLowerCase();

    let textIndex = 0;
    for (let i = 0; i < query.length; i++) {
        textIndex = text.indexOf(query[i], textIndex);
        if (textIndex === -1) return false;
        textIndex++;
    }
    return true;
}

/**
 * Wires up a search input field with a set of rows: on every input,
 * hides all rows whose getText(row) result does not (fuzzy) match the
 * input. Uses the .search-hidden class instead of setting
 * element.style.display directly (see the style.css comment there for
 * the reason - Bootstrap's .d-flex is !important and would otherwise
 * override a simple inline style).
 */
function wireFuzzyFilter(inputEl, rowSelector, getText) {
    if (!inputEl) return;
    inputEl.addEventListener('input', () => {
        const query = inputEl.value.trim();
        document.querySelectorAll(rowSelector).forEach(row => {
            row.classList.toggle('search-hidden', !fuzzyMatch(getText(row), query));
        });
    });
}
