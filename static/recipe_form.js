/**
 * recipe_form.js - Interaktion für templates/recipe_form.html, das EINE
 * gemeinsame Formular für "Rezept anlegen" UND "Rezept bearbeiten" (siehe
 * routes/recipes.py: recipe_create_view/recipe_edit_view). Vorher zwei
 * grundverschiedene Ansichten (eigene Vollseite vs. Bearbeiten-Modal) -
 * dieses Skript ersetzt sowohl das Inline-Skript aus dem früheren
 * recipe_create.html als auch static/recipe_edit_modal.js.
 *
 * Zutatenzeilen-Markup/-Klassen (.ingredient-row/.ing-name-display/
 * .ing-name-input/.ingredient-alias-hint) bleiben absichtlich unverändert -
 * static/ingredient_alias_hint.js kennt genau diese Selektoren.
 */

// --- Pillen (Beilage/Favorit/manuelle Nährwerte) & Saison-Chips ---------
// Die Checkbox selbst schaltet sich beim Klick auf das umschließende
// <label> bereits nativ um - hier wird nur noch die .on-Optik synchron
// gehalten (delegiert über "change", damit auch später hinzugefügte
// Pillen ohne erneutes Verdrahten funktionieren).
document.addEventListener('change', (e) => {
    if (e.target.matches('.rform-pill-input, .rform-chip-input')) {
        const wrapper = e.target.closest('.rform-pill, .rform-chip');
        if (wrapper) wrapper.classList.toggle('on', e.target.checked);
    }
});

// --- Ein-/ausklappbare Abschnitte (Saison, Nährwerte) -------------------
function rformToggleSection(headEl) {
    headEl.closest('.rform-section')?.classList.toggle('rform-collapsed');
}

// --- Nährwerte: manuell-eintragen-Umschalter -----------------------------
// Analog zum bisherigen nutritionOverride-Häkchen (siehe ehemals
// recipe_create.html/recipe_edit_modal.js: wireModalBehaviors) - deaktivierte
// Felder werden beim Absenden gar nicht erst mitgeschickt (HTML-Spec), der
// Server behandelt ein fehlendes Häkchen ohnehin identisch zu "automatisch
// berechnen". Zusätzlich (neu, siehe Kommentar in recipe_form.html): blendet
// zwischen der reinen Ergebnis-Anzeige und den tatsächlich editierbaren
// Eiweiß-/Kohlenhydrate-/Fett-Feldern um - vorher wurden im Mockup nur die
// (weiterhin unsichtbaren) <input>-Werte verändert, ohne dass für den
// Nutzer sichtbar etwas editierbar wurde.
function rformWireNutrition() {
    const toggle = document.getElementById('nutritionOverride');
    const fieldsWrap = document.getElementById('nutritionFields');
    const summaryWrap = document.getElementById('nutritionSummary');
    const proteinInput = document.getElementById('proteinInput');
    const carbsInput = document.getElementById('carbsInput');
    const fatInput = document.getElementById('fatInput');
    const caloriesDisplay = document.getElementById('caloriesDisplay');
    if (!toggle || !proteinInput || !carbsInput || !fatInput || !caloriesDisplay) return;

    function applyMode() {
        const manual = toggle.checked;
        [proteinInput, carbsInput, fatInput].forEach(input => { input.disabled = !manual; });
        fieldsWrap?.classList.toggle('show', manual);
        summaryWrap?.classList.toggle('hidden', manual);
        toggle.closest('.rform-pill')?.classList.toggle('on', manual);
    }

    function recalc() {
        const protein = parseFloat(proteinInput.value) || 0;
        const carbs = parseFloat(carbsInput.value) || 0;
        const fat = parseFloat(fatInput.value) || 0;
        const calories = Math.round(protein * 4 + carbs * 4 + fat * 9);
        caloriesDisplay.value = calories;
        rformUpdateNutritionBadge(calories, protein, carbs, fat);
    }

    toggle.addEventListener('change', () => { applyMode(); if (toggle.checked) recalc(); });
    [proteinInput, carbsInput, fatInput].forEach(input => input.addEventListener('input', recalc));
    applyMode();
}

