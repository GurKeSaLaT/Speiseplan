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

// Ob das Hauptgericht eines Tages bereits als gekocht markiert wurde
// (Index = Wochentag) - steuert das "Ausgrauen" der Tageskarte (siehe
// renderMainDisplay) und die vorbefüllte Checkbox im Rezept-Detail-Fenster
// (siehe openRecipeDetail). Beilagen tragen ihr eigenes cooked-Feld direkt
// am Rezept-Objekt in weeklySideRecipes (siehe jsonify_side in
// services/planning.py), brauchen also kein eigenes paralleles Array.
let dayCooked = window.PLAN_DATA.cookedMain;

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
 * sowohl die Tageskarte im DOM (über refreshDayCard - ein neu gewürfeltes
 * Gericht ist serverseitig automatisch nicht mehr "gekocht", siehe
 * reroll_day() dort, das muss sich auch im Ausgrau-Zustand der Karte
 * niederschlagen) als auch der lokale weeklyPlanRecipes-Speicher und die
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
        weeklyPlanRecipes[dayIndex] = newRecipe;
        dayCooked[dayIndex] = false;
        refreshDayCard(dayIndex);
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
    // Rechts oben neben dem Gericht statt einer eigenen vollbreiten Zeile
    // (siehe renderServingsHtml() weiter unten für den Grund) - dadurch
    // beginnen Datum/Gerichtname weiterhin ganz oben links, ohne dass die
    // Personenzahl stattdessen zwischen Nährwert-Zeile und Beilagen landet.
    const servingsHtml = renderServingsHtml(dayIndex);

    const recipe = weeklyPlanRecipes[dayIndex];
    if (recipe) {
        const cookedClass = dayCooked[dayIndex] ? ' dish-cooked' : '';
        return `
            <div class="d-flex justify-content-between align-items-start mb-2">
                <div class="dish-clickable${cookedClass}" role="button" title="Details anzeigen" onclick="openRecipeDetail(${dayIndex}, null)">
                    <h5 class="text-success fw-bold mb-0" style="color: var(--primary-food) !important;">${dayLabels[dayIndex]}</h5>
                    <span class="recipe-name fw-bold fs-5 text-dark d-block mt-1">${recipe.name}</span>
                </div>
                <div class="text-end">
                    ${servingsHtml}
                    <div class="d-flex align-items-center gap-1 justify-content-end mt-1">
                        <span class="badge badge-category recipe-category px-3 py-2 rounded-pill">${recipe.category_name}</span>
                        <button type="button" class="btn btn-sm btn-outline-secondary border-0 p-2 fs-5" title="Diesen Tag neu würfeln" onclick="rerollSingleDay(${dayIndex})">🎲</button>
                        <button type="button" class="btn btn-sm btn-outline-secondary border-0 p-2 fs-5" title="Anderes Rezept auswählen" onclick="openMainManualSelect(${dayIndex})">✏️</button>
                    </div>
                </div>
            </div>
            <div class="text-muted small font-monospace bg-light p-2 rounded dish-clickable${cookedClass}" role="button" title="Details anzeigen" onclick="openRecipeDetail(${dayIndex}, null)">
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
        <div class="d-flex justify-content-end mb-1">${servingsHtml}</div>
        <div class="text-center text-muted">
            <h5 class="fw-bold mb-1">${dayLabels[dayIndex]}</h5>
            <span>${placeholderText}</span>
            <div class="mt-1">
                <button type="button" class="btn btn-sm btn-outline-secondary" onclick="openMainManualSelect(${dayIndex})">✏️ Rezept auswählen</button>
            </div>
        </div>
    `;
}

/** Personenzahl-Eingabefeld für eine Tageskarte - eigene Funktion statt
 * eines festen HTML-Blocks in renderDayCardBody, da es jetzt in
 * renderMainDisplay() selbst eingebettet wird (siehe dortiger Kommentar),
 * für BEIDE Zweige (Rezept vorhanden/Platzhalter) aber identisch aussieht. */
