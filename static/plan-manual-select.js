/**
 * plan-manual-select.js - Wiederverwendbare "manuell auswählen"-Suchbox für
 * die Plan-Seite (templates/plan.html): eine kleine Live-Suche über alle
 * Rezepte, die eine Aufrufer-Stelle im DOM ersetzt (statt eines separaten
 * Modals/Dialogs) und bei Auswahl/Abbrechen einen übergebenen Callback
 * aufruft.
 *
 * Bewusst als generische, von "Hauptgericht" oder "Beilage" unabhängige
 * Komponente geschrieben: sowohl die Hauptgericht-Auswahl (openMainManualSelect
 * in static/plan.js) als auch die Beilagen-Auswahl (openSideManualSelect in
 * static/plan-sides.js) rufen dieselben zwei Funktionen hier auf, statt
 * eigene, fast identische Suchboxen zu pflegen.
 *
 * Erwartet, dass die globale Konstante `allRecipes` (siehe static/plan.js)
 * bereits gesetzt ist, wenn eine der beiden Funktionen aufgerufen wird -
 * bei normaler Seitenladereihenfolge (dieses Skript nach plan.js eingebunden)
 * ist das immer der Fall, da beide Funktionen erst durch einen Klick
 * ausgelöst werden, also lange nach dem initialen Laden.
 */

/**
 * Baut die HTML-Struktur der Suchbox: ein Textfeld, eine (zunächst leere,
 * versteckte) Ergebnisliste und ein "Abbrechen"-Link. isSide bestimmt nur
 * den Platzhaltertext ("Beilage suchen..." vs. "Rezept suchen...") - die
 * eigentliche Filterung nach Hauptgericht/Beilage passiert in
 * wireManualSelectBox().
 */
function buildManualSelectHtml(isSide) {
    return `
        <div class="manual-select-box">
            <input type="text" class="form-control form-control-sm manual-select-input mb-1" placeholder="${isSide ? 'Beilage' : 'Rezept'} suchen..." autocomplete="off">
            <div class="list-group manual-select-results shadow-sm" style="max-height: 180px; overflow-y: auto; display: none;"></div>
            <button type="button" class="btn btn-sm btn-link p-0 mt-1 manual-select-cancel">Abbrechen</button>
        </div>
    `;
}

/**
 * Verdrahtet eine per buildManualSelectHtml() erzeugte Box: filtert
 * allRecipes bei jedem Tastendruck nach Name/Kategorie (übereinstimmend
 * mit is_side_dish === isSide), rendert Treffer als klickbare Zeilen und
 * ruft bei einem Klick onSelect(recipeId) auf. Der "Abbrechen"-Button ruft
 * stattdessen onCancel() auf (typischerweise: die Box wieder gegen die
 * vorherige Anzeige tauschen). container muss bereits das Markup aus
 * buildManualSelectHtml() enthalten.
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
