/**
 * Filter matching for list searches. The searchable text holds one term per
 * line (e.g. an ingredient and each of its aliases); terms are never matched
 * across each other. Every whitespace-separated query word must match some
 * term:
 * - as a substring (1-2 letter words only at the start of a word), or
 * - as a typo-tolerant subsequence inside ONE word that starts with the same
 *   letter and skips at most one letter between hits ("ptt" -> "Potatoes",
 *   "zwibel" -> "Zwiebel"), for query words of 3+ letters.
 * No ranking; non-matching rows are just hidden.
 */
const SEARCH_WORD_SEPARATORS = /[\s\-\/,;.()&+]+/;
const SEARCH_MAX_SKIPPED_LETTERS = 1;

function normalizeSearchText(text) {
    // Strips accents too, so "creme" finds "Crème".
    return text.toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '');
}

function isCloseSubsequence(word, queryWord) {
    if (word[0] !== queryWord[0]) return false;
    let wordIndex = 0;
    for (let i = 1; i < queryWord.length; i++) {
        const next = word.indexOf(queryWord[i], wordIndex + 1);
        if (next === -1 || next - wordIndex - 1 > SEARCH_MAX_SKIPPED_LETTERS) return false;
        wordIndex = next;
    }
    return true;
}

function termMatchesQueryWord(term, words, queryWord) {
    if (queryWord.length < 3) return words.some(word => word.startsWith(queryWord));
    if (term.includes(queryWord)) return true;
    return words.some(word => isCloseSubsequence(word, queryWord));
}

function fuzzyMatch(text, query) {
    const queryWords = normalizeSearchText(query || '').split(/\s+/).filter(Boolean);
    if (queryWords.length === 0) return true;

    const terms = normalizeSearchText(text || '').split('\n').map(term => term.trim()).filter(Boolean)
        .map(term => ({ term, words: term.split(SEARCH_WORD_SEPARATORS).filter(Boolean) }));

    return queryWords.every(queryWord =>
        terms.some(({ term, words }) => termMatchesQueryWord(term, words, queryWord))
    );
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
