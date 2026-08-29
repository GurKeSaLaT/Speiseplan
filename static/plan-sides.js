/**
 * plan-sides.js - Alles rund um Beilagen auf der Plan-Seite
 * (templates/plan.html): Rendern des Beilagen-Bereichs einer Tageskarte,
 * neue Beilagen hinzufügen (gewürfelt oder manuell ausgewählt), eine
 * bestehende Beilage neu würfeln/manuell ersetzen/entfernen, sowie das
 * Verschieben EINER einzelnen Beilage per Drag-and-Drop auf einen anderen
 * Tag (unabhängig vom kompletten Tages-Tausch, der in static/plan.js
 * lebt).
 *
 * Nutzt gemeinsame Infrastruktur aus den anderen plan-*.js-Dateien:
 * weeklySideRecipes/dayDates/postWithCsrf (siehe static/plan.js),
 * buildManualSelectHtml/wireManualSelectBox (siehe
 * static/plan-manual-select.js) und rebuildShoppingList (siehe
 * static/plan-shopping.js) - alle drei müssen VOR oder NACH dieser Datei
 * eingebunden sein (die Reihenfolge der <script>-Tags in plan.html spielt
 * hier keine Rolle, da diese Datei ihre Funktionen nur deklariert, aber
 * nichts davon beim Laden sofort AUFRUFT - erst spätere Nutzerinteraktionen
 * tun das, wenn längst alle Skripte geladen sind).
 */

/**
 * Baut den kompletten Beilagen-Bereich einer Tageskarte auf: eine Zeile
 * pro aktuell zugewiesener Beilage (jeweils mit eigenem Drag-Handle für
 * moveSideDish sowie 🎲/✏️/❌-Buttons für genau DIESEN Slot) plus eine
 * abschließende "Beilage hinzufügen"-Zeile (🎲 würfelt eine neue zufällige
 * Beilage dazu, ✏️ öffnet die manuelle Auswahl für einen NEUEN Slot). Jede
 * Zeile bekommt eine eigene id (side-item-<dayIndex>-<sideId> bzw.
 * side-add-row-<dayIndex>), über die openSideManualSelect() gezielt genau
 * diese eine Zeile durch die Auswahlbox ersetzen kann.
 */
function renderSidesSection(dayIndex) {
    const sides = weeklySideRecipes[dayIndex] || [];
    let html = '';
    sides.forEach(side => {
        const cookedClass = side.cooked ? ' dish-cooked' : '';
        html += `
            <div class="d-flex justify-content-between align-items-center side-dish-card mb-1"
                 id="side-item-${dayIndex}-${side.side_id}"
                 draggable="true"
                 ondragstart="sideDragStart(event, ${dayIndex}, ${side.side_id})">
                <div class="dish-clickable${cookedClass}" role="button" title="Details anzeigen" onclick="openRecipeDetail(${dayIndex}, ${side.side_id})">
                    <span class="fw-bold text-dark side-dish-name">🥗 ${side.name}</span>
                    <span class="badge badge-category side-dish-category ms-1">${side.category_name}</span>
                    <span class="text-muted small side-dish-kcal">(${side.calories} kcal)</span>
                </div>
                <div class="d-flex align-items-center gap-1">
                    <button type="button" class="btn btn-sm btn-outline-secondary border-0 p-1" title="Diese Beilage neu würfeln" onclick="rerollOneSide(${dayIndex}, ${side.side_id})">🎲</button>
                    <button type="button" class="btn btn-sm btn-outline-secondary border-0 p-1" title="Andere Beilage auswählen" onclick="openSideManualSelect(${dayIndex}, ${side.side_id})">✏️</button>
                    <button type="button" class="btn btn-sm text-danger border-0 p-1" title="Beilage entfernen" onclick="removeOneSide(${dayIndex}, ${side.side_id})">❌</button>
                </div>
            </div>
        `;
    });
    html += `
        <div id="side-add-row-${dayIndex}" class="d-flex gap-1">
            <button type="button" class="btn btn-sm btn-outline-secondary flex-grow-1" onclick="addRandomSide(${dayIndex})">🎲 Beilage würfeln</button>
            <button type="button" class="btn btn-sm btn-outline-secondary" title="Beilage auswählen" onclick="openSideManualSelect(${dayIndex}, null)">✏️</button>
        </div>
    `;
    return html;
}

