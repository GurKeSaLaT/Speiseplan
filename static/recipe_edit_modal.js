/**
 * recipe_edit_modal.js - Verwaltet das EINE wiederverwendete
 * Bearbeiten-Modal (#editModalHost) auf recipe_edit_list.html.
 *
 * Bei typischerweise 50-100+ Rezepten wäre ein eigenes, voll gerendertes
 * .modal-Element PRO Rezept (frühere Umsetzung) gleichzeitig im DOM
 * gestanden, nur per CSS versteckt - inklusive je einem Kategorie-<select>
 * pro Zutatenzeile und der Zutaten-Autovervollständigungsliste an jedem
 * Namensfeld. Das machte sich als spürbares Ruckeln bemerkbar, sobald man
 * IRGENDEIN Zutatenfeld anklickte, unabhängig davon, welches Rezept gerade
 * offen war - der Browser hält für all das (Formularvalidierung,
 * natives Autovervollständigen, Eingabehilfen-Baum) auch für unsichtbare
 * Elemente Buchhaltung.
 *
 * Jetzt liegt der Inhalt jedes Rezepts stattdessen in einem inerten
 * <template id="editModalTpl<id>"> (siehe Kommentar in
 * recipe_edit_list.html) - openEditModal() klont ihn erst beim
 * tatsächlichen Öffnen in das einzige #editModalHost-Element, wireModal
 * Behaviors() verdrahtet die pro-Modal-Logik neu (der Inhalt ist ja jedes
 * Mal frisch geklont), und beim Schließen wird der Host wieder geleert -
 * zu jedem Zeitpunkt steht so höchstens EIN Rezept mit seiner vollen
 * Zutatenliste aktiv im DOM.
 */

function openEditModal(recipeId) {
    const tpl = document.getElementById('editModalTpl' + recipeId);
    const host = document.getElementById('editModalHost');
    if (!tpl || !host) return;
    host.innerHTML = '';
    host.appendChild(tpl.content.cloneNode(true));
    wireModalBehaviors(host);
    bootstrap.Modal.getOrCreateInstance(host).show();
}

/** Pro geöffnetem Modal: Eiweiß/Kohlenhydrate/Fett-Felder je nach "manuell
 * überschreiben"-Häkchen sperren/entsperren, sowie die Kcal-Anzeige live
 * aus ihnen nachführen (rein informativ, wird nicht mitgeschickt - der
 * Server errechnet den Wert beim Speichern ohnehin selbst neu). Läuft bei
 * JEDEM Öffnen neu (statt einmalig beim Laden der Seite über alle Modals),
 * da der geklonte Inhalt bei jedem Öffnen frisch ist - vorherige Listener
 * verschwinden automatisch mit, wenn der Host beim Schließen geleert wird. */
function wireModalBehaviors(host) {
    const toggle = host.querySelector('.nutrition-override-toggle');
    if (toggle) {
        toggle.addEventListener('change', function () {
            host.querySelectorAll('input[name="protein"], input[name="carbs"], input[name="fat"]')
                .forEach(input => { input.disabled = !this.checked; });
        });
    }

    const proteinInput = host.querySelector('.nutrition-protein');
    const carbsInput = host.querySelector('.nutrition-carbs');
    const fatInput = host.querySelector('.nutrition-fat');
    const caloriesDisplay = host.querySelector('.nutrition-calories-display');
    if (proteinInput && carbsInput && fatInput && caloriesDisplay) {
        const recalcCalories = () => {
            const protein = parseFloat(proteinInput.value) || 0;
            const carbs = parseFloat(carbsInput.value) || 0;
            const fat = parseFloat(fatInput.value) || 0;
            caloriesDisplay.value = Math.round(protein * 4 + carbs * 4 + fat * 9);
        };
        [proteinInput, carbsInput, fatInput].forEach(input => input.addEventListener('input', recalcCalories));
    }
}

/** Fügt im GERADE GEÖFFNETEN Bearbeiten-Modal eine weitere leere
 * Zutaten-Zeile hinzu (analog zu addIngredientField() in
 * recipe_create.html) - recipeId identifiziert den Container innerhalb
 * des geklonten Inhalts, der (da immer nur ein Modal gleichzeitig aktiv
 * ist) im Host eindeutig ist. */
function addEditIngredientField(recipeId) {
    const container = document.getElementById('edit-ingredients-container' + recipeId);
    if (!container) return;
    const div = document.createElement('div');
    div.className = 'ingredient-row mb-1';
    div.innerHTML = `
        <div class="row g-2">
            <div class="col-4">
                <input type="text" name="ing_name[]" class="form-control form-control-sm" placeholder="Neue Zutat..." list="ingredients-datalist" autocomplete="off">
            </div>
            <div class="col-2"><input type="number" step="0.1" name="ing_amount[]" class="form-control form-control-sm" placeholder="Menge"></div>
            <div class="col-2"><input type="text" name="ing_unit[]" class="form-control form-control-sm" placeholder="Einheit"></div>
            <div class="col-3"><select name="ing_category[]" class="form-select form-select-sm" title="Einkaufslisten-Kategorie">${categoryOptionsHtml()}</select></div>
            <div class="col-1 d-grid">
                <button type="button" class="btn btn-sm btn-outline-danger" title="Zutat entfernen" onclick="this.closest('.ingredient-row').remove()">✕</button>
            </div>
        </div>
        <div class="ingredient-alias-hint small mt-1"></div>
    `;
    container.appendChild(div);
}

document.addEventListener('DOMContentLoaded', () => {
    const host = document.getElementById('editModalHost');
    // Inhalt (inkl. aller <select>/<option>) wieder freigeben, sobald das
    // Modal komplett geschlossen ist - hält den Host bis zum nächsten
    // Öffnen leer/inert, statt ihn dauerhaft mit dem zuletzt bearbeiteten
    // Rezept gefüllt zu lassen.
    if (host) {
        host.addEventListener('hidden.bs.modal', () => { host.innerHTML = ''; });
    }

    // Öffnet automatisch das Bearbeiten-Modal eines bestimmten Rezepts,
    // wenn die Seite mit ?edit=<id> aufgerufen wird - genutzt vom "✏️
    // Rezept bearbeiten"-Button im read-only Detail-Fenster auf der
    // Plan-Seite (siehe templates/plan.html/static/plan.js:
    // openRecipeDetail), der direkt zum passenden Rezept springen soll
    // statt nur zur allgemeinen Liste. Eine unbekannte/fehlende id wird
    // von openEditModal() stillschweigend ignoriert (kein <template>
    // mit diesem Namen im DOM).
    //
    // In einen DOMContentLoaded-Handler gepackt, statt sofort auszuführen:
    // dieses Skript steht (wie der ganze Seiteninhalt) VOR
    // bootstrap.bundle.min.js im DOM (siehe templates/base.html - das
    // Skript wird ganz am Ende des <body> eingebunden), ein direkter
    // Aufruf hier träfe also auf ein noch undefiniertes window.bootstrap.
    // DOMContentLoaded feuert dagegen erst, nachdem alle synchronen
    // Skripte der Seite (auch das spätere bootstrap.bundle.min.js) bereits
    // ausgeführt wurden.
    const editId = new URLSearchParams(location.search).get('edit');
    if (editId) {
        openEditModal(editId);
    }
});
