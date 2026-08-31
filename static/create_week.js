/**
 * Create page (templates/create_week.html): live search across all
 * recipes, assignment by click or drag-and-drop onto one of the 7
 * weekdays, plus the exclusion toggle ("Exclude this day from
 * planning").
 *
 * Deliberately written COMPLETELY without any dependency on server data -
 * unlike static/plan.js there is no window.PLAN_DATA here. All the
 * information needed (recipe ID, name, category, whether it's a side
 * dish) is already present as data-* attributes on the search result
 * buttons rendered by the server (see create_week.html: .search-item), so
 * this script is pure DOM handling and doesn't know any recipe data
 * itself.
 *
 * Everything here is purely CLIENT-SIDE intermediate state: nothing is
 * saved until the #planForm form is submitted (POST to
 * /plan/<start_date>/generate, see routes/plan/pages.py: week_generate). The
 * assignment of a main dish to a day is stored in a hidden
 * <input type="hidden"> field per day (day-recipe-input-<i>), and the
 * form itself is only MIRRORED by the visible "cards" - moving/deleting a
 * card therefore always also means updating the corresponding form
 * field. Side dishes work structurally differently: a day can have any
 * number of them, so there is NO single fixed field per day, but rather
 * a separate hidden field PER assigned side dish (name="day_side_recipes_<i>[]",
 * see assignSideToZone) - Flask reads these on submit via
 * request.form.getlist() as a list (see week_generate).
 */

const searchInput = document.getElementById('searchInput');
const searchResults = document.getElementById('searchResults');
const searchItems = document.querySelectorAll('.search-item');

// Prevents one and the same recipe from being permanently assigned to two
// different days at the same time: already-assigned IDs are hidden from
// the live search (see search filter below). Main dish and side dish
// assignments keep separate sets, since both pools are independent of
// each other (a recipe is either a main dish OR a side dish, never both
// at once - see models.py: Recipe.is_side_dish). For side dishes, the set
// additionally prevents a duplicate across the WHOLE WEEK (the same
// recipe not appearing twice on different days) - several DIFFERENT side
// dishes on the same day, however, are explicitly allowed, see
// assignSideToZone.
let assignedRecipeIds = new Set();
let assignedSideRecipeIds = new Set();

// Which days (index 0-6) are currently marked as "excluded from
// planning". Currently only ever written to (toggleExcludeDay), never
// read anywhere else - the state that actually matters for the form
// submit lives in the "excluded" CSS class / hidden input per day, not in
// this set.
let excludedDays = new Set();

// 1. Live search: filters the results list on every keystroke. A search
// hit counts on a match in the recipe name OR the category name (e.g.
// "pasta" finds both "Spaghetti" (category Pasta) as well as a recipe
// that has "pasta" in its own name).
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

        // Recipes already planned are hidden entirely from the result
        // list (not just greyed out) - clicking a second time would be
        // pointless anyway, since each recipe can be permanently assigned
        // at most once per week.
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

// Closes the results dropdown as soon as a click happens anywhere outside
// the search field or the results list (typical "click elsewhere closes
// the dropdown" behavior).
document.addEventListener('click', function(e) {
    if (!searchInput.contains(e.target) && !searchResults.contains(e.target)) {
      searchResults.style.display = 'none';
    }
});

