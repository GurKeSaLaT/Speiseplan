/**
 * Erstellen-Seite (templates/create_week.html): Live-Suche über alle
 * Rezepte, Zuweisung per Klick oder Drag-and-Drop auf einen der 7
 * Wochentage, sowie die Ausnahme-Umschaltung ("Diesen Tag von der
 * Planung ausnehmen").
 *
 * Bewusst KOMPLETT ohne Abhängigkeit von Server-Daten geschrieben - anders
 * als static/plan.js gibt es hier kein window.PLAN_DATA. Alle nötigen
 * Informationen (Rezept-ID, Name, Kategorie, ob Beilage) stecken bereits
 * als data-*-Attribute in den vom Server gerenderten Such-Ergebnis-Buttons
 * (siehe create_week.html: .search-item), sodass dieses Skript reines DOM-
 * Handling ist, ohne selbst irgendwelche Rezeptdaten zu kennen.
 *
 * Alles hier ist rein CLIENTSEITIGER Zwischenzustand: nichts wird
 * gespeichert, bevor nicht das Formular #planForm abgeschickt wird (POST an
 * /plan/<start_date>/generate, siehe routes/plan.py: week_generate). Die
 * Zuweisung eines Rezepts zu einem Tag landet dafür in einem versteckten
 * <input type="hidden">-Feld pro Tag (day-recipe-input-<i> bzw.
 * day-side-recipe-input-<i>), das Formular selbst wird von den sichtbaren
 * "Kärtchen" nur SPIEGELND begleitet - ein Kärtchen zu verschieben/löschen
 * heißt also immer auch, das zugehörige Formularfeld zu aktualisieren.
 */

const searchInput = document.getElementById('searchInput');
const searchResults = document.getElementById('searchResults');
const searchItems = document.querySelectorAll('.search-item');

// Verhindert, dass ein und dasselbe Rezept an zwei verschiedenen Tagen
// gleichzeitig fest zugewiesen wird: bereits zugewiesene IDs werden aus
// der Live-Suche ausgeblendet (siehe Suchfilter unten). Haupt- und
// Beilagen-Zuweisungen führen getrennte Sets, da beide Pools unabhängig
// voneinander sind (ein Rezept ist entweder Hauptgericht ODER Beilage,
// nie beides zugleich - siehe models.py: Recipe.is_side_dish).
let assignedRecipeIds = new Set();
let assignedSideRecipeIds = new Set();

// Welche Tage (Index 0-6) aktuell als "von der Planung ausgenommen"
// markiert sind. Wird aktuell nur geschrieben (toggleExcludeDay), nirgends
// mehr ausgelesen - der maßgebliche Zustand für den Formular-Submit steckt
// im "excluded"-CSS-Klasse/versteckten Input je Tag, nicht in diesem Set.
let excludedDays = new Set();

// 1. Live-Suche: filtert die Ergebnisliste bei jedem Tastendruck. Ein
// Suchtreffer zählt bei Übereinstimmung im Rezeptnamen ODER im
// Kategorienamen (z.B. "Pasta" findet sowohl "Spaghetti" (Kategorie
// Pasta) als auch ein Rezept, das "Pasta" im eigenen Namen trägt).
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

        // Bereits verplante Rezepte werden komplett aus der Trefferliste
        // ausgeblendet (nicht nur ausgegraut) - ein zweites Mal anklicken
        // wäre ohnehin sinnlos, da jedes Rezept höchstens einmal pro
        // Woche fest zugewiesen werden kann.
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

// Schließt das Ergebnis-Dropdown, sobald irgendwo außerhalb von Suchfeld
// oder Ergebnisliste geklickt wird (typisches "Klick daneben schließt
// Dropdown"-Verhalten).
document.addEventListener('click', function(e) {
    if (!searchInput.contains(e.target) && !searchResults.contains(e.target)) {
      searchResults.style.display = 'none';
    }
});