function rformFormatDe(num) {
    return Number(num).toFixed(1).replace('.', ',');
}

function rformUpdateNutritionBadge(calories, protein, carbs, fat) {
    const badge = document.getElementById('nutritionBadge');
    if (badge) {
        badge.textContent = `${Math.round(calories)} kcal · E ${rformFormatDe(protein)}g · K ${rformFormatDe(carbs)}g · F ${rformFormatDe(fat)}g`;
    }
    document.querySelectorAll('.rform-nutrition-summary .stat').forEach((statEl, i) => {
        const values = [Math.round(calories), `${rformFormatDe(protein)}g`, `${rformFormatDe(carbs)}g`, `${rformFormatDe(fat)}g`];
        const numEl = statEl.querySelector('.num');
        if (numEl && values[i] !== undefined) numEl.textContent = values[i];
    });
    const pvKcal = document.getElementById('pvKcal');
    if (pvKcal) pvKcal.textContent = `${Math.round(calories)} kcal`;
}

// --- Zutatenzeilen hinzufügen/entfernen ----------------------------------
// categoryOptionsHtml() kommt aus static/ingredient_category_select.js
// (auf derselben Seite eingebunden, siehe recipe_form.html).
function rformAddIngredientRow() {
    const container = document.getElementById('ingredientsContainer');
    if (!container) return;
    const div = document.createElement('div');
    div.className = 'ingredient-row';
    div.innerHTML = `
        <div class="ing-fields">
            <input type="text" name="ing_name[]" placeholder="Neue Zutat..." list="ingredients-datalist" autocomplete="off">
            <input type="number" step="0.1" name="ing_amount[]" placeholder="Menge">
            <input type="text" name="ing_unit[]" placeholder="Einheit">
            <select name="ing_category[]" title="Einkaufslisten-Kategorie">${categoryOptionsHtml()}</select>
            <button type="button" class="rform-ing-del" title="Zutat entfernen" onclick="this.closest('.ingredient-row').remove(); rformUpdateIngredientCount();">✕</button>
        </div>
        <div class="ingredient-alias-hint small mt-1"></div>
    `;
    container.appendChild(div);
    rformUpdateIngredientCount();
}

function rformUpdateIngredientCount() {
    const n = document.querySelectorAll('#ingredientsContainer .ingredient-row').length;
    const countEl = document.getElementById('ingCount');
    if (countEl) countEl.textContent = n + (n === 1 ? ' Zutat' : ' Zutaten');
    const pvIngCount = document.getElementById('pvIngCount');
    if (pvIngCount) pvIngCount.textContent = n;
    rformUpdateChecklist();
}

// --- Import (nur im Anlegen-Modus): entry-choice-Karten + AJAX-Import ---
function rformChooseEntry(which) {
    document.getElementById('entryCardImport')?.classList.toggle('active', which === 'import');
    document.getElementById('entryCardManual')?.classList.toggle('active', which === 'manual');
    document.getElementById('importRow')?.classList.toggle('show', which === 'import');
}

function rformImportRecipe() {
    const urlInput = document.getElementById('importUrl');
    const url = urlInput.value.trim();
    if (!url) return;

    const status = document.getElementById('importStatus');
    const button = document.getElementById('importButton');
    status.textContent = 'Importiere...';
    status.className = 'form-text text-muted';
    button.disabled = true;

    fetch('/manage/recipe/import-preview', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': window.CSRF_TOKEN },
        body: JSON.stringify({ url: url }),
    })
    .then(response => response.json().then(data => ({ ok: response.ok, data: data })))
    .then(({ ok, data }) => {
        if (!ok) throw new Error(data.error || 'Import fehlgeschlagen.');
        rformApplyImportedRecipe(data);
        status.textContent = '✓ Importiert - bitte Kategorie wählen und alle Angaben prüfen.';
        status.className = 'form-text text-success fw-bold';
    })
    .catch(err => {
        status.textContent = err.message;
        status.className = 'form-text text-danger';
    })
    .finally(() => {
        button.disabled = false;
    });
}