// 2. Clicking a search result assigns it automatically instead of having
// to be placed via drag-and-drop. Main dishes look for a day WITHOUT a
// main dish (at most one per day possible). Side dishes, on the other
// hand, can have any number per day - "the next free day" doesn't make
// sense for them; instead the day with the FEWEST side dishes so far
// ALWAYS gets the new one added (in case of a tie: the first in weekday
// order), so that repeatedly-clicked side dishes distribute themselves
// evenly across the week on their own, instead of all landing on one
// day. Fine-tuning which side dish ends up on which specific day is then
// always possible afterwards on the finished plan page via drag-and-drop
// (see static/plan.js: moveSideDish).
searchItems.forEach(item => {
    item.addEventListener('click', function() {
      const recipeId = this.getAttribute('data-id');
      const recipeName = this.getAttribute('data-name');
      const categoryName = this.getAttribute('data-category');
      const isSide = this.getAttribute('data-is-side') === 'true';

      if (isSide) {
        // Side dishes are also allowed on an already-excluded day - a
        // side dish doesn't block the day and is completely independent
        // of the main dish exclusion status (see models.py: PlanDay).
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
        // Main dishes, on the other hand, need a day that is NEITHER
        // excluded NOR already occupied.
        const freeZone = Array.from(document.querySelectorAll('.day-dropzone')).find(zone =>
          !zone.classList.contains('excluded') && zone.querySelector('.draggable-recipe-card') === null
        );
        if (!freeZone) {
          alert("No free day left!");
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

// 3. Assigns a main dish to a specific day dropzone: updates the status
// text, sets the hidden form field, and builds the visible, draggable
// "card". Called both by the click-on-search-result handler (above) and
// by the drag-and-drop logic (drop(), further below) - hence a
// standalone, reusable function instead of inline in the click handler.
function assignRecipeToZone(zoneElement, id, name, category) {
    const slotContainer = zoneElement.querySelector('.recipe-slot-container');
    const statusText = zoneElement.querySelector('.slot-status');
    const dayIndex = zoneElement.getAttribute('data-day-index');
    assignedRecipeIds.add(id);
    statusText.textContent = "Planned";
    statusText.classList.remove('text-muted');
    statusText.classList.add('text-dark', 'fw-bold');

    // The field that actually matters for the form submit - independent
    // of the visible card, which is purely for display/dragging.
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
        <span class="name">${name}</span>
        <button type="button" class="x" onclick="removeRecipeFromZone('${id}', '${dayIndex}')" aria-label="Remove">✕</button>
    `;
    slotContainer.innerHTML = '';
    slotContainer.appendChild(card);
}

// 4. Removes a main dish from a day again (card gone, status back to
// "Fill automatically", hidden field cleared) - undoes assignRecipeToZone()
// for this exact day.
function removeRecipeFromZone(id, dayIndex) {
    assignedRecipeIds.delete(id);
    const zone = document.getElementById('day-zone-' + dayIndex);
    if (zone) {
      zone.querySelector('.recipe-slot-container').innerHTML = '';
      const statusText = zone.querySelector('.slot-status');
      statusText.textContent = "Fill automatically";
      statusText.classList.remove('text-dark', 'fw-bold');
      statusText.classList.add('text-muted');
    }
    const dayInput = document.getElementById('day-recipe-input-' + dayIndex);
    if (dayInput) dayInput.value = '';
}

// 4b. Counterpart to assignRecipeToZone() for side dishes - but ADDITIVE
// instead of replacing: a day can have any number of side-dish cards at
// once in .side-slot-container. Each card gets its OWN hidden form field
// (instead of a single shared field per day as with the main dish) - id
// "side-input-<recipe-ID>", name "day_side_recipes_<day-index>[]", so
// that Flask receives all of that day's side dish IDs as a list on
// submit via request.form.getlist() (see week_generate() in
// routes/plan/pages.py). No status text (that only belongs to the main
// dish slot) and no drag-and-drop (side-dish cards are deliberately not
// draggable on THIS page - moving individual side dishes between days is
// only possible on the finished plan page, see static/plan.js:
// moveSideDish).
function assignSideToZone(zoneElement, id, name, category) {
    const sideContainer = zoneElement.querySelector('.side-slot-container');
    const dayIndex = zoneElement.getAttribute('data-day-index');
    assignedSideRecipeIds.add(id);

    // "No side dish" placeholder disappears as soon as the first side
    // dish for this day is added.
    const placeholder = sideContainer.querySelector('.no-side-placeholder');
    if (placeholder) placeholder.remove();

    const chip = document.createElement('div');
    chip.className = 'side-dish-chip';
    chip.setAttribute('id', 'side-card-' + id);
    chip.setAttribute('data-id', id);
    chip.innerHTML = `
        <span class="text-truncate">🥗 ${name}</span>
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

// 4c. Removes a SINGLE side dish again (card + its own hidden field) -
// undoes assignSideToZone() for exactly this one side dish, without
// touching the other side dishes on the same day. Shows the "No side
// dish" placeholder again as soon as no side dish is left for this day.
function removeSideFromZone(id, dayIndex) {
    assignedSideRecipeIds.delete(id);
    const chip = document.getElementById('side-card-' + id);
    if (chip) chip.remove();
    const sideInput = document.getElementById('side-input-' + id);
    if (sideInput) sideInput.remove();

    const zone = document.getElementById('day-zone-' + dayIndex);
    const sideContainer = zone && zone.querySelector('.side-slot-container');
    if (sideContainer && sideContainer.children.length === 0) {
        sideContainer.innerHTML = '<span class="no-side no-side-placeholder">No side dish</span>';
    }
}

// Resets ALL 7 days at once (the "Clear all" button) - instead of calling
// removeRecipeFromZone()/removeSideFromZone() for each day, it resets the
// status and fields directly itself, since every zone is set up
// completely fresh here regardless of its current content anyway
// (whether a card was there at all doesn't matter). For side dishes this
// means: all dynamically created hidden fields (name starting with
// "day_side_recipes_") are removed per zone, since (unlike the main
// dish) there is no single fixed field that could simply be cleared.
function clearAllDays() {
    assignedRecipeIds.clear();
    assignedSideRecipeIds.clear();
    document.querySelectorAll('.day-dropzone').forEach(zone => {
      zone.querySelector('.recipe-slot-container').innerHTML = '';
      zone.querySelector('.side-slot-container').innerHTML = '<span class="no-side no-side-placeholder">No side dish</span>';
      const statusText = zone.querySelector('.slot-status');
      statusText.textContent = "Fill automatically";
      statusText.classList.remove('text-dark', 'fw-bold');
      statusText.classList.add('text-muted');
      const dayIndex = zone.getAttribute('data-day-index');
      const dayInput = document.getElementById('day-recipe-input-' + dayIndex);
      if (dayInput) dayInput.value = '';
      zone.querySelectorAll('input[type="hidden"][name^="day_side_recipes_"]').forEach(input => input.remove());
    });
}

// 5. Toggles a day between "will be filled automatically" and "excluded
// from main dish planning" (🚫 button). Excluding a day automatically
// removes any main dish already assigned to it (an excluded day should
// not get one) - a side dish already assigned, however, stays untouched,
// since "excluded" by definition applies ONLY to the main dish.
function toggleExcludeDay(dayIndex) {
    const zone = document.getElementById('day-zone-' + dayIndex);
    const excludedInput = document.getElementById('day-excluded-input-' + dayIndex);
    const excludeBtn = document.getElementById('exclude-btn-' + dayIndex);
    const statusText = zone.querySelector('.slot-status');
    if (!zone || !excludedInput) return;

    const isCurrentlyExcluded = zone.classList.contains('excluded');

    if (isCurrentlyExcluded) {
      // Include the day in automatic planning again.
      zone.classList.remove('excluded');
      excludedInput.value = '0';
      excludedDays.delete(parseInt(dayIndex));
      statusText.textContent = "Fill automatically";
      statusText.classList.remove('text-dark', 'fw-bold');
      statusText.classList.add('text-muted');
      excludeBtn.classList.remove('btn-danger');
      excludeBtn.classList.add('btn-outline-secondary');
      excludeBtn.title = "Exclude this day from planning";
    } else {
      const existingCard = zone.querySelector('.draggable-recipe-card');
      if (existingCard) {
        removeRecipeFromZone(existingCard.getAttribute('data-id'), dayIndex);
      }
      zone.classList.add('excluded');
      excludedInput.value = '1';
      excludedDays.add(parseInt(dayIndex));
      statusText.textContent = "Excluded";
      statusText.classList.remove('text-muted');
      statusText.classList.add('text-dark', 'fw-bold');
      excludeBtn.classList.remove('btn-outline-secondary');
      excludeBtn.classList.add('btn-danger');
      excludeBtn.title = "Include this day in planning again";
    }
}

// --- NATIVE DRAG AND DROP IMPLEMENTATION ---
// Uses the built-in HTML5 drag-and-drop API (draggable="true" +
// dragstart/dragover/drop events, see the corresponding on* attributes in
// create_week.html) instead of an external library - for the simple use
// case "drag a card from one day box into another" this is entirely
// sufficient.

function dragStart(event) {
    // dataTransfer is the only way to carry information from the source
    // to the target element of a drag: the ID of the dragged card AND the
    // ID of its CURRENT (origin) zone are stored here, so that drop()
    // further below can read both back out again.
    event.dataTransfer.setData("text/plain", event.target.id);
    event.dataTransfer.setData("source-zone-id", event.target.closest('.day-dropzone').id);
}

function allowDrop(event) {
    const zone = event.target.closest('.day-dropzone');
    if (zone && zone.classList.contains('excluded')) {
      return; // Don't allow dropping onto excluded days
    }
    // event.preventDefault() is strictly necessary for the browser to
    // allow the "drop" event at all - without it, a zone counts as "not a
    // valid target" by default under the HTML5 drag-and-drop API.
    event.preventDefault();
    if (zone) {
      zone.classList.add('drag-over');
    }
}

// Removes the visual highlight (drag-over border) as soon as the dragged
// card leaves a zone again without being dropped there.
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
    // No valid card found, or dropped onto itself (source == target) ->
    // nothing to do.
    if (!cardElement || sourceZoneId === targetZone.id) return;
    const sourceZone = document.getElementById(sourceZoneId);
    const sourceDayIndex = sourceZone.getAttribute('data-day-index');
    const id = cardElement.getAttribute('data-id');
    const name = cardElement.getAttribute('data-name');
    const category = cardElement.getAttribute('data-category');

    const existingTargetCard = targetZone.querySelector('.draggable-recipe-card');
    if (existingTargetCard) {
      // SWAP LOGIC: if the target zone is already occupied, both dishes
      // are simply swapped with each other, instead of the drop being
      // rejected outright - feels more intuitive to the user ("swap two
      // days" instead of "have to empty one day first").
      const targetId = existingTargetCard.getAttribute('data-id');
      const targetName = existingTargetCard.getAttribute('data-name');
      const targetCategory = existingTargetCard.getAttribute('data-category');
      assignRecipeToZone(sourceZone, targetId, targetName, targetCategory);
    } else {
      // Target zone was empty: the origin zone now becomes free, so it
      // must be reset to its empty state itself (status text, form
      // field) - assignRecipeToZone() for the NEW zone further below
      // does not take care of this automatically.
      sourceZone.querySelector('.recipe-slot-container').innerHTML = '';
      const sourceStatus = sourceZone.querySelector('.slot-status');
      sourceStatus.textContent = "Fill automatically";
      sourceStatus.classList.remove('text-dark', 'fw-bold');
      sourceStatus.classList.add('text-muted');
      const sourceInput = document.getElementById('day-recipe-input-' + sourceDayIndex);
      if (sourceInput) sourceInput.value = '';
    }
    // In both cases (swap or simple move), the dragged dish ends up
    // permanently in the target zone.
    assignRecipeToZone(targetZone, id, name, category);
}
