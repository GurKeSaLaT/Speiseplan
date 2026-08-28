/**
 * plan.js - Client-seitige Logik der Wochenplan-Ansicht (templates/plan.html).
 *
 * Verantwortlich für alles, was auf der Plan-Seite ohne Neuladen der Seite
 * passiert: einzelne Tage neu würfeln (Haupt- und Beilagengericht), zwei
 * Tage per Drag-and-Drop komplett tauschen, die Personenzahl pro Tag ändern,
 * sowie die daraus abgeleiteten Übersichten (Wochen-Nährwerte, Einkaufsliste)
 * live neu berechnen, ohne dafür die Seite neu laden zu müssen.
 *
 * Jede Aktion, die den Plan verändert (würfeln, tauschen, Personenzahl,
 * Beilage entfernen), schickt zuerst einen fetch()-Request an den Server
 * (siehe routes/plan.py), der die Änderung in der Datenbank persistiert -
 * erst wenn die Antwort erfolgreich war, wird auch der lokale JavaScript-
 * Speicher und das DOM aktualisiert. Ein Fehlschlag (z.B. "keine
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

// Zusatzgerichte/Beilagen, unabhängig vom Hauptgericht (Index = Wochentag, null = keine Beilage)
let weeklySideRecipes = window.PLAN_DATA.sidePlan;

// Beim ersten Laden der Seite die Einkaufsliste (und darüber auch die
// Wochen-Nährwertübersicht, siehe rebuildShoppingList) einmal aus den
// bereits vom Server mitgelieferten Daten aufbauen - ab dann übernehmen die
// einzelnen Aktionen unten das Neu-Berechnen bei jeder Änderung.
document.addEventListener('DOMContentLoaded', () => {
    rebuildShoppingList();
});

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

    fetch(`/day/${dayDates[dayIndex]}/reroll-main`, { method: 'POST' })
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
 * Erzeugt das HTML für die Beilagen-Zeile einer Tageskarte. Zwei
 * Zustände: ist bereits eine Beilage zugewiesen, wird sie mit
 * Neu-würfeln- und Entfernen-Button dargestellt; ist keine zugewiesen,
 * erscheint stattdessen nur ein "Beilage würfeln"-Button über die volle
 * Breite. Wird sowohl beim initialen Rendern (renderDayCardBody) als auch
 * nach jedem erfolgreichen Beilagen-Reroll/-Entfernen erneut aufgerufen,
 * um exakt dasselbe Markup ohne Duplikation zu erzeugen.
 */
function renderSideRow(dayIndex, recipe) {
    if (recipe) {
        return `
            <div class="d-flex justify-content-between align-items-center side-dish-card">
                <div>
                    <span class="fw-bold text-dark side-dish-name">🥗 ${recipe.name}</span>
                    <span class="badge badge-category side-dish-category ms-1">${recipe.category_name}</span>
                    <span class="text-muted small side-dish-kcal">(${recipe.calories} kcal)</span>
                </div>
                <div class="d-flex align-items-center gap-1">
                    <button type="button" class="btn btn-sm btn-outline-secondary border-0 p-1" title="Beilage neu würfeln" onclick="rerollSideDay(${dayIndex})">🎲</button>
                    <button type="button" class="btn btn-sm text-danger border-0 p-1" title="Beilage entfernen" onclick="removeSideDish(${dayIndex})">❌</button>
                </div>
            </div>
        `;
    }
    return `<button type="button" class="btn btn-sm btn-outline-secondary w-100" onclick="rerollSideDay(${dayIndex})">🥗 Beilage würfeln</button>`;
}