// 2. Klick auf ein Suchergebnis weist es automatisch dem NÄCHSTEN freien
// Tag zu (statt selbst per Drag-and-Drop platziert werden zu müssen) -
// Hauptgerichte suchen sich dabei einen Tag ohne Hauptgericht, Beilagen
// einen Tag ohne Beilage; beide Slots sind unabhängig voneinander frei/belegt.
searchItems.forEach(item => {
    item.addEventListener('click', function() {
      const recipeId = this.getAttribute('data-id');
      const recipeName = this.getAttribute('data-name');
      const categoryName = this.getAttribute('data-category');
      const isSide = this.getAttribute('data-is-side') === 'true';

      if (isSide) {
        // Beilagen dürfen auch auf einen bereits ausgenommenen Tag - eine
        // Beilage blockiert den Tag nicht und ist komplett unabhängig vom
        // Hauptgericht-Ausnahme-Status (siehe models.py: PlanDay).
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
        // Hauptgerichte dagegen brauchen einen Tag, der WEDER ausgenommen
        // NOCH bereits belegt ist.
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

// 3. Weist ein Hauptgericht einer bestimmten Tages-Dropzone zu: aktualisiert
// den Status-Text, setzt das versteckte Formularfeld und baut das
// sichtbare, per Drag-and-Drop verschiebbare "Kärtchen" auf. Wird sowohl
// vom Klick-auf-Suchergebnis-Handler (oben) als auch von der
// Drag-and-Drop-Logik (drop(), weiter unten) aufgerufen - daher als
// eigenständige, wiederverwendbare Funktion statt inline im Klick-Handler.
function assignRecipeToZone(zoneElement, id, name, category) {
    const slotContainer = zoneElement.querySelector('.recipe-slot-container');
    const statusText = zoneElement.querySelector('.slot-status');
    const dayIndex = zoneElement.getAttribute('data-day-index');
    assignedRecipeIds.add(id);
    statusText.textContent = "Fest verplant";
    statusText.classList.remove('text-muted');
    statusText.classList.add('text-dark', 'fw-bold');

    // Das eigentlich für den Formular-Submit entscheidende Feld - unabhängig
    // vom sichtbaren Kärtchen, das rein zur Darstellung/zum Ziehen dient.
    const dayInput = document.getElementById('day-recipe-input-' + dayIndex);
    if (dayInput) dayInput.value = id;

    const card = document.createElement('div');
    card.className = 'p-2 bg-white rounded border draggable-recipe-card d-flex justify-content-between align-items-center animate-fade-in';
    card.setAttribute('draggable', 'true');
    card.setAttribute('id', 'recipe-card-' + id);
    card.setAttribute('data-id', id);
    card.setAttribute('data-name', name);
    card.setAttribute('data-category', category);
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

// 4. Entfernt ein Hauptgericht wieder von einem Tag (Kärtchen weg, Status
// zurück auf "Automatisch auffüllen", verstecktes Feld geleert) - macht
// assignRecipeToZone() für genau diesen Tag rückgängig.
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

// 4b. Pendant zu assignRecipeToZone() für Beilagen: eigener Container
// (.side-slot-container), eigenes verstecktes Feld, kein Status-Text (der
// gehört nur zum Hauptgericht-Slot) und kein Drag-and-Drop (Beilagen-Chips
// sind bewusst nicht ziehbar - nur Hauptgerichte lassen sich zwischen
// Tagen verschieben).
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

// 4c. Entfernt eine Beilage wieder - macht assignSideToZone() rückgängig.
function removeSideFromZone(id, dayIndex) {
    assignedSideRecipeIds.delete(id);
    const zone = document.getElementById('day-zone-' + dayIndex);
    if (zone) {
      zone.querySelector('.side-slot-container').innerHTML = '<span class="text-muted small fst-italic">Keine Beilage</span>';
    }
    const sideInput = document.getElementById('day-side-recipe-input-' + dayIndex);
    if (sideInput) sideInput.value = '';
}

// Setzt ALLE 7 Tage auf einmal zurück (Button "Alle leeren") - ruft dafür
// nicht etwa removeRecipeFromZone()/removeSideFromZone() für jeden Tag auf,
// sondern setzt Status und Felder direkt selbst zurück, da hier ohnehin
// jede Zone unabhängig von ihrem aktuellen Inhalt komplett neu aufgesetzt
// wird (ob dort überhaupt ein Kärtchen steckte, spielt keine Rolle).
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

// 5. Schaltet einen Tag zwischen "wird automatisch aufgefüllt" und "von der
// Hauptgericht-Planung ausgenommen" um (🚫-Button). Ausnehmen entfernt
// dabei automatisch ein eventuell bereits zugewiesenes Hauptgericht (ein
// ausgenommener Tag soll keins bekommen) - eine bereits zugewiesene
// Beilage bleibt dagegen unangetastet stehen, da "ausgenommen" sich per
// Definition NUR auf das Hauptgericht bezieht.
function toggleExcludeDay(dayIndex) {
    const zone = document.getElementById('day-zone-' + dayIndex);
    const excludedInput = document.getElementById('day-excluded-input-' + dayIndex);
    const excludeBtn = document.getElementById('exclude-btn-' + dayIndex);
    const statusText = zone.querySelector('.slot-status');
    if (!zone || !excludedInput) return;

    const isCurrentlyExcluded = zone.classList.contains('excluded');

    if (isCurrentlyExcluded) {
      // Tag wieder in die automatische Planung aufnehmen.
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
// Nutzt die eingebaute HTML5-Drag-and-Drop-API (draggable="true" +
// dragstart/dragover/drop-Events, siehe zugehörige on*-Attribute in
// create_week.html) statt einer externen Bibliothek - für den einfachen
// Anwendungsfall "ein Kärtchen von einer Tages-Box in eine andere ziehen"
// reicht das vollständig aus.

function dragStart(event) {
    // dataTransfer ist der einzige Weg, Informationen vom Start- zum
    // Zielelement eines Drags zu transportieren: die ID des gezogenen
    // Kärtchens UND die ID seiner AKTUELLEN (Ursprungs-)Zone werden hier
    // hinterlegt, damit drop() weiter unten beide wieder auslesen kann.
    event.dataTransfer.setData("text/plain", event.target.id);
    event.dataTransfer.setData("source-zone-id", event.target.closest('.day-dropzone').id);
}

function allowDrop(event) {
    const zone = event.target.closest('.day-dropzone');
    if (zone && zone.classList.contains('excluded')) {
      return; // Kein Drop auf ausgenommene Tage erlauben
    }
    // event.preventDefault() ist zwingend nötig, damit der Browser das
    // "drop"-Event überhaupt zulässt - ohne das gilt eine Zone per
    // HTML5-Drag-and-Drop-API standardmäßig als "kein gültiges Ziel".
    event.preventDefault();
    if (zone) {
      zone.classList.add('drag-over');
    }
}

// Entfernt das visuelle Hervorheben (drag-over-Rahmen), sobald das
// gezogene Kärtchen eine Zone wieder verlässt, ohne dort abgelegt zu
// werden.
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
    // Kein gültiges Kärtchen gefunden, oder auf sich selbst fallengelassen
    // (Quelle == Ziel) -> nichts zu tun.
    if (!cardElement || sourceZoneId === targetZone.id) return;
    const sourceZone = document.getElementById(sourceZoneId);
    const sourceDayIndex = sourceZone.getAttribute('data-day-index');
    const id = cardElement.getAttribute('data-id');
    const name = cardElement.getAttribute('data-name');
    const category = cardElement.getAttribute('data-category');

    const existingTargetCard = targetZone.querySelector('.draggable-recipe-card');
    if (existingTargetCard) {
      // TAUSCH-LOGIK: Ist die Zielzone bereits belegt, werden beide
      // Gerichte einfach über Kreuz getauscht, statt den Drop schlicht
      // abzulehnen - fühlt sich für den Nutzer intuitiver an ("zwei Tage
      // vertauschen" statt "erst den einen Tag leeren müssen").
      const targetId = existingTargetCard.getAttribute('data-id');
      const targetName = existingTargetCard.getAttribute('data-name');
      const targetCategory = existingTargetCard.getAttribute('data-category');
      assignRecipeToZone(sourceZone, targetId, targetName, targetCategory);
    } else {
      // Zielzone war leer: die Ursprungszone wird jetzt frei, muss also
      // selbst auf ihren Leerzustand zurückgesetzt werden (Status-Text,
      // Formularfeld) - das übernimmt assignRecipeToZone() für die
      // NEUE Zone weiter unten nicht automatisch mit.
      sourceZone.querySelector('.recipe-slot-container').innerHTML = '';
      const sourceStatus = sourceZone.querySelector('.slot-status');
      sourceStatus.textContent = "Automatisch auffüllen";
      sourceStatus.classList.remove('text-dark', 'fw-bold');
      sourceStatus.classList.add('text-muted');
      const sourceInput = document.getElementById('day-recipe-input-' + sourceDayIndex);
      if (sourceInput) sourceInput.value = '';
    }
    // In beiden Fällen (Tausch oder einfaches Verschieben) landet das
    // gezogene Gericht am Ende fest in der Zielzone.
    assignRecipeToZone(targetZone, id, name, category);
}
