// Plan-Seite (plan.html): Live-Interaktionen für den dauerhaften Wochenplan
// (würfeln, tauschen, Beilage, Personenzahl, Einkaufsliste, Wochen-Nährwert-
// übersicht) sowie der Wochen-Sprung-Datepicker. Erwartet, dass window.PLAN_DATA
// (siehe plan.html) vor diesem Script gesetzt wurde.

const dayLabels = window.PLAN_DATA.dayLabels;
const dayDates = window.PLAN_DATA.weekDates;
let dayExcluded = window.PLAN_DATA.excludedDays;
// Für wie viele Personen an jedem Wochentag eingekauft werden soll (Index = Wochentag,
// aus der Datenbank vorbefüllt). Bleibt an den Wochentag gebunden, nicht ans Gericht -
// wandert beim Tage-Tausch also NICHT mit.
let dayServings = window.PLAN_DATA.servingsList;
// Rezepte im JavaScript-Speicher (Index = Wochentag, null = kein Rezept)
let weeklyPlanRecipes = window.PLAN_DATA.plan;
// Zusatzgerichte/Beilagen, unabhängig vom Hauptgericht (Index = Wochentag, null = keine Beilage)
let weeklySideRecipes = window.PLAN_DATA.sidePlan;

// Initiales Rendern beim Laden der Seite
document.addEventListener('DOMContentLoaded', () => {
    rebuildShoppingList();
});

// Funktion zum Neu-Würfeln eines einzelnen Wochentags (persistiert serverseitig)
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

// Baut den HTML-Inhalt einer Beilagen-Zeile für einen Tag auf (mit oder ohne Beilage)
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

// Baut den kompletten Innenbereich einer Tageskarte (Personen-Zeile + Hauptgericht-Block
// + Beilagen-Zeile) aus dem aktuellen JavaScript-Speicher auf - wird nach einem
// Tage-Tausch pro Tag neu gerendert
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

// Setzt die Personenzahl für einen Wochentag (optimistisch sofort übernommen für
// reaktionsschnelle UI) und speichert sie serverseitig
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

// Aktualisiert Datenattribute und Inhalt einer Tageskarte anhand des aktuellen
// JavaScript-Speichers (weeklyPlanRecipes/weeklySideRecipes/dayExcluded)
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
// Tauscht Hauptgericht, Beilage UND Ausnahme-Status zweier Tage komplett miteinander -
// serverseitig persistiert, die Personenzahl bleibt bewusst am Wochentag hängen.
function daySwapDragStart(event) {
    event.dataTransfer.setData('text/plain', event.currentTarget.id);
}

function daySwapAllowDrop(event) {
    event.preventDefault();
    event.currentTarget.classList.add('drag-over');
}

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

// Funktion zum (Neu-)Würfeln einer Beilage für einen einzelnen Wochentag (persistiert serverseitig)
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

// Funktion zum Entfernen einer bereits zugewiesenen Beilage (serverseitig persistiert)
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

// Nährwerte aller Tage (Haupt- + Zusatzgericht) zur Wochenübersicht aufsummieren.
// Unskaliert (Nährwerte sind immer pro Portion/Person, unabhängig von der
// Personenzahl - die betrifft nur die Zutatenmengen der Einkaufsliste).
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

// Einkaufsliste zusammenrechnen und darstellen
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
// ist aber unsichtbar und wird per Klick auf das Textfeld geöffnet.
(function() {
    const display = document.getElementById('weekDateDisplay');
    const picker = document.getElementById('weekDatePicker');
    if (!display || !picker) return;

    display.addEventListener('click', () => {
        if (picker.showPicker) {
            picker.showPicker();
        } else {
            picker.focus();
        }
    });

    picker.addEventListener('change', () => {
        if (picker.value) {
            location.href = '/plan/' + picker.value;
        }
    });
})();
