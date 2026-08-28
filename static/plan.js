/**
 * plan.js - Client-seitige Logik der Wochenplan-Ansicht (templates/plan.html).
 *
 * Verantwortlich für ALLES auf der Plan-Seite, inklusive dem erstmaligen
 * Aufbau der 7 Tageskarten (siehe DOMContentLoaded ganz unten in diesem
 * Abschnitt - anders als früher liefert Jinja nur noch leere Karten-Hüllen):
 * Hauptgericht würfeln ODER manuell auswählen, Beilagen hinzufügen
 * (gewürfelt oder manuell) in beliebiger Anzahl pro Tag, einzelne Beilagen
 * neu würfeln/manuell ersetzen/entfernen, zwei Tageskarten komplett
 * tauschen (Beilagen wandern dabei mit), eine einzelne Beilage per
 * Drag-and-Drop auf einen ANDEREN Tag verschieben, die Personenzahl pro Tag
 * ändern, manuelle Einkaufslisten-Artikel hinzufügen/entfernen, sowie die
 * daraus abgeleiteten Übersichten (Wochen-Nährwerte, nach Supermarkt-
 * Kategorie gruppierte Einkaufsliste) live neu berechnen - alles ohne die
 * Seite neu zu laden.
 *
 * Jede Aktion, die den Plan verändert, schickt zuerst einen fetch()-Request
 * an den Server (siehe routes/plan.py), der die Änderung in der Datenbank
 * persistiert - erst wenn die Antwort erfolgreich war, wird auch der lokale
 * JavaScript-Speicher und das DOM aktualisiert. Ein Fehlschlag (z.B. "keine
 * Alternative verfügbar") führt NICHT zu einer optimistischen, dann wieder
 * zurückgerollten UI-Änderung, sondern zu einem alert() und sonst nichts -
 * der bisherige Zustand bleibt unverändert sichtbar.
 *
 * Erwartet, dass window.PLAN_DATA (siehe plan.html, per Jinja tojson-Filter
 * sicher aus Python-Daten erzeugt) VOR diesem Script im DOM gesetzt wurde.
 */

// Wochentag-Beschriftungen ("Montag", "Dienstag", ...) und die zugehörigen
// ISO-Datumsstrings (z.B. "2026-08-31") - beide Arrays sind über den Index
// (0 = erster Wochentag) miteinander und mit den weiteren Arrays unten
// verknüpft und ändern sich nach dem initialen Laden nicht mehr (nur ihr
// Inhalt an den jeweiligen Indizes über dayServings/weeklyPlanRecipes/... -
// ein Tage-Tausch tauscht z.B. NICHT die dayDates, sondern die Rezepte an
// den bestehenden Datums-Indizes).
const dayLabels = window.PLAN_DATA.dayLabels;
const dayDates = window.PLAN_DATA.weekDates;

// ALLE Rezepte (unabhängig vom aktuellen Plan) in schlanker Form
// ({id, name, category_name, is_side_dish}) - Grundlage für die manuelle
// Rezeptauswahl-Suche (siehe buildManualSelectHtml/wireManualSelectBox
// weiter unten). Ändert sich nach dem Laden der Seite nicht mehr; ein neu
// angelegtes Rezept taucht dort erst nach einem Neuladen auf.
const allRecipes = window.PLAN_DATA.allRecipes || [];

// Ob ein Tag bewusst von der automatischen Planung ausgenommen wurde
// (Checkbox auf der Erstellen-Seite). Wird beim Tage-Tausch mitgetauscht,
// da ein "ausgenommener Tag" eine Eigenschaft des Kalendertags ist (z.B.
// "wir essen dienstags immer auswärts"), nicht des zufällig dort
// gelandeten Gerichts.
let dayExcluded = window.PLAN_DATA.excludedDays;

// Für wie viele Personen an jedem Wochentag eingekauft werden soll (Index = Wochentag,
// aus der Datenbank vorbefüllt). Bleibt an den Wochentag gebunden, nicht ans Gericht -
// wandert beim Tage-Tausch also NICHT mit.
let dayServings = window.PLAN_DATA.servingsList;

// Rezepte im JavaScript-Speicher (Index = Wochentag, null = kein Rezept).
// Dies ist die "Quelle der Wahrheit" für alles, was clientseitig aus dem
// Plan berechnet wird (Nährwertsumme, Einkaufsliste) - nach jeder
// erfolgreichen serverseitigen Änderung wird dieses Array aktualisiert,
// damit diese Berechnungen ohne Seiten-Reload konsistent bleiben.
let weeklyPlanRecipes = window.PLAN_DATA.plan;

// Zusatzgerichte/Beilagen (Index = Wochentag, Wert = LISTE von
// Rezept-Objekten - ein Tag kann beliebig viele Beilagen gleichzeitig
// haben, siehe models.py: PlanDaySide). Jedes Beilagen-Objekt hat
// zusätzlich zu den normalen Rezeptfeldern ein side_id-Feld: die ID der
// PlanDaySide-Zeile selbst (NICHT des Rezepts), über die eine einzelne
// Beilage gezielt neu gewürfelt/ersetzt/entfernt/verschoben wird - siehe
// rerollOneSide/setOneSide/removeOneSide/moveSideDish weiter unten.
let weeklySideRecipes = window.PLAN_DATA.sidePlan;

