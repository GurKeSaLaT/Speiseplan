// Erstellen-Seite (create_week.html): Live-Suche, Drag-and-Drop-Zuweisung von
// Haupt-/Zusatzgerichten auf die 7 Wochentage, Ausnahme-Umschaltung. Rein
// clientseitig bis zum Formular-Submit (POST an /plan/<start_date>/generate) -
// braucht keine Server-Daten, alles kommt aus data-*-Attributen im DOM.

const searchInput = document.getElementById('searchInput');
const searchResults = document.getElementById('searchResults');
const searchItems = document.querySelectorAll('.search-item');
// Speichert die IDs der aktuell verplanten Hauptgerichte, um Duplikate zu verhindern
let assignedRecipeIds = new Set();
// Speichert die IDs der aktuell verplanten Zusatzgerichte/Beilagen, um Duplikate zu verhindern
let assignedSideRecipeIds = new Set();
// Speichert, welche Tage (Index 0-6) von der Planung ausgenommen sind
let excludedDays = new Set();

// 1. Live-Suche beim Tippen filtern
searchInput.addEventListener('input', function() {
    const query = this.value.toLowerCase().trim();
    if (query.length === 0) {
        searchResults.style.display = 'none';
        searchItems.forEach(item => item.style.setProperty('display', 'none', 'important'));
        return;
    }

    let hasResults = false;
    searchItems.forEach(item => {
        const recipeId = item.getAttribute('data-id');
        const recipeName = item.getAttribute('data-name').toLowerCase();
        const categoryName = item.getAttribute('data-category').toLowerCase();
        const isSide = item.getAttribute('data-is-side') === 'true';

        if (isSide ? assignedSideRecipeIds.has(recipeId) : assignedRecipeIds.has(recipeId)) {
            item.style.setProperty('display', 'none', 'important');
            return;
        }

        if (recipeName.includes(query) || categoryName.includes(query)) {
            item.style.setProperty('display', 'flex', 'important');
            hasResults = true;
        } else {
            item.style.setProperty('display', 'none', 'important');
        }
    });
   searchResults.style.display = hasResults ? 'block' : 'none';
});
document.addEventListener('click', function(e) {
    if (!searchInput.contains(e.target) && !searchResults.contains(e.target)) {
      searchResults.style.display = 'none';
    }
});
// 2. Klick auf Suchergebnis -> In den nächsten freien Tag werfen
//    Hauptgerichte belegen den Tages-Slot, Beilagen den unabhängigen Beilagen-Slot
searchItems.forEach(item => {
    item.addEventListener('click', function() {
      const recipeId = this.getAttribute('data-id');
      const recipeName = this.getAttribute('data-name');
      const categoryName = this.getAttribute('data-category');
      const isSide = this.getAttribute('data-is-side') === 'true';

      if (isSide) {
        // Finde die erste Dropzone ohne Beilage - auch ausgenommene Tage sind erlaubt,
        // eine Beilage blockiert den Tag nicht und ist unabhängig vom Hauptgericht
        const freeZone = Array.from(document.querySelectorAll('.day-dropzone')).find(zone =>
          zone.querySelector('.side-dish-chip') === null
        );
        if (!freeZone) {
          alert("Es ist kein freier Tag für Beilagen mehr verfügbar!");
          searchInput.value = '';
          searchResults.style.display = 'none';
          return;
        }
        assignSideToZone(freeZone, recipeId, recipeName, categoryName);
      } else {
        // Finde die erste Dropzone, die weder ausgenommen ist noch bereits ein Hauptgericht enthält
        const freeZone = Array.from(document.querySelectorAll('.day-dropzone')).find(zone =>
          !zone.classList.contains('excluded') && zone.querySelector('.draggable-recipe-card') === null
        );
        if (!freeZone) {
          alert("Es ist kein freier Tag mehr verfügbar!");
          searchInput.value = '';
          searchResults.style.display = 'none';
          return;
        }
        assignRecipeToZone(freeZone, recipeId, recipeName, categoryName);
      }
      searchInput.value = '';
      searchResults.style.display = 'none';
      searchInput.focus();
    });
});
// 3. Funktion: Rezept in eine bestimmte Zone setzen
function assignRecipeToZone(zoneElement, id, name, category) {
    const slotContainer = zoneElement.querySelector('.recipe-slot-container');
    const statusText = zoneElement.querySelector('.slot-status');
    const dayIndex = zoneElement.getAttribute('data-day-index');
    assignedRecipeIds.add(id);
    statusText.textContent = "Fest verplant";
    statusText.classList.remove('text-muted');
    statusText.classList.add('text-dark', 'fw-bold');

    // Das persistente, tag-gebundene Formularfeld auf diese Rezept-ID setzen
    const dayInput = document.getElementById('day-recipe-input-' + dayIndex);
    if (dayInput) dayInput.value = id;

    // Erstelle das ziehbare Kärtchen (rein visuell, ohne eigenes Formularfeld)
    const card = document.createElement('div');
    card.className = 'p-2 bg-white rounded border draggable-recipe-card d-flex justify-content-between align-items-center animate-fade-in';
    card.setAttribute('draggable', 'true');
    card.setAttribute('id', 'recipe-card-' + id);
    card.setAttribute('data-id', id);
    card.setAttribute('data-name', name);
    card.setAttribute('data-category', category);
    // Drag-Events an das Kärtchen hängen
    card.ondragstart = dragStart;
    card.innerHTML = `
        <div style="max-width: 85%;">
            <strong class="text-dark small d-block text-truncate">${name}</strong>
            <span class="badge badge-category" style="font-size: 0.7rem;">${category}</span>
        </div>
        <button type="button" class="btn btn-sm text-danger border-0 p-0 fs-5" onclick="removeRecipeFromZone('${id}', '${dayIndex}')">❌</button>
    `;
    slotContainer.innerHTML = '';
    slotContainer.appendChild(card);
}
// 4. Funktion: Gericht von einem Wochentag entfernen ("Kein Essen verplant")
function removeRecipeFromZone(id, dayIndex) {
    assignedRecipeIds.delete(id);
    const zone = document.getElementById('day-zone-' + dayIndex);
    if (zone) {
      zone.querySelector('.recipe-slot-container').innerHTML = '';
      const statusText = zone.querySelector('.slot-status');
      statusText.textContent = "Automatisch auffüllen";
      statusText.classList.remove('text-dark', 'fw-bold');
      statusText.classList.add('text-muted');
    }
    const dayInput = document.getElementById('day-recipe-input-' + dayIndex);
    if (dayInput) dayInput.value = '';
}