function rformApplyImportedRecipe(data) {
    document.getElementById('nameInput').value = data.name || '';
    document.getElementById('proteinInput').value = data.protein || '';
    document.getElementById('carbsInput').value = data.carbs || '';
    document.getElementById('fatInput').value = data.fat || '';
    document.getElementById('servingsInput').value = data.servings || 2;
    const sourceUrlInput = document.getElementById('sourceUrlInput');
    if (sourceUrlInput) sourceUrlInput.value = data.source_url || '';
    const instructionsInput = document.getElementById('instructionsInput');
    if (instructionsInput) instructionsInput.value = data.instructions || '';

    const container = document.getElementById('ingredientsContainer');
    container.innerHTML = '';
    const ingredients = (data.ingredients && data.ingredients.length) ? data.ingredients : [{}];
    ingredients.forEach(ing => {
        rformAddIngredientRow();
        const rows = container.querySelectorAll('.ingredient-row');
        const lastRow = rows[rows.length - 1];
        lastRow.querySelector('[name="ing_name[]"]').value = ing.name || '';
        lastRow.querySelector('[name="ing_amount[]"]').value = ing.amount || '';
        lastRow.querySelector('[name="ing_unit[]"]').value = ing.unit || '';
    });

    rformUpdatePreview();
}

// --- Live-Vorschau (rechte Spalte) ----------------------------------------
function rformUpdatePreview() {
    const name = document.getElementById('nameInput')?.value.trim();
    const pvName = document.getElementById('pvName');
    if (pvName) pvName.textContent = name || 'Unbenanntes Rezept';

    const catSelect = document.getElementById('categoryInput');
    const pvCat = document.getElementById('pvCat');
    if (pvCat && catSelect) pvCat.textContent = catSelect.options[catSelect.selectedIndex]?.text || '';

    const servings = document.getElementById('servingsInput')?.value || '2';
    const pvServ = document.getElementById('pvServ');
    if (pvServ) pvServ.textContent = `👥 ${servings} Personen`;

    rformUpdateChecklist();
}

function rformUpdateChecklist() {
    const name = document.getElementById('nameInput')?.value.trim();
    const ingCount = document.querySelectorAll('#ingredientsContainer .ingredient-row').length;
    const instructions = document.getElementById('instructionsInput')?.value.trim();

    const ciName = document.getElementById('ciName');
    ciName?.classList.toggle('done', !!name);
    const ciIng = document.getElementById('ciIng');
    ciIng?.classList.toggle('done', ingCount > 0);
    const ciIngLabel = document.getElementById('ciIngLabel');
    if (ciIngLabel) ciIngLabel.textContent = `Zutaten (${ingCount})`;
    const ciInstr = document.getElementById('ciInstr');
    ciInstr?.classList.toggle('done', !!instructions);
}

document.addEventListener('DOMContentLoaded', () => {
    rformWireNutrition();
    rformUpdateIngredientCount();
    rformUpdatePreview();

    ['nameInput', 'categoryInput', 'servingsInput'].forEach(id => {
        document.getElementById(id)?.addEventListener('input', rformUpdatePreview);
        document.getElementById(id)?.addEventListener('change', rformUpdatePreview);
    });
    document.getElementById('instructionsInput')?.addEventListener('input', rformUpdateChecklist);

    if (window.RECIPE_NUTRITION) {
        const n = window.RECIPE_NUTRITION;
        rformUpdateNutritionBadge(n.calories, n.protein, n.carbs, n.fat);
    }
});