function renderServingsHtml(dayIndex) {
    return `
        <div class="d-flex align-items-center justify-content-end gap-1">
            <label class="small text-muted mb-0" for="servings-${dayIndex}">👥 Personen</label>
            <input type="number" id="servings-${dayIndex}" class="form-control form-control-sm servings-input" style="width: 60px;" min="1" step="1" value="${dayServings[dayIndex]}" onchange="updateDayServings(${dayIndex}, this.value)">
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
        dayCooked[dayIndex] = false;
        refreshDayCard(dayIndex);
        rebuildShoppingList();
    })
    .catch(err => {
        alert('Hinweis: ' + err.message);
    });
}

/**
 * Baut den kompletten Innenbereich einer Tageskarte auf: Hauptgericht-
 * Anzeigebereich (in einem eigenen main-dish-display-<i>-Div, das
 * openMainManualSelect gezielt ersetzt - enthält auch die Personenzahl-
 * Eingabe, siehe renderMainDisplay) und den Beilagen-Bereich
 * (renderSidesSection, siehe static/plan-sides.js). Liest dabei
 * ausschließlich aus dem aktuellen JavaScript-Speicher (weeklyPlanRecipes/
 * weeklySideRecipes/dayServings/dayExcluded), nicht aus dem DOM - wird
 * nach einem Tage-Tausch für beide beteiligten Tage komplett neu
 * aufgerufen, statt einzelne DOM-Knoten gezielt zu aktualisieren, weil
 * sich beim Tausch potenziell jedes Feld ändert.
 */
function renderDayCardBody(dayIndex) {
    // Die Personenzahl-Eingabe ist Teil von renderMainDisplay() selbst
    // (oben rechts neben dem Gericht) statt einer eigenen Zeile hier -
    // Datum/Gerichtname beginnen dadurch ganz oben links in der Karte,
    // ohne dass die Personenzahl zwischen Nährwert-Zeile und Beilagen
    // landet (siehe dortiger Kommentar).
    const mainDisplayHtml = `<div class="main-dish-display" id="main-dish-display-${dayIndex}">${renderMainDisplay(dayIndex)}</div>`;
    const sidesHtml = `<div class="side-dish-row mt-2 pt-2 border-top" id="side-row-${dayIndex}">${renderSidesSection(dayIndex)}</div>`;

    return mainDisplayHtml + sidesHtml;
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
        [dayCooked[i], dayCooked[j]] = [dayCooked[j], dayCooked[i]];

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

// --- REZEPT-DETAIL-FENSTER ---
// Ein einzelnes, wiederverwendetes Modal (#recipeDetailModal, siehe
// plan.html) statt eines pro Gericht: es zeigt immer nur GENAU EIN
// Gericht gleichzeitig, sein Inhalt wird bei jedem Öffnen per JS neu
// befüllt. Öffnet man per Klick auf ein Hauptgericht (dish-clickable in
// renderMainDisplay oben) oder eine Beilage (dish-clickable in
// static/plan-sides.js: renderSidesSection) - liest in beiden Fällen aus
// den bereits im Frontend vorliegenden weeklyPlanRecipes/
// weeklySideRecipes-Objekten, kein eigener Server-Roundtrip nötig (siehe
// services/planning.py: jsonify_recipe()-Docstring für die dafür
// zusätzlich mitgelieferten Felder is_favorite/source_url/instructions).

// Merkt sich, für welchen Tag/welche Beilage das Detail-Fenster gerade
// offen ist - braucht toggleDetailCooked() unten, um zu wissen, wohin die
// Checkbox-Änderung serverseitig gespeichert werden soll, ohne dass jeder
// Aufrufer das selbst durchreichen müsste.
let detailDayIndex = null;
let detailSideId = null;

/** Escaped Text für die sichere Einbettung in innerHTML (verhindert, dass
 * z.B. ein Rezeptname mit "<"/"&" das Markup des Detail-Fensters bricht
 * oder - da hier anders als bei renderMainDisplay/renderSidesSection auch
 * längerer freier Text wie die Zubereitung angezeigt wird - referenziertes
 * HTML ausführt). */
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text ?? '';
    return div.innerHTML;
}

/**
 * Öffnet das Rezept-Detail-Fenster für das Hauptgericht eines Tages
 * (sideId null) oder eine bestimmte Beilage (sideId gesetzt) - baut den
 * kompletten, rein lesenden Inhalt aus dem bereits vorliegenden
 * Rezept-Objekt auf und zeigt das Bootstrap-Modal an.
 */
function openRecipeDetail(dayIndex, sideId) {
    const recipe = sideId
        ? (weeklySideRecipes[dayIndex] || []).find(s => s.side_id === sideId)
        : weeklyPlanRecipes[dayIndex];
    if (!recipe) return;

    detailDayIndex = dayIndex;
    detailSideId = sideId;
    const cooked = sideId ? !!recipe.cooked : !!dayCooked[dayIndex];

    document.getElementById('recipeDetailTitle').textContent = (recipe.is_favorite ? '⭐ ' : '') + recipe.name;
    document.getElementById('recipeDetailEditLink').href = `/manage/recipe/edit/${recipe.id}`;
    document.getElementById('recipeDetailBody').innerHTML = renderRecipeDetailBody(recipe, dayServings[dayIndex]);

    const checkbox = document.getElementById('recipeDetailCookedCheckbox');
    checkbox.checked = cooked;
    checkbox.onchange = () => toggleDetailCooked(checkbox.checked);

    bootstrap.Modal.getOrCreateInstance(document.getElementById('recipeDetailModal')).show();
}

/** Baut den read-only Inhalt des Detail-Fensters (Kategorie/Personen,
 * Nährwerte, Zutatenliste, ggf. Anleitung/Quelle) aus einem
 * Rezept-Objekt - bewusst eine andere, kompaktere Darstellung als das
 * Anlegen-/Bearbeiten-Formular, die alles auf einen Blick zeigt statt
 * einzelner Formularfelder.
 *
 * targetServings ist die für DIESEN Tag eingestellte Personenzahl
 * (dayServings[dayIndex], siehe openRecipeDetail) - die Zutatenmengen
 * werden auf sie hochgerechnet (statt wie vorher die für recipe.servings
 * ausgelegte Grundmenge unverändert zu zeigen), exakt nach demselben
 * Verhältnis, das auch die Einkaufsliste verwendet (siehe
 * static/plan-shopping.js: rebuildShoppingList - roundedAmount() von dort
 * wird hier für dieselbe, an- statt abgeschnittene Rundung
 * wiederverwendet). Nährwerte bleiben davon bewusst unberührt: die gelten
 * immer PRO PORTION, unabhängig von der geplanten Personenzahl. */
function renderRecipeDetailBody(recipe, targetServings) {
    const factor = recipe.servings ? targetServings / recipe.servings : 1;
    const ingredientsHtml = recipe.ingredients.length
        ? `<ul class="mb-0 ps-3">${recipe.ingredients.map(ing =>
            `<li>${escapeHtml(roundedAmount({ amount: ing.amount * factor }))} ${escapeHtml(ing.unit)} ${escapeHtml(ing.name)}</li>`
          ).join('')}</ul>`
        : '<span class="text-muted">Keine Zutaten hinterlegt.</span>';

    const instructionsHtml = recipe.instructions
        ? `<h6 class="fw-bold text-dark mt-3 mb-1">📝 Zubereitung</h6><p class="mb-0" style="white-space: pre-line;">${escapeHtml(recipe.instructions)}</p>`
        : '';

    const sourceHtml = recipe.source_url
        ? `<a href="${escapeHtml(recipe.source_url)}" target="_blank" rel="noopener noreferrer" class="badge bg-light text-dark border px-2 py-1 text-decoration-none mt-2 d-inline-block">🔗 Quelle öffnen</a>`
        : '';

    return `
        <div class="d-flex flex-wrap gap-2 align-items-center mb-3">
            <span class="badge badge-category px-3 py-2 rounded-pill">${escapeHtml(recipe.category_name)}</span>
            <span class="text-muted small">👥 ${targetServings} Personen</span>
        </div>
        <div class="text-muted small font-monospace bg-light p-2 rounded mb-3">
            📊 ${recipe.calories} kcal | E: ${recipe.protein}g | K: ${recipe.carbs}g | F: ${recipe.fat}g <span class="text-muted">(pro Portion)</span>
        </div>
        <h6 class="fw-bold text-dark mb-1">🛒 Zutaten</h6>
        ${ingredientsHtml}
        ${instructionsHtml}
        ${sourceHtml}
    `;
}

/**
 * Speichert die geänderte "Gekocht"-Checkbox des gerade offenen
 * Detail-Fensters serverseitig (routes/plan/day_actions.py:
 * set_day_cooked()/set_side_cooked()) und aktualisiert bei Erfolg sowohl
 * den lokalen Zustand (dayCooked bzw. das cooked-Feld direkt am
 * Beilagen-Objekt) als auch - über refreshDayCard()/refreshSidesSection() -
 * das Ausgrauen der betroffenen Tageskarte, ohne das Detail-Fenster dafür
 * zu schließen.
 */
function toggleDetailCooked(cooked) {
    const dayIndex = detailDayIndex;
    const sideId = detailSideId;
    const url = sideId
        ? `/day/${dayDates[dayIndex]}/side/${sideId}/cooked`
        : `/day/${dayDates[dayIndex]}/cooked`;

    postWithCsrf(url, {
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ cooked: cooked }),
    })
    .then(response => {
        if (!response.ok) throw new Error('Konnte nicht gespeichert werden.');
        return response.json();
    })
    .then(data => {
        if (sideId) {
            const side = (weeklySideRecipes[dayIndex] || []).find(s => s.side_id === sideId);
            if (side) side.cooked = data.cooked;
            refreshSidesSection(dayIndex);
        } else {
            dayCooked[dayIndex] = data.cooked;
            refreshDayCard(dayIndex);
        }
    })
    .catch(err => {
        alert('Hinweis: ' + err.message);
        // Checkbox auf den zuletzt bekannten Stand zurücksetzen, da die
        // Änderung serverseitig nicht übernommen wurde.
        document.getElementById('recipeDetailCookedCheckbox').checked = !cooked;
    });
}
