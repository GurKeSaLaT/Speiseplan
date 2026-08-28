/**
 * plan.js - Kern der Plan-Seite (templates/plan.html): globaler Zustand,
 * Tageskarten-Aufbau (inkl. dem erstmaligen Aufbau beim Laden der Seite -
 * Jinja liefert nur noch leere Karten-Hüllen), Hauptgericht würfeln oder
 * manuell auswählen, Personenzahl ändern, sowie der komplette Tages-Tausch
 * per Drag-and-Drop.
 *
 * Diese Datei ist die "Basis", auf der drei Begleitdateien aufbauen (sie
 * nutzen deren globale state-Variablen/Funktionen, siehe unten) - zusammen
 * ersetzen sie das früher einzelne, auf über 1000 Zeilen angewachsene
 * plan.js:
 * - static/plan-manual-select.js: die wiederverwendbare Rezeptsuche-Box,
 *   die sowohl hier (Hauptgericht) als auch in plan-sides.js (Beilagen)
 *   verwendet wird.
 * - static/plan-sides.js: alles rund um Beilagen (beliebig viele pro Tag,
 *   hinzufügen/würfeln/auswählen/entfernen/verschieben).
 * - static/plan-shopping.js: Wochen-Nährwertübersicht, Einkaufsliste,
 *   manuelle Einkaufslisten-Artikel.
 *
 * Da alle vier Dateien klassische (nicht als type="module" eingebundene)
 * <script>-Tags sind, teilen sie sich denselben globalen Scope - welche
 * Reihenfolge sie in plan.html geladen werden, spielt für die Korrektheit
 * keine Rolle: keine der Dateien RUFT beim eigenen Laden bereits Funktionen
 * aus einer anderen auf (nur der DOMContentLoaded-Handler unten tut das,
 * und der feuert erst, nachdem alle Skripte vollständig geladen sind).
 *
 * Jede Aktion, die den Plan verändert, schickt zuerst einen fetch()-Request
 * an den Server (siehe routes/plan/), der die Änderung in der Datenbank
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
// den bestehenden Datums-Indizes). dayDates wird auch von den
// Begleitdateien (plan-sides.js, plan-shopping.js) für ihre eigenen
// fetch()-URLs verwendet.
const dayLabels = window.PLAN_DATA.dayLabels;
const dayDates = window.PLAN_DATA.weekDates;

// ALLE Rezepte (unabhängig vom aktuellen Plan) in schlanker Form
// ({id, name, category_name, is_side_dish}) - Grundlage für die manuelle
// Rezeptauswahl-Suche (siehe static/plan-manual-select.js). Ändert sich
// nach dem Laden der Seite nicht mehr; ein neu angelegtes Rezept taucht
// dort erst nach einem Neuladen auf.
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
// Plan berechnet wird (Nährwertsumme, Einkaufsliste, siehe
// static/plan-shopping.js) - nach jeder erfolgreichen serverseitigen
// Änderung wird dieses Array aktualisiert, damit diese Berechnungen ohne
// Seiten-Reload konsistent bleiben.
let weeklyPlanRecipes = window.PLAN_DATA.plan;

// Zusatzgerichte/Beilagen (Index = Wochentag, Wert = LISTE von
// Rezept-Objekten - ein Tag kann beliebig viele Beilagen gleichzeitig
// haben, siehe models.py: PlanDaySide). Jedes Beilagen-Objekt hat
// zusätzlich zu den normalen Rezeptfeldern ein side_id-Feld: die ID der
// PlanDaySide-Zeile selbst (NICHT des Rezepts), über die eine einzelne
// Beilage gezielt neu gewürfelt/ersetzt/entfernt/verschoben wird - siehe
// static/plan-sides.js.
let weeklySideRecipes = window.PLAN_DATA.sidePlan;

// Manuell zur Einkaufsliste dieser Woche hinzugefügte Artikel, die zu keinem
// Rezept gehören (z.B. Hygieneartikel) - jeder Eintrag ist ein Objekt
// {id, name, amount, unit, category} und wurde bereits serverseitig
// persistiert (siehe routes/plan/shopping.py: add_shopping_item). Anders
// als weeklyPlanRecipes/weeklySideRecipes NICHT nach Wochentag indiziert,
// sondern eine flache Liste - ein manueller Artikel gehört der Woche als
// Ganzes, keinem bestimmten Tag. Verwaltet in static/plan-shopping.js.
let weeklyExtraItems = window.PLAN_DATA.extraItems || [];

// Beim ersten Laden der Seite alle 7 Tageskarten (siehe renderDayCardBody
// weiter unten - Jinja liefert in plan.html nur noch leere Karten-Hüllen)
// sowie die Einkaufsliste (und darüber auch die Wochen-Nährwertübersicht,
// siehe static/plan-shopping.js: rebuildShoppingList) aus den bereits vom
// Server mitgelieferten Daten aufbauen - ab dann übernehmen die einzelnen
// Aktionen das Neu-Berechnen bei jeder Änderung. refreshDayCard/
// rebuildShoppingList brechen selbst früh ab, wenn die jeweiligen
// Container gar nicht im DOM existieren (z.B. weil diese Woche noch gar
// keinen Plan hat) - dieser Aufruf ist daher auch in dem Fall gefahrlos.
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
 * CSRF-Header jedes Mal von Hand mitschreiben zu müssen. Wird auch von
 * den plan-*.js-Begleitdateien für ihre eigenen fetch()-Aufrufe verwendet.
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
 * routes/plan/day_actions.py: reroll_day() auf, welche eine zufällige
 * Alternative aus derselben Kategorie wählt, die weder in dieser Woche
 * noch in den category-Nachbartagen bereits vorkommt). Bei Erfolg werden
 * sowohl die Tageskarte im DOM als auch der lokale weeklyPlanRecipes-
 * Speicher und die Einkaufsliste aktualisiert; bei Misserfolg (keine
 * Alternative verfügbar) bleibt alles unverändert und der Nutzer bekommt
 * eine Fehlermeldung.
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
 * Baut den Hauptgericht-Anzeigebereich einer Tageskarte auf: entweder das
 * zugewiesene Rezept mit 🎲 (neu würfeln) + ✏️ (manuell auswählen), oder
 * einen Platzhaltertext (ausgenommen bzw. kein passendes Rezept gefunden)
 * mit einem eigenständigen "Rezept auswählen"-Button - die manuelle
 * Auswahl bleibt so auch dann erreichbar, wenn die automatische Planung
 * an diesem Tag nichts gefunden hat oder der Tag ausgenommen wurde (die
 * Auswahl hebt eine Ausnahme automatisch wieder auf, siehe
 * routes/plan/day_actions.py: set_main_day).
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
 * Öffnet die manuelle Rezeptauswahl-Box (siehe static/plan-manual-select.js)
 * anstelle der aktuellen Hauptgericht-Anzeige (main-dish-display-<dayIndex>,
 * siehe renderDayCardBody). previousHtml wird gemerkt, um bei "Abbrechen"
 * exakt den vorherigen Zustand wiederherzustellen, ohne extra einen
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
 * Rezept (ruft serverseitig routes/plan/day_actions.py: set_main_day()
 * auf - KEINE der Balance-/Nachbarschafts-/Wiederholungs-Regeln von
 * rerollSingleDay gilt hier, siehe dortigen Docstring). Setzt dayExcluded
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
 * Baut den kompletten Innenbereich einer Tageskarte auf: Personenzahl-Zeile,
 * Hauptgericht-Anzeigebereich (in einem eigenen main-dish-display-<i>-Div,
 * das openMainManualSelect gezielt ersetzt) und den Beilagen-Bereich
 * (renderSidesSection, siehe static/plan-sides.js). Liest dabei
 * ausschließlich aus dem aktuellen JavaScript-Speicher (weeklyPlanRecipes/
 * weeklySideRecipes/dayServings/dayExcluded), nicht aus dem DOM - wird
 * nach einem Tage-Tausch für beide beteiligten Tage komplett neu
 * aufgerufen, statt einzelne DOM-Knoten gezielt zu aktualisieren, weil
 * sich beim Tausch potenziell jedes Feld ändert.
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
 * unnötig fehleranfällig wäre. Wird außerdem beim initialen Laden der
 * Seite für alle 7 Tage aufgerufen (siehe DOMContentLoaded oben).
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
//    siehe static/plan-sides.js: renderSidesSection) - verschiebt NUR
//    diese eine Beilage auf den Zieltag, ohne den Rest von Quell- oder
//    Zieltag anzutasten (moveSideDish, siehe static/plan-sides.js).
//
// Da eine Beilagen-Zeile INNERHALB einer Tageskarte verschachtelt liegt und
// beide draggable="true" haben, wählt der Browser beim Ziehen automatisch
// das innerste draggable-Element unter dem Cursor - ein Ziehen ab einer
// Beilagen-Zeile zieht also nur sie, nicht die ganze Karte, ganz ohne
// eigene Konfliktbehandlung. Welcher der beiden Fälle vorliegt, steht als
// JSON-codiertes {type: 'day'|'side', ...}-Objekt im DataTransfer (siehe
// dayCardDragStart hier bzw. sideDragStart in static/plan-sides.js).

/** Merkt beim Start des Ziehens einer GANZEN Tageskarte deren Index im DataTransfer. */
function dayCardDragStart(event) {
    const dayIndex = parseInt(event.currentTarget.getAttribute('data-day-index'));
    event.dataTransfer.setData('text/plain', JSON.stringify({ type: 'day', dayIndex: dayIndex }));
}

/** Erlaubt das Ablegen auf dieser Karte (sonst ignoriert der Browser drop-Events per Default) und markiert sie optisch. */
function dayCardAllowDrop(event) {
    event.preventDefault();
    event.currentTarget.classList.add('drag-over');
}

/**
 * Gemeinsamer Drop-Handler für beide Drag-Arten (siehe Erklärung oben):
 * liest die JSON-codierte Payload aus dem DataTransfer und leitet je nach
 * "type" an daySwap() (ganze Karte, hier unten) oder moveSideDish() (eine
 * Beilage, siehe static/plan-sides.js) weiter. Ungültige/fehlende
 * Payloads (z.B. ein Drag von außerhalb dieser Seite) werden
 * stillschweigend ignoriert.
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
 * routes/plan/day_actions.py: swap_days() auf) und tauscht erst nach
 * dessen Bestätigung die drei betroffenen Arrays (weeklyPlanRecipes,
 * weeklySideRecipes, dayExcluded) per Destrukturierungs-Swap, bevor beide
 * Karten neu gerendert werden.
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