/** Rendert nur den Beilagen-Bereich einer Tageskarte neu (side-row-<dayIndex>), ohne Personenzeile/Hauptgericht anzutasten. */
function refreshSidesSection(dayIndex) {
    const container = document.getElementById(`side-row-${dayIndex}`);
    if (container) container.innerHTML = renderSidesSection(dayIndex);
}

/**
 * Öffnet die manuelle Beilagenauswahl-Box: entweder ANSTELLE einer
 * bestehenden Beilagen-Zeile (sideId gesetzt - ersetzt genau diesen Slot,
 * siehe setOneSide) oder ANSTELLE der "Hinzufügen"-Zeile (sideId null -
 * legt einen NEUEN Slot an, siehe addSide). Beide Fälle nutzen denselben
 * Mechanismus: die Ziel-Zeile per id finden, ihr aktuelles Markup merken,
 * gegen die Auswahlbox (siehe static/plan-manual-select.js) tauschen. Nach
 * einer erfolgreichen Auswahl rendert refreshSidesSection() ohnehin den
 * kompletten Bereich neu (siehe addSide/setOneSide), ein manuelles
 * Wiederherstellen bei Erfolg ist daher nicht nötig - nur bei "Abbrechen".
 */
function openSideManualSelect(dayIndex, sideId) {
    const container = sideId
        ? document.getElementById(`side-item-${dayIndex}-${sideId}`)
        : document.getElementById(`side-add-row-${dayIndex}`);
    if (!container) return;

    const previousHtml = container.innerHTML;
    container.innerHTML = buildManualSelectHtml(true);
    wireManualSelectBox(
        container, true,
        (recipeId) => {
            if (sideId) {
                setOneSide(dayIndex, sideId, recipeId);
            } else {
                addSide(dayIndex, recipeId);
            }
        },
        () => { container.innerHTML = previousHtml; }
    );
}

/**
 * Legt eine NEUE Beilage für einen Tag an (ruft serverseitig
 * routes/plan/day_actions.py: add_side() auf) - zusätzlich zu bereits
 * vorhandenen, ein Tag kann beliebig viele haben. recipeId ist optional:
 * gesetzt (manuelle Auswahl über ✏️) wird genau dieses Rezept übernommen,
 * fehlt es (🎲-Button), würfelt der Server zufällig unter Berücksichtigung
 * von Wochen-Dubletten und der weichen Wiederholungs-Gewichtung.
 */
function addSide(dayIndex, recipeId) {
    postWithCsrf(`/day/${dayDates[dayIndex]}/side/add`, {
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ recipe_id: recipeId || null }),
    })
    .then(response => {
        if (!response.ok) return response.json().then(data => { throw new Error(data.error || 'Keine Beilage verfügbar.'); });
        return response.json();
    })
    .then(newSide => {
        weeklySideRecipes[dayIndex].push(newSide);
        refreshSidesSection(dayIndex);
        rebuildShoppingList();
    })
    .catch(err => {
        alert('Hinweis: ' + err.message);
    });
}

/** Kurzer Alias für den 🎲-Button der "Beilage hinzufügen"-Zeile - würfelt eine neue Beilage ohne manuelle Auswahl. */
function addRandomSide(dayIndex) {
    addSide(dayIndex, null);
}

/**
 * Würfelt EINE bestehende Beilage neu (ersetzt sie durch ein anderes,
 * zufällig gewähltes Rezept - im Gegensatz zu addSide, das einen
 * ZUSÄTZLICHEN Slot anlegt). sideId identifiziert die PlanDaySide-Zeile,
 * nicht das Rezept.
 */
function rerollOneSide(dayIndex, sideId) {
    postWithCsrf(`/day/${dayDates[dayIndex]}/side/${sideId}/reroll`)
    .then(response => {
        if (!response.ok) return response.json().then(data => { throw new Error(data.error || 'Keine Alternative verfügbar.'); });
        return response.json();
    })
    .then(newSide => {
        const idx = weeklySideRecipes[dayIndex].findIndex(s => s.side_id === sideId);
        if (idx !== -1) weeklySideRecipes[dayIndex][idx] = newSide;
        refreshSidesSection(dayIndex);
        rebuildShoppingList();
    })
    .catch(err => {
        alert('Hinweis: ' + err.message);
    });
}