/**
 * Baut den kompletten Innenbereich einer Tageskarte auf: Personenzahl-Zeile,
 * Hauptgericht-Block (oder Platzhaltertext, falls kein Rezept zugewiesen
 * ist bzw. der Tag ausgenommen wurde) und Beilagen-Zeile. Liest dabei
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

    const recipe = weeklyPlanRecipes[dayIndex];
    let mainHtml;
    if (recipe) {
        mainHtml = `
            <div class="d-flex justify-content-between align-items-start mb-2">
                <div>
                    <h5 class="text-success fw-bold mb-0" style="color: var(--primary-food) !important;">${dayLabels[dayIndex]}</h5>
                    <span class="recipe-name fw-bold fs-5 text-dark d-block mt-1">${recipe.name}</span>
                </div>
                <div class="d-flex align-items-center gap-2">
                    <span class="badge badge-category recipe-category px-3 py-2 rounded-pill">${recipe.category_name}</span>
                    <button type="button" class="btn btn-sm btn-outline-secondary border-0 p-2 fs-5" title="Diesen Tag neu würfeln" onclick="rerollSingleDay(${dayIndex})">🎲</button>
                </div>
            </div>
            <div class="text-muted small font-monospace bg-light p-2 rounded">
                📊 <span class="recipe-kcal">${recipe.calories}</span> kcal |
                E: <span class="recipe-protein">${recipe.protein}</span>g |
                K: <span class="recipe-carbs">${recipe.carbs}</span>g |
                F: <span class="recipe-fat">${recipe.fat}</span>g
            </div>
        `;
    } else {
        // Zwei mögliche Gründe für ein leeres Hauptgericht: der Tag wurde
        // bewusst ausgenommen (Checkbox), oder die automatische Planung hat
        // schlicht kein passendes Rezept mehr gefunden (z.B. Kategorie
        // erschöpft) - beide Fälle bekommen einen eigenen, unterscheidbaren
        // Hinweistext statt einer nichtssagend leeren Karte.
        const placeholderText = dayExcluded[dayIndex] ? '🚫 Von der Planung ausgenommen' : 'Kein passendes Rezept verfügbar';
        mainHtml = `
            <div class="text-center text-muted">
                <h5 class="fw-bold mb-1">${dayLabels[dayIndex]}</h5>
                <span>${placeholderText}</span>
            </div>
        `;
    }

    const sideHtml = `<div class="side-dish-row mt-2 pt-2 border-top" id="side-row-${dayIndex}">${renderSideRow(dayIndex, weeklySideRecipes[dayIndex])}</div>`;

    return servingsHtml + mainHtml + sideHtml;
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

    fetch(`/day/${dayDates[dayIndex]}/servings`, {
        method: 'POST',
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
    const sideRecipe = weeklySideRecipes[dayIndex];
    card.setAttribute('data-recipe-id', recipe ? recipe.id : '');
    card.setAttribute('data-category-id', recipe ? recipe.category_id : '');
    card.setAttribute('data-side-recipe-id', sideRecipe ? sideRecipe.id : '');
    card.innerHTML = renderDayCardBody(dayIndex);
}

// --- TAGE TAUSCHEN PER DRAG-AND-DROP ---
// Nutzt die native HTML5-Drag-and-Drop-API. Getauscht werden Hauptgericht,
// Beilage UND der Ausnahme-Status der beiden Tage komplett miteinander (die
// Personenzahl bewusst NICHT, siehe Kommentar bei dayServings oben) - der
// Tausch wird über /day/<datum>/swap/<datum> serverseitig persistiert,
// bevor die lokale Anzeige aktualisiert wird.

/** Merkt beim Start des Ziehens die HTML-id der Quellkarte im DataTransfer. */
function daySwapDragStart(event) {
    event.dataTransfer.setData('text/plain', event.currentTarget.id);
}

/** Erlaubt das Ablegen auf dieser Karte (sonst ignoriert der Browser drop-Events per Default) und markiert sie optisch. */
function daySwapAllowDrop(event) {
    event.preventDefault();
    event.currentTarget.classList.add('drag-over');
}

/**
 * Führt den eigentlichen Tausch aus, sobald eine Karte auf einer anderen
 * abgelegt wird: liest zunächst die Quellkarte aus dem DataTransfer, bricht
 * bei fehlender/identischer Quelle ab, ruft dann den Server-Endpunkt auf
 * und tauscht erst nach dessen Bestätigung die drei betroffenen Arrays
 * (weeklyPlanRecipes, weeklySideRecipes, dayExcluded) per
 * Destrukturierungs-Swap, bevor beide Karten neu gerendert werden.
 */
