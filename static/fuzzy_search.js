/**
 * Subsequence match for list filters: all query characters must appear in
 * order, not necessarily adjacent ("ptt" matches "Potatoes"). No ranking;
 * non-matching rows are just hidden.
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

/** Rows are queried on every input, so rows added later are filtered too.
 * Uses the .search-hidden class: an inline display style would lose against
 * Bootstrap's !important .d-flex. */
function wireFuzzyFilter(inputEl, rowSelector, getText) {
    if (!inputEl) return;
    inputEl.addEventListener('input', () => {
        const query = inputEl.value.trim();
        document.querySelectorAll(rowSelector).forEach(row => {
            row.classList.toggle('search-hidden', !fuzzyMatch(getText(row), query));
        });
    });
}