/** Ersetzt EINE bestehende Beilage durch ein vom Nutzer manuell gewähltes Rezept (das manuelle Pendant zu rerollOneSide). */
function setOneSide(dayIndex, sideId, recipeId) {
    postWithCsrf(`/day/${dayDates[dayIndex]}/side/${sideId}/set`, {
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ recipe_id: recipeId }),
    })
    .then(response => {
        if (!response.ok) return response.json().then(data => { throw new Error(data.error || 'Auswahl fehlgeschlagen.'); });
        return response.json();
    })
    .then(newSide => {
        const idx = weeklySideRecipes[dayIndex].findIndex(s => s.side_id === sideId);
        if (idx !== -1) weeklySideRecipes[dayIndex][idx] = newSide;
        refreshSidesSection(dayIndex);
        rebuildShoppingList();
    })
    .catch(err => {
        alert('Hinweis: ' + err.message);
    });
}

/** Entfernt EINE bestehende Beilage endgültig, ohne die übrigen Beilagen desselben Tages anzutasten. */
function removeOneSide(dayIndex, sideId) {
    postWithCsrf(`/day/${dayDates[dayIndex]}/side/${sideId}/remove`)
    .then(response => {
        if (!response.ok) throw new Error('Entfernen fehlgeschlagen.');
    })
    .then(() => {
        weeklySideRecipes[dayIndex] = weeklySideRecipes[dayIndex].filter(s => s.side_id !== sideId);
        refreshSidesSection(dayIndex);
        rebuildShoppingList();
    })
    .catch(err => {
        alert('Hinweis: ' + err.message);
    });
}

// --- EINZELNE BEILAGE PER DRAG-AND-DROP VERSCHIEBEN ---
// Siehe static/plan.js für den kompletten Tages-Tausch (ganze Karte ziehen)
// und den gemeinsamen dayCardDrop()-Handler, der anhand der im DataTransfer
// codierten {type: 'side', ...}-Payload hierher (moveSideDish) verzweigt.

/** Merkt beim Start des Ziehens EINER Beilagen-Zeile deren Herkunft (Tag + PlanDaySide-ID) im DataTransfer. stopPropagation verhindert, dass zusätzlich (redundant) auch noch dayCardDragStart der umschließenden Karte feuert. */
function sideDragStart(event, dayIndex, sideId) {
    event.dataTransfer.setData('text/plain', JSON.stringify({ type: 'side', dayIndex: dayIndex, sideId: sideId }));
    event.stopPropagation();
}

/**
 * Verschiebt EINE einzelne Beilage von sourceDayIndex zu targetDayIndex
 * (ruft serverseitig routes/plan/day_actions.py: move_one_side() auf) -
 * ein einseitiges Verschieben, kein Tausch: der Zieltag behält alles, was
 * er bereits hatte, und bekommt die Beilage zusätzlich. Aktualisiert nach
 * Erfolg beide betroffenen Beilagen-Bereiche (nicht die ganze Karte, das
 * Hauptgericht bleibt ja unangetastet). Wird von static/plan.js:
 * dayCardDrop() aufgerufen.
 */
function moveSideDish(sourceDayIndex, sideId, targetDayIndex) {
    if (sourceDayIndex === targetDayIndex) return;

    postWithCsrf(`/day/${dayDates[sourceDayIndex]}/side/${sideId}/move/${dayDates[targetDayIndex]}`)
    .then(response => {
        if (!response.ok) throw new Error('Verschieben fehlgeschlagen.');
        return response.json();
    })
    .then(movedSide => {
        weeklySideRecipes[sourceDayIndex] = weeklySideRecipes[sourceDayIndex].filter(s => s.side_id !== sideId);
        weeklySideRecipes[targetDayIndex].push(movedSide);
        refreshSidesSection(sourceDayIndex);
        refreshSidesSection(targetDayIndex);
        rebuildShoppingList();
    })
    .catch(err => {
        alert('Hinweis: ' + err.message);
    });
}
