/**
 * Week creation page: live search, assigning dishes to days by click or
 * drag and drop, and excluding days.
 *
 * Pure DOM work: recipe data comes from the search items' data-*
 * attributes, and nothing is saved until the form is submitted. A main
 * dish lives in one hidden input per day (day-recipe-input-<i>); each side
 * dish gets its own hidden input named day_side_recipes_<i>[], read as a
 * list by the server.
 */

const searchInput = document.getElementById('searchInput');
const searchResults = document.getElementById('searchResults');
const searchItems = document.querySelectorAll('.search-item');

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Assigned recipes are hidden from the search so a recipe is used at most
// once per week. Several different sides on one day are fine.
let assignedRecipeIds = new Set();
let assignedSideRecipeIds = new Set();

let excludedDays = new Set();

// Matches the recipe name or its category name.
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

// Clicking a result: a main dish goes to the first free, non-excluded day;
// a side goes to the day with the fewest sides (excluded days included),
// so repeated clicks spread sides across the week.
searchItems.forEach(item => {
    item.addEventListener('click', function() {
      const recipeId = this.getAttribute('data-id');
      const recipeName = this.getAttribute('data-name');
      const categoryName = this.getAttribute('data-category');
      const isSide = this.getAttribute('data-is-side') === 'true';

      if (isSide) {
        let targetZone = null;
        let fewestSides = Infinity;
        document.querySelectorAll('.day-dropzone').forEach(zone => {
          const count = zone.querySelectorAll('.side-dish-chip').length;
          if (count < fewestSides) {
            fewestSides = count;
            targetZone = zone;
          }
        });
        assignSideToZone(targetZone, recipeId, recipeName, categoryName);
      } else {
        const freeZone = Array.from(document.querySelectorAll('.day-dropzone')).find(zone =>
          !zone.classList.contains('excluded') && zone.querySelector('.draggable-recipe-card') === null
        );
        if (!freeZone) {
          alert(window.I18N.no_free_day);
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

/** Sets the day's hidden input (what gets submitted) and its visible,
 * draggable card. */
function assignRecipeToZone(zoneElement, id, name, category) {
    const slotContainer = zoneElement.querySelector('.recipe-slot-container');
    const statusText = zoneElement.querySelector('.slot-status');
    const dayIndex = zoneElement.getAttribute('data-day-index');
    assignedRecipeIds.add(id);
    statusText.textContent = window.I18N.day_planned;
    statusText.classList.remove('text-muted');
    statusText.classList.add('text-dark', 'fw-bold');

    const dayInput = document.getElementById('day-recipe-input-' + dayIndex);
    if (dayInput) dayInput.value = id;

    const card = document.createElement('div');
    card.className = 'assigned-pill draggable-recipe-card';
    card.setAttribute('draggable', 'true');
    card.setAttribute('id', 'recipe-card-' + id);
    card.setAttribute('data-id', id);
    card.setAttribute('data-name', name);
    card.setAttribute('data-category', category);
    card.ondragstart = dragStart;
    card.innerHTML = `
        <span class="name">${escapeHtml(name)}</span>
        <button type="button" class="x" onclick="removeRecipeFromZone('${id}', '${dayIndex}')" aria-label="Remove">✕</button>
    `;
    slotContainer.innerHTML = '';
    slotContainer.appendChild(card);
}

function removeRecipeFromZone(id, dayIndex) {
    assignedRecipeIds.delete(id);
    const zone = document.getElementById('day-zone-' + dayIndex);
    if (zone) {
      zone.querySelector('.recipe-slot-container').innerHTML = '';
      const statusText = zone.querySelector('.slot-status');
      statusText.textContent = window.I18N.day_fill_automatically;
      statusText.classList.remove('text-dark', 'fw-bold');
      statusText.classList.add('text-muted');
    }
    const dayInput = document.getElementById('day-recipe-input-' + dayIndex);
    if (dayInput) dayInput.value = '';
}

/** Adds a side (never replaces), with its own hidden input. Sides aren't
 * draggable here; they can be moved on the finished plan page. */
function assignSideToZone(zoneElement, id, name, category) {
    const sideContainer = zoneElement.querySelector('.side-slot-container');
    const dayIndex = zoneElement.getAttribute('data-day-index');
    assignedSideRecipeIds.add(id);

    const placeholder = sideContainer.querySelector('.no-side-placeholder');
    if (placeholder) placeholder.remove();

    const chip = document.createElement('div');
    chip.className = 'side-dish-chip';
    chip.setAttribute('id', 'side-card-' + id);
    chip.setAttribute('data-id', id);
    chip.innerHTML = `
        <span class="text-truncate">🥗 ${escapeHtml(name)}</span>
        <button type="button" class="x" onclick="removeSideFromZone('${id}', '${dayIndex}')" aria-label="Remove">✕</button>
    `;
    sideContainer.appendChild(chip);

    const sideInput = document.createElement('input');
    sideInput.type = 'hidden';
    sideInput.name = `day_side_recipes_${dayIndex}[]`;
    sideInput.value = id;
    sideInput.setAttribute('id', 'side-input-' + id);
    zoneElement.appendChild(sideInput);
}

function removeSideFromZone(id, dayIndex) {
    assignedSideRecipeIds.delete(id);
    const chip = document.getElementById('side-card-' + id);
    if (chip) chip.remove();
    const sideInput = document.getElementById('side-input-' + id);
    if (sideInput) sideInput.remove();

    const zone = document.getElementById('day-zone-' + dayIndex);
    const sideContainer = zone && zone.querySelector('.side-slot-container');
    if (sideContainer && sideContainer.children.length === 0) {
        sideContainer.innerHTML = `<span class="no-side no-side-placeholder">${escapeHtml(window.I18N.no_side_dish)}</span>`;
    }
}

/** "Clear all": resets every day, including removing the per-side inputs. */
function clearAllDays() {
    assignedRecipeIds.clear();
    assignedSideRecipeIds.clear();
    document.querySelectorAll('.day-dropzone').forEach(zone => {
      zone.querySelector('.recipe-slot-container').innerHTML = '';
      zone.querySelector('.side-slot-container').innerHTML = `<span class="no-side no-side-placeholder">${escapeHtml(window.I18N.no_side_dish)}</span>`;
      const statusText = zone.querySelector('.slot-status');
      statusText.textContent = window.I18N.day_fill_automatically;
      statusText.classList.remove('text-dark', 'fw-bold');
      statusText.classList.add('text-muted');
      const dayIndex = zone.getAttribute('data-day-index');
      const dayInput = document.getElementById('day-recipe-input-' + dayIndex);
      if (dayInput) dayInput.value = '';
      zone.querySelectorAll('input[type="hidden"][name^="day_side_recipes_"]').forEach(input => input.remove());
    });
}

/** Excluding removes the day's main dish; its sides stay. */
function toggleExcludeDay(dayIndex) {
    const zone = document.getElementById('day-zone-' + dayIndex);
    const excludedInput = document.getElementById('day-excluded-input-' + dayIndex);
    const excludeBtn = document.getElementById('exclude-btn-' + dayIndex);
    const statusText = zone.querySelector('.slot-status');
    if (!zone || !excludedInput) return;

    const isCurrentlyExcluded = zone.classList.contains('excluded');

    if (isCurrentlyExcluded) {
      zone.classList.remove('excluded');
      excludedInput.value = '0';
      excludedDays.delete(parseInt(dayIndex));
      statusText.textContent = window.I18N.day_fill_automatically;
      statusText.classList.remove('text-dark', 'fw-bold');
      statusText.classList.add('text-muted');
      excludeBtn.classList.remove('btn-danger');
      excludeBtn.classList.add('btn-outline-secondary');
      excludeBtn.title = window.I18N.exclude_day_title;
    } else {
      const existingCard = zone.querySelector('.draggable-recipe-card');
      if (existingCard) {
        removeRecipeFromZone(existingCard.getAttribute('data-id'), dayIndex);
      }
      zone.classList.add('excluded');
      excludedInput.value = '1';
      excludedDays.add(parseInt(dayIndex));
      statusText.textContent = window.I18N.day_excluded;
      statusText.classList.remove('text-muted');
      statusText.classList.add('text-dark', 'fw-bold');
      excludeBtn.classList.remove('btn-outline-secondary');
      excludeBtn.classList.add('btn-danger');
      excludeBtn.title = window.I18N.include_day_title;
    }
}

// --- Drag and drop (main dishes only) ---

function dragStart(event) {
    event.dataTransfer.setData("text/plain", event.target.id);
    event.dataTransfer.setData("source-zone-id", event.target.closest('.day-dropzone').id);
}

function allowDrop(event) {
    const zone = event.target.closest('.day-dropzone');
    if (zone && zone.classList.contains('excluded')) {
      return; // Don't allow dropping onto excluded days
    }
    // Required, or the browser won't fire the drop event.
    event.preventDefault();
    if (zone) {
      zone.classList.add('drag-over');
    }
}

document.querySelectorAll('.day-dropzone').forEach(zone => {
    zone.addEventListener('dragleave', () => zone.classList.remove('drag-over'));
});

/** Dropping onto an occupied day swaps the two dishes. */
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
    const id = cardElement.getAttribute('data-id');
    const name = cardElement.getAttribute('data-name');
    const category = cardElement.getAttribute('data-category');

    const existingTargetCard = targetZone.querySelector('.draggable-recipe-card');
    if (existingTargetCard) {
      const targetId = existingTargetCard.getAttribute('data-id');
      const targetName = existingTargetCard.getAttribute('data-name');
      const targetCategory = existingTargetCard.getAttribute('data-category');
      assignRecipeToZone(sourceZone, targetId, targetName, targetCategory);
    } else {
      // The source day becomes empty.
      sourceZone.querySelector('.recipe-slot-container').innerHTML = '';
      const sourceStatus = sourceZone.querySelector('.slot-status');
      sourceStatus.textContent = "Fill automatically";
      sourceStatus.classList.remove('text-dark', 'fw-bold');
      sourceStatus.classList.add('text-muted');
      const sourceInput = document.getElementById('day-recipe-input-' + sourceDayIndex);
      if (sourceInput) sourceInput.value = '';
    }
    assignRecipeToZone(targetZone, id, name, category);
}