// Manuell zur Einkaufsliste dieser Woche hinzugefügte Artikel, die zu keinem
// Rezept gehören (z.B. Hygieneartikel) - jeder Eintrag ist ein Objekt
// {id, name, amount, unit, category} und wurde bereits serverseitig
// persistiert (siehe routes/plan.py: add_shopping_item). Anders als
// weeklyPlanRecipes/weeklySideRecipes NICHT nach Wochentag indiziert,
// sondern eine flache Liste - ein manueller Artikel gehört der Woche als
// Ganzes, keinem bestimmten Tag.
let weeklyExtraItems = window.PLAN_DATA.extraItems || [];

// Beim ersten Laden der Seite alle 7 Tageskarten (siehe renderDayCardBody
// weiter unten - Jinja liefert in plan.html nur noch leere Karten-Hüllen)
// sowie die Einkaufsliste (und darüber auch die Wochen-Nährwertübersicht,
// siehe rebuildShoppingList) aus den bereits vom Server mitgelieferten
// Daten aufbauen - ab dann übernehmen die einzelnen Aktionen unten das
// Neu-Berechnen bei jeder Änderung. refreshDayCard/rebuildShoppingList
// brechen selbst früh ab, wenn die jeweiligen Container gar nicht im DOM
// existieren (z.B. weil diese Woche noch gar keinen Plan hat) - dieser
// Aufruf ist daher auch in dem Fall gefahrlos.
document.addEventListener('DOMContentLoaded', () => {
    for (let i = 0; i < 7; i++) {
        refreshDayCard(i);
    }
    rebuildShoppingList();
});

/**
 * Führt einen POST-fetch()-Request aus und ergänzt dabei automatisch den
 * X-CSRFToken-Header (aus window.CSRF_TOKEN, siehe base.html) - alle
 * schreibenden Endpunkte sind serverseitig per Flask-WTF CSRFProtect
 * abgesichert (siehe app.py) und lehnen POSTs ohne gültiges Token ab.
 * Zusätzliche fetch()-Optionen (z.B. ein JSON-Body samt eigenem
 * Content-Type-Header) können über extraOptions ergänzt werden, ohne den
 * CSRF-Header jedes Mal von Hand mitschreiben zu müssen.
 */
function postWithCsrf(url, extraOptions = {}) {
    return fetch(url, {
        method: 'POST',
        ...extraOptions,
        headers: {
            'X-CSRFToken': window.CSRF_TOKEN,
            ...(extraOptions.headers || {}),
        },
    });
}

/**
 * Würfelt das Hauptgericht eines einzelnen Tages neu (ruft serverseitig
 * reroll_day() in routes/plan.py auf, welche eine zufällige Alternative aus
 * derselben Kategorie wählt, die weder in dieser Woche noch in den
 * category-Nachbartagen bereits vorkommt). Bei Erfolg werden sowohl die
 * Tageskarte im DOM als auch der lokale weeklyPlanRecipes-Speicher und die
 * Einkaufsliste aktualisiert; bei Misserfolg (keine Alternative verfügbar)
 * bleibt alles unverändert und der Nutzer bekommt eine Fehlermeldung.
 */
function rerollSingleDay(dayIndex) {
    const dayCard = document.getElementById(`day-card-${dayIndex}`);
    if (!dayCard) return;

    postWithCsrf(`/day/${dayDates[dayIndex]}/reroll-main`)
    .then(response => {
        if (!response.ok) return response.json().then(data => { throw new Error(data.error || 'Kein alternatives Rezept verfügbar.'); });
        return response.json();
    })
    .then(newRecipe => {
        // 1. HTML-Anzeige des Wochentags aktualisieren
        dayCard.setAttribute('data-recipe-id', newRecipe.id);
        dayCard.setAttribute('data-category-id', newRecipe.category_id);

        dayCard.querySelector('.recipe-name').textContent = newRecipe.name;
        dayCard.querySelector('.recipe-category').textContent = newRecipe.category_name;
        dayCard.querySelector('.recipe-kcal').textContent = newRecipe.calories;
        dayCard.querySelector('.recipe-protein').textContent = newRecipe.protein;
        dayCard.querySelector('.recipe-carbs').textContent = newRecipe.carbs;
        dayCard.querySelector('.recipe-fat').textContent = newRecipe.fat;

        // 2. JavaScript-Speicher aktualisieren
        weeklyPlanRecipes[dayIndex] = newRecipe;

        // 3. Einkaufsliste live neu berechnen
        rebuildShoppingList();
    })
    .catch(err => {
        alert('Hinweis: ' + err.message);
    });
}

