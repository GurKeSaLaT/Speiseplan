/**
 * plan-shopping.js - Wochen-Nährwertübersicht und Einkaufsliste auf der
 * Plan-Seite (templates/plan.html): fasst die Nährwerte/Zutaten aller
 * geplanten Haupt- und Zusatzgerichte einer Woche zusammen, gruppiert die
 * Einkaufsliste nach fester Supermarkt-Kategorie-Reihenfolge und verwaltet
 * zusätzlich manuell hinzugefügte Einkaufslisten-Artikel, die zu keinem
 * Rezept gehören.
 *
 * Nutzt gemeinsame Infrastruktur aus static/plan.js: die state-Arrays
 * (weeklyPlanRecipes/weeklySideRecipes/weeklyExtraItems/dayServings/
 * dayDates) und postWithCsrf(). rebuildShoppingList() wird von praktisch
 * JEDER planändernden Aktion auf der Seite aufgerufen (siehe plan.js,
 * plan-sides.js) - sie lebt hier, weil sie inhaltlich zur Einkaufsliste
 * gehört, nicht weil sie nur lokal gebraucht würde.
 */

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