function daySwapDrop(event) {
    event.preventDefault();
    const targetCard = event.currentTarget;
    targetCard.classList.remove('drag-over');

    const sourceId = event.dataTransfer.getData('text/plain');
    if (!sourceId || sourceId === targetCard.id) return;
    const sourceCard = document.getElementById(sourceId);
    if (!sourceCard) return;

    const i = parseInt(sourceCard.getAttribute('data-day-index'));
    const j = parseInt(targetCard.getAttribute('data-day-index'));
    if (i === j) return;

    fetch(`/day/${dayDates[i]}/swap/${dayDates[j]}`, { method: 'POST' })
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
 * Würfelt die Beilage eines Tages neu (unabhängig vom Hauptgericht -
 * funktioniert auch, wenn noch gar keine Beilage zugewiesen war, ruft dann
 * serverseitig effektiv eine erstmalige Zuweisung auf). Aktualisiert bei
 * Erfolg nur die Beilagen-Zeile dieses Tages (renderSideRow), nicht die
 * ganze Karte.
 */
function rerollSideDay(dayIndex) {
    const dayCard = document.getElementById(`day-card-${dayIndex}`);
    const sideRow = document.getElementById(`side-row-${dayIndex}`);
    if (!dayCard || !sideRow) return;

    fetch(`/day/${dayDates[dayIndex]}/reroll-side`, { method: 'POST' })
    .then(response => {
        if (!response.ok) return response.json().then(data => { throw new Error(data.error || 'Keine weitere Beilage verfügbar.'); });
        return response.json();
    })
    .then(newRecipe => {
        dayCard.setAttribute('data-side-recipe-id', newRecipe.id);
        sideRow.innerHTML = renderSideRow(dayIndex, newRecipe);
        weeklySideRecipes[dayIndex] = newRecipe;
        rebuildShoppingList();
    })
    .catch(err => {
        alert('Hinweis: ' + err.message);
    });
}

/**
 * Entfernt eine bereits zugewiesene Beilage von einem Tag wieder komplett
 * (im Gegensatz zu rerollSideDay, das durch eine ANDERE Beilage ersetzt).
 * Nach Erfolg zeigt die Beilagen-Zeile wieder nur den "Beilage würfeln"-
 * Button (siehe renderSideRow mit recipe=null).
 */
function removeSideDish(dayIndex) {
    const dayCard = document.getElementById(`day-card-${dayIndex}`);
    const sideRow = document.getElementById(`side-row-${dayIndex}`);
    if (!dayCard || !sideRow) return;

    fetch(`/day/${dayDates[dayIndex]}/remove-side`, { method: 'POST' })
    .then(response => {
        if (!response.ok) throw new Error('Entfernen fehlgeschlagen.');
        dayCard.setAttribute('data-side-recipe-id', '');
        sideRow.innerHTML = renderSideRow(dayIndex, null);
        weeklySideRecipes[dayIndex] = null;
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
        [weeklyPlanRecipes[i], weeklySideRecipes[i]].forEach(recipe => {
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
 * Rechnet die komplette Einkaufsliste der Woche aus dem aktuellen
 * JavaScript-Speicher neu zusammen und rendert sie. Wird nach JEDER
 * Änderung am Plan aufgerufen (würfeln, tauschen, Personenzahl,
 * Beilage entfernen), da praktisch jede dieser Änderungen die benötigten
 * Zutatenmengen beeinflusst. Ruft dabei auch rebuildWeeklyNutritionSummary()
 * mit auf, da beide Übersichten stets gemeinsam aktuell gehalten werden.
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
        [weeklyPlanRecipes[i], weeklySideRecipes[i]].forEach(recipe => {
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
                    } else {
                        consolidated[key] = { name: ing.name, amount: scaledAmount, unit: ing.unit };
                    }
                });
            }
        });
    }

    const items = Object.values(consolidated);
    if (counterBadge) counterBadge.textContent = items.length;

    if (items.length === 0) {
        container.innerHTML = '<li class="list-group-item text-center text-muted my-3">Keine Zutaten für diese Woche benötigt.</li>';
        return;
    }

    // Alphabetisch sortieren
    items.sort((a, b) => a.name.localeCompare(b.name));

    items.forEach(item => {
        const li = document.createElement('li');
        li.className = 'list-group-item d-flex justify-content-between align-items-center py-2 px-3';
        // Auf 2 Nachkommastellen runden, um Fließkomma-Artefakte durch die
        // Personen-Skalierung zu vermeiden (z.B. 133.33333333333334 -> 133.33)
        const displayAmount = Math.round(item.amount * 100) / 100;
        li.innerHTML = `
            <label class="d-flex align-items-center m-0 flex-grow-1" style="cursor: pointer;">
                <input type="checkbox" class="form-check-input me-3" style="transform: scale(1.15);">
                <span class="text-dark fs-5">${item.name}</span>
            </label>
            <span class="badge bg-success px-3 py-2 rounded-pill font-monospace" style="background-color: var(--primary-food) !important; font-size: 0.9rem;">
                ${displayAmount} ${item.unit}
            </span>
        `;

        // Checkbox dient rein der Anzeige beim Einkaufen (durchgestrichen +
        // ausgegraut, sobald abgehakt) - der Zustand wird bewusst NICHT
        // gespeichert (weder serverseitig noch in localStorage), da die
        // Liste ohnehin bei jeder Planänderung komplett neu aufgebaut wird.
        const checkbox = li.querySelector('input[type="checkbox"]');
        checkbox.addEventListener('change', function() {
            const span = li.querySelector('span.text-dark');
            if (this.checked) {
                span.style.textDecoration = 'line-through';
                span.style.opacity = '0.5';
            } else {
                span.style.textDecoration = 'none';
                span.style.opacity = '1';
            }
        });

        container.appendChild(li);
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