/**
 * Baut die <option>-freie Trefferliste für die manuelle Rezeptauswahl-Box:
 * eine kleine "Suchen..."-Eingabe + Live-Ergebnisliste (analog zur
 * Rezeptsuche auf create_week.html, aber als wiederverwendbare Komponente
 * für beliebig viele Stellen auf DIESER Seite - Hauptgericht UND jede
 * einzelne Beilage bekommen jeweils ihre eigene). isSide filtert
 * allRecipes auf Beilagen (true) oder Hauptgerichte (false).
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

/**
 * Baut den Hauptgericht-Anzeigebereich einer Tageskarte auf: entweder das
 * zugewiesene Rezept mit 🎲 (neu würfeln) + ✏️ (manuell auswählen), oder
 * einen Platzhaltertext (ausgenommen bzw. kein passendes Rezept gefunden)
 * mit einem eigenständigen "Rezept auswählen"-Button - die manuelle
 * Auswahl bleibt so auch dann erreichbar, wenn die automatische Planung
 * an diesem Tag nichts gefunden hat oder der Tag ausgenommen wurde (die
 * Auswahl hebt eine Ausnahme automatisch wieder auf, siehe
 * routes/plan.py: set_main_day).
 */
function renderMainDisplay(dayIndex) {
    const recipe = weeklyPlanRecipes[dayIndex];
    if (recipe) {
        return `
            <div class="d-flex justify-content-between align-items-start mb-2">
                <div>
                    <h5 class="text-success fw-bold mb-0" style="color: var(--primary-food) !important;">${dayLabels[dayIndex]}</h5>
                    <span class="recipe-name fw-bold fs-5 text-dark d-block mt-1">${recipe.name}</span>
                </div>
                <div class="d-flex align-items-center gap-1">
                    <span class="badge badge-category recipe-category px-3 py-2 rounded-pill">${recipe.category_name}</span>
                    <button type="button" class="btn btn-sm btn-outline-secondary border-0 p-2 fs-5" title="Diesen Tag neu würfeln" onclick="rerollSingleDay(${dayIndex})">🎲</button>
                    <button type="button" class="btn btn-sm btn-outline-secondary border-0 p-2 fs-5" title="Anderes Rezept auswählen" onclick="openMainManualSelect(${dayIndex})">✏️</button>
                </div>
            </div>
            <div class="text-muted small font-monospace bg-light p-2 rounded">
                📊 <span class="recipe-kcal">${recipe.calories}</span> kcal |
                E: <span class="recipe-protein">${recipe.protein}</span>g |
                K: <span class="recipe-carbs">${recipe.carbs}</span>g |
                F: <span class="recipe-fat">${recipe.fat}</span>g
            </div>
        `;
    }
    // Zwei mögliche Gründe für ein leeres Hauptgericht: der Tag wurde
    // bewusst ausgenommen (Checkbox), oder die automatische Planung hat
    // schlicht kein passendes Rezept mehr gefunden (z.B. Kategorie
    // erschöpft) - beide Fälle bekommen einen eigenen, unterscheidbaren
    // Hinweistext statt einer nichtssagend leeren Karte.
    const placeholderText = dayExcluded[dayIndex] ? '🚫 Von der Planung ausgenommen' : 'Kein passendes Rezept verfügbar';
    return `
        <div class="text-center text-muted">
            <h5 class="fw-bold mb-1">${dayLabels[dayIndex]}</h5>
            <span>${placeholderText}</span>
            <div class="mt-1">
                <button type="button" class="btn btn-sm btn-outline-secondary" onclick="openMainManualSelect(${dayIndex})">✏️ Rezept auswählen</button>
            </div>
        </div>
    `;
}

/**
 * Öffnet die manuelle Rezeptauswahl-Box anstelle der aktuellen
 * Hauptgericht-Anzeige (main-dish-display-<dayIndex>, siehe
 * renderDayCardBody). previousHtml wird gemerkt, um bei "Abbrechen" exakt
 * den vorherigen Zustand wiederherzustellen, ohne extra einen
 * Server-Roundtrip zu brauchen.
 */
function openMainManualSelect(dayIndex) {
    const area = document.getElementById(`main-dish-display-${dayIndex}`);
    if (!area) return;
    const previousHtml = area.innerHTML;
    area.innerHTML = buildManualSelectHtml(false);
    wireManualSelectBox(
        area, false,
        (recipeId) => setMainRecipe(dayIndex, recipeId),
        () => { area.innerHTML = previousHtml; }
    );
}

/**
 * Setzt das Hauptgericht eines Tages auf ein vom Nutzer manuell gewähltes
 * Rezept (ruft serverseitig set_main_day() auf - KEINE der
 * Balance-/Nachbarschafts-/Wiederholungs-Regeln von rerollSingleDay gilt
 * hier, siehe dortigen Docstring in routes/plan.py). Setzt dayExcluded
 * lokal ebenfalls zurück, da eine manuelle Zuweisung serverseitig
 * automatisch die Ausnahme aufhebt.
 */