// 4b. Funktion: Zusatzgericht/Beilage in eine bestimmte Zone setzen (blockiert den Tag nicht)
function assignSideToZone(zoneElement, id, name, category) {
    const sideContainer = zoneElement.querySelector('.side-slot-container');
    const dayIndex = zoneElement.getAttribute('data-day-index');
    assignedSideRecipeIds.add(id);

    const sideInput = document.getElementById('day-side-recipe-input-' + dayIndex);
    if (sideInput) sideInput.value = id;

    const chip = document.createElement('div');
    chip.className = 'p-2 bg-white rounded border side-dish-chip d-flex justify-content-between align-items-center animate-fade-in';
    chip.setAttribute('id', 'side-card-' + id);
    chip.setAttribute('data-id', id);
    chip.innerHTML = `
        <div style="max-width: 85%;">
            <strong class="text-dark small d-block text-truncate">🥗 ${name}</strong>
            <span class="badge badge-category" style="font-size: 0.7rem;">${category}</span>
        </div>
        <button type="button" class="btn btn-sm text-danger border-0 p-0 fs-5" onclick="removeSideFromZone('${id}', '${dayIndex}')">❌</button>
    `;
    sideContainer.innerHTML = '';
    sideContainer.appendChild(chip);
}

// 4c. Funktion: Zusatzgericht/Beilage von einem Wochentag entfernen
function removeSideFromZone(id, dayIndex) {
    assignedSideRecipeIds.delete(id);
    const zone = document.getElementById('day-zone-' + dayIndex);
    if (zone) {
      zone.querySelector('.side-slot-container').innerHTML = '<span class="text-muted small fst-italic">Keine Beilage</span>';
    }
    const sideInput = document.getElementById('day-side-recipe-input-' + dayIndex);
    if (sideInput) sideInput.value = '';
}

function clearAllDays() {
    assignedRecipeIds.clear();
    assignedSideRecipeIds.clear();
    document.querySelectorAll('.day-dropzone').forEach(zone => {
      zone.querySelector('.recipe-slot-container').innerHTML = '';
      zone.querySelector('.side-slot-container').innerHTML = '<span class="text-muted small fst-italic">Keine Beilage</span>';
      const statusText = zone.querySelector('.slot-status');
      statusText.textContent = "Automatisch auffüllen";
      statusText.classList.remove('text-dark', 'fw-bold');
      statusText.classList.add('text-muted');
      const dayIndex = zone.getAttribute('data-day-index');
      const dayInput = document.getElementById('day-recipe-input-' + dayIndex);
      if (dayInput) dayInput.value = '';
      const sideInput = document.getElementById('day-side-recipe-input-' + dayIndex);
      if (sideInput) sideInput.value = '';
    });
}

