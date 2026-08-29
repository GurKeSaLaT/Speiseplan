/**
 * fuzzy_search.js - kleine, abhängigkeitsfreie Fuzzy-Suche für die
 * clientseitigen Listen-Filter (Rezepte bearbeiten, Kategorien verwalten,
 * Zutaten gleichsetzen): prüft, ob alle Zeichen der Sucheingabe in
 * DERSELBEN REIHENFOLGE, aber nicht zwingend zusammenhängend, im Zieltext
 * vorkommen - "ktfl" matcht z.B. "Kartoffeln", "rzsp" matcht "Rezeptsuppe".
 * Eine leere Sucheingabe matcht immer alles (kein Filter aktiv).
 *
 * Bewusst kein Scoring/Ranking (die Reihenfolge der Liste bleibt
 * unverändert, nur nicht passende Zeilen werden ausgeblendet) - für ein
 * einfaches "tippe irgendwas Ähnliches und die Liste schrumpft" reicht
 * das, ein echtes Ranking wäre für diese Listengrößen unnötiger Aufwand.
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
 * Verdrahtet ein Sucheingabefeld mit einer Menge von Zeilen: blendet bei
 * jeder Eingabe alle Zeilen aus, deren getText(row)-Ergebnis nicht (fuzzy)
 * auf die Eingabe passt. Nutzt die .search-hidden-Klasse statt
 * element.style.display direkt zu setzen (siehe style.css-Kommentar dort
 * für den Grund - Bootstraps .d-flex ist !important und würde einen
 * einfachen Inline-Style sonst überstimmen).
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