function setMainRecipe(dayIndex, recipeId) {
    postWithCsrf(`/day/${dayDates[dayIndex]}/set-main`, {
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ recipe_id: recipeId }),
    })
    .then(response => {
        if (!response.ok) return response.json().then(data => { throw new Error(data.error || 'Auswahl fehlgeschlagen.'); });
        return response.json();
    })
    .then(newRecipe => {
        weeklyPlanRecipes[dayIndex] = newRecipe;
        dayExcluded[dayIndex] = false;
        refreshDayCard(dayIndex);
        rebuildShoppingList();
    })
    .catch(err => {
        alert('Hinweis: ' + err.message);
    });
}

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
        html += `
            <div class="d-flex justify-content-between align-items-center side-dish-card mb-1"
                 id="side-item-${dayIndex}-${side.side_id}"
                 draggable="true"
                 ondragstart="sideDragStart(event, ${dayIndex}, ${side.side_id})">
                <div>
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
 * gegen die Auswahlbox tauschen. Nach einer erfolgreichen Auswahl rendert
 * refreshSidesSection() ohnehin den kompletten Bereich neu (siehe
 * addSide/setOneSide), ein manuelles Wiederherstellen bei Erfolg ist daher
 * nicht nötig - nur bei "Abbrechen".
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
 * Legt eine NEUE Beilage für einen Tag an (ruft serverseitig add_side()
 * auf) - zusätzlich zu bereits vorhandenen, ein Tag kann beliebig viele
 * haben. recipeId ist optional: gesetzt (manuelle Auswahl über ✏️) wird
 * genau dieses Rezept übernommen, fehlt es (🎲-Button), würfelt der Server
 * zufällig unter Berücksichtigung von Wochen-Dubletten und der weichen
 * Wiederholungs-Gewichtung.
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

/**
 * Baut den kompletten Innenbereich einer Tageskarte auf: Personenzahl-Zeile,
 * Hauptgericht-Anzeigebereich (in einem eigenen main-dish-display-<i>-Div,
 * das openMainManualSelect gezielt ersetzt) und den Beilagen-Bereich
 * (renderSidesSection). Liest dabei ausschließlich aus dem aktuellen
 * JavaScript-Speicher (weeklyPlanRecipes/weeklySideRecipes/dayServings/
 * dayExcluded), nicht aus dem DOM - wird nach einem Tage-Tausch für beide
 * beteiligten Tage komplett neu aufgerufen, statt einzelne DOM-Knoten
 * gezielt zu aktualisieren, weil sich beim Tausch potenziell jedes Feld
 * ändert.
 */
function renderDayCardBody(dayIndex) {
    const servingsHtml = `
        <div class="d-flex justify-content-end align-items-center gap-1 mb-2">
            <label class="small text-muted mb-0" for="servings-${dayIndex}">👥 Personen</label>
            <input type="number" id="servings-${dayIndex}" class="form-control form-control-sm servings-input" style="width: 60px;" min="1" step="1" value="${dayServings[dayIndex]}" onchange="updateDayServings(${dayIndex}, this.value)">
        </div>
    `;

    const mainDisplayHtml = `<div class="main-dish-display" id="main-dish-display-${dayIndex}">${renderMainDisplay(dayIndex)}</div>`;
    const sidesHtml = `<div class="side-dish-row mt-2 pt-2 border-top" id="side-row-${dayIndex}">${renderSidesSection(dayIndex)}</div>`;

    return servingsHtml + mainDisplayHtml + sidesHtml;
}

/**
 * Übernimmt eine geänderte Personenzahl für einen Wochentag sofort in die
 * lokale Anzeige (optimistisch, für ein reaktionsschnelles Gefühl beim
 * Tippen) und schickt sie parallel an den Server zur dauerhaften
 * Speicherung. Anders als bei den würfeln/tauschen-Aktionen wird hier NICHT
 * auf die Serverantwort gewartet, bevor die UI reagiert - ein Fehlschlag
 * führt nur zu einer nachträglichen Fehlermeldung, die Eingabe bleibt aber
 * stehen (ein Zurückrollen der Zahl im Eingabefeld wäre für den Nutzer
 * verwirrender als eine kurze Fehlermeldung bei einem seltenen
 * Netzwerkfehler).
 */
function updateDayServings(dayIndex, value) {
    const n = parseInt(value);
    const servings = (isNaN(n) || n < 1) ? 1 : n;
    dayServings[dayIndex] = servings;
    rebuildShoppingList();

    postWithCsrf(`/day/${dayDates[dayIndex]}/servings`, {
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ servings: servings })
    }).catch(() => {
        alert('Hinweis: Personenzahl konnte nicht gespeichert werden.');
    });
}

/**
 * Schreibt die data-*-Attribute und den kompletten Inhalt einer Tageskarte
 * anhand des aktuellen JavaScript-Speichers neu (siehe renderDayCardBody).
 * Wird nach einem Tage-Tausch für beide betroffenen Tage aufgerufen, da
 * sich dort potenziell alle Felder auf einmal ändern und ein gezieltes
 * Aktualisieren einzelner DOM-Knoten (wie es rerollSingleDay tut) hier
 * unnötig fehleranfällig wäre.
 */
function refreshDayCard(dayIndex) {
    const card = document.getElementById(`day-card-${dayIndex}`);
    if (!card) return;

    const recipe = weeklyPlanRecipes[dayIndex];
    card.setAttribute('data-recipe-id', recipe ? recipe.id : '');
    card.setAttribute('data-category-id', recipe ? recipe.category_id : '');
    card.innerHTML = renderDayCardBody(dayIndex);
}

// --- TAGE TAUSCHEN / BEILAGEN VERSCHIEBEN PER DRAG-AND-DROP ---
// Nutzt die native HTML5-Drag-and-Drop-API. ZWEI unterschiedliche Dinge
// lassen sich auf dieser Seite ziehen, beide enden am selben Drop-Handler
// (dayCardDrop) auf der Tageskarte:
//
// 1. Die ganze Tageskarte (draggable="true" auf dem äußeren
//    .recipe-day-card-Element, siehe plan.html) - tauscht Hauptgericht,
//    ALLE Beilagen und Ausnahme-Status zweier Tage komplett miteinander
//    (daySwap). "Wird das Hauptgericht verschoben, kommen die Beilagen mit."
//
// 2. Eine einzelne Beilagen-Zeile (draggable="true" auf .side-dish-card,
//    siehe renderSidesSection) - verschiebt NUR diese eine Beilage auf den
//    Zieltag, ohne den Rest von Quell- oder Zieltag anzutasten (moveSideDish).
//
// Da eine Beilagen-Zeile INNERHALB einer Tageskarte verschachtelt liegt und
// beide draggable="true" haben, wählt der Browser beim Ziehen automatisch
// das innerste draggable-Element unter dem Cursor - ein Ziehen ab einer
// Beilagen-Zeile zieht also nur sie, nicht die ganze Karte, ganz ohne
// eigene Konfliktbehandlung. Welcher der beiden Fälle vorliegt, steht als
// JSON-codiertes {type: 'day'|'side', ...}-Objekt im DataTransfer (siehe
// dayCardDragStart/sideDragStart).

/** Merkt beim Start des Ziehens einer GANZEN Tageskarte deren Index im DataTransfer. */
function dayCardDragStart(event) {
    const dayIndex = parseInt(event.currentTarget.getAttribute('data-day-index'));
    event.dataTransfer.setData('text/plain', JSON.stringify({ type: 'day', dayIndex: dayIndex }));
}

/** Merkt beim Start des Ziehens EINER Beilagen-Zeile deren Herkunft (Tag + PlanDaySide-ID) im DataTransfer. stopPropagation verhindert, dass zusätzlich (redundant) auch noch dayCardDragStart der umschließenden Karte feuert. */
function sideDragStart(event, dayIndex, sideId) {
    event.dataTransfer.setData('text/plain', JSON.stringify({ type: 'side', dayIndex: dayIndex, sideId: sideId }));
    event.stopPropagation();
}

/** Erlaubt das Ablegen auf dieser Karte (sonst ignoriert der Browser drop-Events per Default) und markiert sie optisch. */
function dayCardAllowDrop(event) {
    event.preventDefault();
    event.currentTarget.classList.add('drag-over');
}

/**
 * Gemeinsamer Drop-Handler für beide Drag-Arten (siehe Erklärung oben):
 * liest die JSON-codierte Payload aus dem DataTransfer und leitet je nach
 * "type" an daySwap() (ganze Karte) oder moveSideDish() (eine Beilage)
 * weiter. Ungültige/fehlende Payloads (z.B. ein Drag von außerhalb dieser
 * Seite) werden stillschweigend ignoriert.
 */
function dayCardDrop(event) {
    event.preventDefault();
    const targetCard = event.currentTarget;
    targetCard.classList.remove('drag-over');

    const raw = event.dataTransfer.getData('text/plain');
    if (!raw) return;
    let payload;
    try {
        payload = JSON.parse(raw);
    } catch (e) {
        return;
    }

    const targetDayIndex = parseInt(targetCard.getAttribute('data-day-index'));

    if (payload.type === 'side') {
        moveSideDish(payload.dayIndex, payload.sideId, targetDayIndex);
    } else if (payload.type === 'day') {
        daySwap(payload.dayIndex, targetDayIndex);
    }
}

/**
 * Tauscht zwei ganze Tageskarten komplett miteinander (ruft serverseitig
 * swap_days() auf) und tauscht erst nach dessen Bestätigung die drei
 * betroffenen Arrays (weeklyPlanRecipes, weeklySideRecipes, dayExcluded)
 * per Destrukturierungs-Swap, bevor beide Karten neu gerendert werden.
 */
function daySwap(i, j) {
    if (i === j) return;

    postWithCsrf(`/day/${dayDates[i]}/swap/${dayDates[j]}`)
    .then(response => {
        if (!response.ok) throw new Error('Tausch fehlgeschlagen.');
        return response.json();
    })
    .then(() => {
        [weeklyPlanRecipes[i], weeklyPlanRecipes[j]] = [weeklyPlanRecipes[j], weeklyPlanRecipes[i]];
        [weeklySideRecipes[i], weeklySideRecipes[j]] = [weeklySideRecipes[j], weeklySideRecipes[i]];
        [dayExcluded[i], dayExcluded[j]] = [dayExcluded[j], dayExcluded[i]];

        refreshDayCard(i);
        refreshDayCard(j);
        rebuildShoppingList();
    })
    .catch(err => {
        alert('Hinweis: ' + err.message);
    });
}

/**
 * Verschiebt EINE einzelne Beilage von sourceDayIndex zu targetDayIndex
 * (ruft serverseitig move_one_side() auf) - ein einseitiges Verschieben,
 * kein Tausch: der Zieltag behält alles, was er bereits hatte, und bekommt
 * die Beilage zusätzlich. Aktualisiert nach Erfolg beide betroffenen
 * Beilagen-Bereiche (nicht die ganze Karte, das Hauptgericht bleibt ja
 * unangetastet).
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

/**
 * Summiert die Nährwerte aller Tage (Haupt- + Zusatzgericht, sofern
 * vorhanden) zu einer Wochenübersicht und einem Tagesdurchschnitt (nur über
 * tatsächlich geplante Tage gemittelt, nicht über alle 7). Die Werte
 * bleiben dabei bewusst UNskaliert bezüglich der Personenzahl: Nährwerte
 * in diesem Projekt sind immer "pro Portion/Person" gemeint, unabhängig
 * davon wie viele Personen an dem Tag mitessen - die Personenzahl
 * beeinflusst ausschließlich die Zutatenmengen der Einkaufsliste (siehe
 * rebuildShoppingList).
 */
function rebuildWeeklyNutritionSummary() {
    const container = document.getElementById('weeklyNutritionSummary');
    if (!container) return;

    const totals = { calories: 0, protein: 0, carbs: 0, fat: 0 };
    let plannedDays = 0;

    for (let i = 0; i < 7; i++) {
        let dayHasSomething = false;
        [weeklyPlanRecipes[i], ...weeklySideRecipes[i]].forEach(recipe => {
            if (recipe) {
                totals.calories += recipe.calories || 0;
                totals.protein += recipe.protein || 0;
                totals.carbs += recipe.carbs || 0;
                totals.fat += recipe.fat || 0;
                dayHasSomething = true;
            }
        });
        if (dayHasSomething) plannedDays++;
    }

    if (plannedDays === 0) {
        container.innerHTML = '<span class="text-muted small">Noch keine Gerichte im Plan.</span>';
        return;
    }

    container.innerHTML = `
        <div class="text-muted small font-monospace bg-light p-2 rounded mb-1">
            Σ Woche: ${Math.round(totals.calories)} kcal | E: ${totals.protein.toFixed(1)}g | K: ${totals.carbs.toFixed(1)}g | F: ${totals.fat.toFixed(1)}g
        </div>
        <div class="text-muted small font-monospace bg-light p-2 rounded">
            Ø pro Tag (${plannedDays} geplant): ${Math.round(totals.calories / plannedDays)} kcal | E: ${(totals.protein / plannedDays).toFixed(1)}g | K: ${(totals.carbs / plannedDays).toFixed(1)}g | F: ${(totals.fat / plannedDays).toFixed(1)}g
        </div>
    `;
}

/**
 * Liefert die Sortierposition einer Einkaufslisten-Kategorie gemäß der
 * festen Reihenfolge in window.SHOPPING_CATEGORIES (siehe base.html/
 * services/shopping.py). Unbekannte oder fehlende Kategorien (null,
 * undefined, oder ein Wert, der nicht in der Liste steht - z.B. weil eine
 * Zutat aus der Zeit vor Einführung dieses Felds stammt) bekommen die
 * höchste Positionsnummer und landen dadurch immer GANZ AM ENDE der
 * Einkaufsliste, in der "Sonstiges"-Sammelgruppe.
 */
function categorySortIndex(category) {
    const categories = window.SHOPPING_CATEGORIES || [];
    const idx = categories.indexOf(category);
    return idx === -1 ? categories.length : idx;
}

/**
 * Rechnet die komplette Einkaufsliste der Woche aus dem aktuellen
 * JavaScript-Speicher neu zusammen und rendert sie, gruppiert nach fester
 * Einkaufslisten-Kategorie-Reihenfolge (siehe categorySortIndex) und
 * innerhalb einer Gruppe alphabetisch. Wird nach JEDER Änderung am Plan
 * aufgerufen (würfeln, tauschen, Personenzahl, Beilage entfernen, Artikel
 * hinzufügen/entfernen), da praktisch jede dieser Änderungen die
 * benötigten Zutatenmengen beeinflusst. Ruft dabei auch
 * rebuildWeeklyNutritionSummary() mit auf, da beide Übersichten stets
 * gemeinsam aktuell gehalten werden.
 *
 * Zwei Quellen fließen in die Liste ein: aus Rezept-Zutaten abgeleitete
 * Posten (nach Name+Einheit über die ganze Woche konsolidiert und mit der
 * jeweiligen Tages-Personenzahl skaliert, wie schon zuvor) sowie manuell
 * hinzugefügte Artikel aus weeklyExtraItems (unskaliert, jeder für sich
 * einzeln mit eigenem Lösch-Button, da sie zu keinem Rezept/Tag gehören).
 */
function rebuildShoppingList() {
    rebuildWeeklyNutritionSummary();

    const container = document.getElementById('shoppingListContainer');
    const counterBadge = document.getElementById('totalIngredientsCount');
    if (!container) return;

    container.innerHTML = '';
    let consolidated = {};

    // Zutatenmengen werden pro Tag auf die dort eingestellte Personenzahl hochgerechnet
    // (Verhältnis zur Portionsangabe des jeweiligen Rezepts) - Nährwerte bleiben davon
    // unberührt, die sind immer pro Portion/Person.
    for (let i = 0; i < 7; i++) {
        [weeklyPlanRecipes[i], ...weeklySideRecipes[i]].forEach(recipe => {
            if (recipe && recipe.ingredients) {
                const factor = recipe.servings ? dayServings[i] / recipe.servings : 1;
                recipe.ingredients.forEach(ing => {
                    // Zusammenfassungs-Schlüssel aus Name+Einheit: dieselbe
                    // Zutat in unterschiedlicher Einheit (z.B. "Mehl" in g
                    // an einem Tag, in EL an einem anderen) wird bewusst
                    // NICHT zusammengerechnet, da die Mengen sonst nicht
                    // vergleichbar wären.
                    const key = `${ing.name.trim()}|||${ing.unit.trim()}`;
                    const scaledAmount = ing.amount * factor;
                    if (consolidated[key]) {
                        consolidated[key].amount += scaledAmount;
                        // Falls dieselbe Zutat in mehreren Rezepten leicht
                        // unterschiedlich kategorisiert wurde, gewinnt die
                        // zuletzt gesehene nicht-leere Kategorie - kein
                        // harter Fehlerfall, kommt in der Praxis kaum vor.
                        if (ing.category) consolidated[key].category = ing.category;
                    } else {
                        consolidated[key] = { name: ing.name, amount: scaledAmount, unit: ing.unit, category: ing.category || null };
                    }
                });
            }
        });
    }

    // Konsolidierte Rezept-Zutaten und manuelle Artikel zu einer
    // gemeinsamen Liste zusammenführen, damit beide zusammen sortiert und
    // gruppiert dargestellt werden - isExtra unterscheidet später, ob ein
    // Eintrag einen Lösch-Button bekommt (nur manuelle Artikel sind
    // einzeln entfernbar, Rezept-Zutaten ergeben sich automatisch aus dem
    // Plan).
    const items = Object.values(consolidated).map(item => ({ ...item, isExtra: false }));
    weeklyExtraItems.forEach(extra => {
        items.push({
            id: extra.id, name: extra.name, amount: extra.amount, unit: extra.unit,
            category: extra.category, isExtra: true,
        });
    });

    if (counterBadge) counterBadge.textContent = items.length;

    if (items.length === 0) {
        container.innerHTML = '<li class="list-group-item text-center text-muted my-3">Keine Zutaten für diese Woche benötigt.</li>';
        return;
    }

    // Erst nach fester Einkaufs-Kategorie-Reihenfolge sortieren, innerhalb
    // derselben Kategorie alphabetisch nach Name.
    items.sort((a, b) => {
        const catDiff = categorySortIndex(a.category) - categorySortIndex(b.category);
        return catDiff !== 0 ? catDiff : a.name.localeCompare(b.name);
    });

    // Gruppen-Überschriften einfügen, sobald sich die Kategorie zum
    // vorherigen Posten ändert (die Liste ist bereits danach sortiert, ein
    // einfacher Wechsel-Check reicht daher statt vorab zu gruppieren).
    let lastCategoryLabel = undefined;
    items.forEach(item => {
        const categoryLabel = item.category || window.SHOPPING_UNCATEGORIZED;
        if (categoryLabel !== lastCategoryLabel) {
            const header = document.createElement('li');
            header.className = 'list-group-item bg-light text-muted small fw-bold text-uppercase py-1 px-3';
            header.textContent = categoryLabel;
            container.appendChild(header);
            lastCategoryLabel = categoryLabel;
        }

        const li = document.createElement('li');
        li.className = 'list-group-item d-flex justify-content-between align-items-center py-2 px-3';

        const label = document.createElement('label');
        label.className = 'd-flex align-items-center m-0 flex-grow-1';
        label.style.cursor = 'pointer';

        const checkbox = document.createElement('input');
        checkbox.type = 'checkbox';
        checkbox.className = 'form-check-input me-3';
        checkbox.style.transform = 'scale(1.15)';

        const nameSpan = document.createElement('span');
        nameSpan.className = 'text-dark fs-5';
        // textContent statt innerHTML: item.name kann Nutzereingabe sein
        // (sowohl ein Zutatenname aus einem Rezept als auch - neu - der
        // frei eingetippte Name eines manuellen Artikels), textContent
        // umgeht dadurch jedes HTML/Script-Injection-Risiko von vornherein.
        nameSpan.textContent = item.name;

        label.appendChild(checkbox);
        label.appendChild(nameSpan);

        const right = document.createElement('div');
        right.className = 'd-flex align-items-center';

        // Auf 2 Nachkommastellen runden, um Fließkomma-Artefakte durch die
        // Personen-Skalierung zu vermeiden (z.B. 133.33333333333334 -> 133.33).
        // Manuelle Artikel dürfen ganz ohne Mengenangabe existieren (null).
        const displayAmount = (item.amount === null || item.amount === undefined) ? null : Math.round(item.amount * 100) / 100;
        if (displayAmount !== null) {
            const badge = document.createElement('span');
            badge.className = 'badge bg-success px-3 py-2 rounded-pill font-monospace';
            badge.style.backgroundColor = 'var(--primary-food)';
            badge.style.fontSize = '0.9rem';
            badge.textContent = item.unit ? `${displayAmount} ${item.unit}` : `${displayAmount}`;
            right.appendChild(badge);
        }

        if (item.isExtra) {
            const deleteBtn = document.createElement('button');
            deleteBtn.type = 'button';
            deleteBtn.className = 'btn btn-sm text-danger border-0 p-1 ms-1';
            deleteBtn.title = 'Artikel entfernen';
            deleteBtn.textContent = '❌';
            deleteBtn.onclick = () => removeExtraShoppingItem(item.id);
            right.appendChild(deleteBtn);
        }

        li.appendChild(label);
        li.appendChild(right);

        // Checkbox dient rein der Anzeige beim Einkaufen (durchgestrichen +
        // ausgegraut, sobald abgehakt) - der Zustand wird bewusst NICHT
        // gespeichert (weder serverseitig noch in localStorage), da die
        // Liste ohnehin bei jeder Planänderung komplett neu aufgebaut wird.
        checkbox.addEventListener('change', function() {
            if (this.checked) {
                nameSpan.style.textDecoration = 'line-through';
                nameSpan.style.opacity = '0.5';
            } else {
                nameSpan.style.textDecoration = 'none';
                nameSpan.style.opacity = '1';
            }
        });

        container.appendChild(li);
    });
}

/**
 * Liest das "Artikel hinzufügen"-Mini-Formular aus (siehe plan.html), legt
 * den Artikel serverseitig für die aktuell angezeigte Woche an (dayDates[0]
 * ist der Montag dieser Woche) und hängt ihn bei Erfolg an weeklyExtraItems
 * an, bevor die Einkaufsliste neu aufgebaut wird. name ist die einzige
 * Pflichtangabe - ist das Feld leer, passiert nichts (kein Fehler nötig,
 * der Button/Enter-Druck bleibt einfach wirkungslos).
 */
function addExtraShoppingItem() {
    const nameInput = document.getElementById('extraItemName');
    const amountInput = document.getElementById('extraItemAmount');
    const unitInput = document.getElementById('extraItemUnit');
    const categorySelect = document.getElementById('extraItemCategory');
    if (!nameInput) return;

    const name = nameInput.value.trim();
    if (!name) return;

    postWithCsrf(`/plan/${dayDates[0]}/shopping-item/add`, {
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            name: name,
            amount: amountInput.value ? parseFloat(amountInput.value) : null,
            unit: unitInput.value.trim(),
            category: categorySelect.value,
        }),
    })
    .then(response => {
        if (!response.ok) throw new Error('Hinzufügen fehlgeschlagen.');
        return response.json();
    })
    .then(newItem => {
        weeklyExtraItems.push(newItem);
        rebuildShoppingList();
        // Formular für den nächsten Artikel zurücksetzen und den Fokus
        // gleich wieder ins Namensfeld legen, damit mehrere Artikel
        // hintereinander schnell per Enter eingetragen werden können.
        nameInput.value = '';
        amountInput.value = '';
        unitInput.value = '';
        categorySelect.value = '';
        nameInput.focus();
    })
    .catch(err => {
        alert('Hinweis: ' + err.message);
    });
}

/**
 * Entfernt einen manuell hinzugefügten Artikel wieder aus der Einkaufsliste
 * (serverseitig endgültig gelöscht, nicht nur ausgeblendet).
 */
function removeExtraShoppingItem(itemId) {
    postWithCsrf(`/shopping-item/${itemId}/delete`)
    .then(response => {
        if (!response.ok) throw new Error('Entfernen fehlgeschlagen.');
        weeklyExtraItems = weeklyExtraItems.filter(item => item.id !== itemId);
        rebuildShoppingList();
    })
    .catch(err => {
        alert('Hinweis: ' + err.message);
    });
}

// Datumsanzeige/-sprung: eigenes dd.mm.yyyy-Textfeld statt des Browser-lokalisierten
// <input type="date">-Anzeigetexts (der z.B. in Chrome je nach Systemsprache
// mm/dd/yyyy zeigen kann). Der native Picker bleibt fürs Kalender-Popup erhalten,
// ist aber unsichtbar (siehe CSS in plan.html) und wird per Klick auf das
// sichtbare Textfeld programmatisch geöffnet (showPicker()). Wählt der Nutzer
// im Popup ein Datum, navigiert das change-Event direkt zur Plan-Seite der
// Woche, in der dieses Datum liegt.
(function() {
    const display = document.getElementById('weekDateDisplay');
    const picker = document.getElementById('weekDatePicker');
    if (!display || !picker) return;

    display.addEventListener('click', () => {
        if (picker.showPicker) {
            picker.showPicker();
        } else {
            // Fallback für Browser ohne showPicker()-Unterstützung: Fokus
            // auf das (unsichtbare) native Feld, damit zumindest
            // Tastatureingabe/native Bedienung möglich bleibt.
            picker.focus();
        }
    });

    picker.addEventListener('change', () => {
        if (picker.value) {
            location.href = '/plan/' + picker.value;
        }
    });
})();