// 5. Funktion: Tag von der Planung ausnehmen / wieder einschließen
function toggleExcludeDay(dayIndex) {
    const zone = document.getElementById('day-zone-' + dayIndex);
    const excludedInput = document.getElementById('day-excluded-input-' + dayIndex);
    const excludeBtn = document.getElementById('exclude-btn-' + dayIndex);
    const statusText = zone.querySelector('.slot-status');
    if (!zone || !excludedInput) return;

    const isCurrentlyExcluded = zone.classList.contains('excluded');

    if (isCurrentlyExcluded) {
      // Tag wieder einschließen
      zone.classList.remove('excluded');
      excludedInput.value = '0';
      excludedDays.delete(parseInt(dayIndex));
      statusText.textContent = "Automatisch auffüllen";
      statusText.classList.remove('text-dark', 'fw-bold');
      statusText.classList.add('text-muted');
      excludeBtn.classList.remove('btn-danger');
      excludeBtn.classList.add('btn-outline-secondary');
      excludeBtn.title = "Diesen Tag von der Planung ausnehmen";
    } else {
      // Vorher zugewiesenes Hauptgericht entfernen, dann Tag ausnehmen.
      // Eine bereits zugewiesene Beilage bleibt bestehen - "ausgenommen" heißt nur,
      // dass kein Hauptgericht gewürfelt/fest zugewiesen wird.
      const existingCard = zone.querySelector('.draggable-recipe-card');
      if (existingCard) {
        removeRecipeFromZone(existingCard.getAttribute('data-id'), dayIndex);
      }
      zone.classList.add('excluded');
      excludedInput.value = '1';
      excludedDays.add(parseInt(dayIndex));
      statusText.textContent = "Ausgenommen";
      statusText.classList.remove('text-muted');
      statusText.classList.add('text-dark', 'fw-bold');
      excludeBtn.classList.remove('btn-outline-secondary');
      excludeBtn.classList.add('btn-danger');
      excludeBtn.title = "Diesen Tag wieder in die Planung aufnehmen";
    }
}

// --- NATIVE DRAG AND DROP IMPLEMENTIERUNG ---
function dragStart(event) {
    // Speichere die ID des Kärtchens, das gezogen wird, sowie die alte Zone
    event.dataTransfer.setData("text/plain", event.target.id);
    event.dataTransfer.setData("source-zone-id", event.target.closest('.day-dropzone').id);
}

function allowDrop(event) {
    const zone = event.target.closest('.day-dropzone');
    if (zone && zone.classList.contains('excluded')) {
      return; // Kein Drop auf ausgenommene Tage erlauben
    }
    event.preventDefault();
    if (zone) {
      zone.classList.add('drag-over');
    }
}
// Entfernt das visuelle Highlight, wenn das Kärtchen die Zone verlässt
document.querySelectorAll('.day-dropzone').forEach(zone => {
    zone.addEventListener('dragleave', () => zone.classList.remove('drag-over'));
});

function drop(event) {
    event.preventDefault();
    const targetZone = event.target.closest('.day-dropzone');
    if (!targetZone || targetZone.classList.contains('excluded')) return;
    targetZone.classList.remove('drag-over');
    const cardId = event.dataTransfer.getData("text/plain");
    const sourceZoneId = event.dataTransfer.getData("source-zone-id");
    const cardElement = document.getElementById(cardId);
    if (!cardElement || sourceZoneId === targetZone.id) return;
    const sourceZone = document.getElementById(sourceZoneId);
    const sourceDayIndex = sourceZone.getAttribute('data-day-index');
    // Daten des gezogenen Elements extrahieren
    const id = cardElement.getAttribute('data-id');
    const name = cardElement.getAttribute('data-name');
    const category = cardElement.getAttribute('data-category'); // Prüfen, ob die Zielzone bereits belegt ist
    const existingTargetCard = targetZone.querySelector('.draggable-recipe-card');
    if (existingTargetCard) {
      // TAUSCH-LOGIK: Wenn die Zielzone belegt ist, tauschen wir die Gerichte einfach über Kreuz!
      const targetId = existingTargetCard.getAttribute('data-id');
      const targetName = existingTargetCard.getAttribute('data-name');
      const targetCategory = existingTargetCard.getAttribute('data-category'); // Setze das Ziel-Gericht in die Ursprungs-Zone zurück
      assignRecipeToZone(sourceZone, targetId, targetName, targetCategory);
    } else { // Wenn die alte Zone nach dem Verschieben leer wird, Status und Formularfeld zurücksetzen
      sourceZone.querySelector('.recipe-slot-container').innerHTML = '';
      const sourceStatus = sourceZone.querySelector('.slot-status');
      sourceStatus.textContent = "Automatisch auffüllen";
      sourceStatus.classList.remove('text-dark', 'fw-bold');
      sourceStatus.classList.add('text-muted');
      const sourceInput = document.getElementById('day-recipe-input-' + sourceDayIndex);
      if (sourceInput) sourceInput.value = '';
    } // Setze das gezogene Gericht fest in die neue Zielzone
    assignRecipeToZone(targetZone, id, name, category);
}
