/**
 * ingredient_alias_hint.js - Live-Hinweis neben jedem Zutatennamen-Feld
 * beim Rezept anlegen/bearbeiten (recipe_create.html, recipe_edit_list.html):
 * zeigt beim Eintragen einer Zutat, ob dafür bereits eine Zutaten-
 * Gleichsetzung (siehe services/ingredient_aliases.py, Verwaltung ->
 * 🔗 Zutaten gleichsetzen) besteht, und erlaubt es, direkt eine neue
 * anzulegen, ohne die Seite zu verlassen. Genau drei Fälle:
 *
 * A) Für den eingetragenen Namen existiert bereits ein Alias
 *    (z.B. "Olivenöl" -> "Öl") - zeigt, als was er auf der Einkaufsliste
 *    zusammengefasst wird.
 * B) Der eingetragene Name ist selbst der kanonische Name, auf den
 *    ANDERE Zutaten verweisen ("Grundzutat", z.B. "Öl" selbst) - zeigt,
 *    für welche Zutaten er Grundzutat ist.
 * C) Weder A noch B: der Name ist bislang komplett unabhängig - bietet
 *    ein Mini-Formular an, um direkt einen Alias zu setzen.
 *
 * Zusätzlich (unabhängig von A/B/C, siehe renderNutritionPart unten):
 * prüft, ob für die aufgelöste kanonische Zutat bereits Nährwerte
 * hinterlegt sind (services/nutrition.py, Verwaltung -> 🍎 Nährwerte) -
 * falls nicht, bietet ein zweites Mini-Formular an, um sie direkt
 * nachzutragen, ohne die Rezept-Seite zu verlassen.
 *
 * window.INGREDIENT_ALIASES ({raw_name: canonical_name}, siehe
 * app.py: inject_ingredient_aliases()) und window.INGREDIENT_NUTRITION
 * ({canonical_name: {reference_amount, reference_unit, calories, protein,
 * carbs, fat}}, siehe app.py: inject_ingredient_nutrition()) müssen VOR
 * diesem Skript im DOM eingebettet sein. Arbeitet rein über Event-
 * Delegation auf document.body, damit sowohl serverseitig gerenderte
 * Zeilen als auch per JS dynamisch hinzugefügte Zutatenzeilen
 * (addIngredientField/addEditIngredientField) ohne separate
 * Initialisierung funktionieren - auch bei mehreren unabhängigen
 * Formularen gleichzeitig im DOM (je ein Bearbeiten-Modal pro Rezept auf
 * recipe_edit_list.html).
 */

(function () {
    const ALIASES = window.INGREDIENT_ALIASES || {};
    const NUTRITION = window.INGREDIENT_NUTRITION || {};

    // Menge aller kanonischen Zielnamen, für den schnellen "ist das
    // selbst eine Grundzutat?"-Check (Fall B). Wird bei jedem neu
    // gesetzten Alias (siehe submitAlias unten) mit aktualisiert.
    let canonicalNames = new Set(Object.values(ALIASES));

    /** Python-.title()-Äquivalent für einen clientseitigen Vorab-Check -
     * MUSS exakt dasselbe Ergebnis liefern wie Pythons str.title() (siehe
     * services/ingredient_aliases.py: normalize_name), sonst schlagen
     * ALIASES-Lookups für Namen mit Satzzeichen fehl (z.B. Pythons
     * "(ca. 20 g) Ingwer".title() == "(Ca. 20 G) Ingwer" - jeder
     * Buchstabe direkt NACH einem Nicht-Buchstaben wird groß, nicht nur
     * der erste jedes leerzeichen-getrennten "Worts"). Eine frühere,
     * einfachere Version hier trennte nur an Leerzeichen/Bindestrich und
     * traf bei Klammern/Punkten wie oben die falsche Schreibweise -
     * dadurch wurde weder der bestehende Alias gefunden noch beim
     * Zurückklappen des Namensfelds der Alias statt des Rohnamens
     * angezeigt. \p{L} (Unicode-"ist ein Buchstabe") statt eines festen
     * a-z/äöü-Musters, damit das auch für Umlaute & Akzente korrekt
     * greift wie Pythons eigene, unicode-bewusste .title(). */
    function titleCase(value) {
        let result = '';
        let prevIsLetter = false;
        for (const ch of value.trim()) {
            const isLetter = /\p{L}/u.test(ch);
            result += isLetter ? (prevIsLetter ? ch.toLowerCase() : ch.toUpperCase()) : ch;
            prevIsLetter = isLetter;
        }
        return result;
    }

    function rawNamesFor(canonical) {
        return Object.entries(ALIASES)
            .filter(([, c]) => c === canonical)
            .map(([raw]) => raw);
    }

    /** Auf welchen kanonischen Namen die Nährwert-Suche für "name" läuft:
     * bei bestehendem Alias (Fall A) dessen Ziel, sonst der Name selbst
     * (Fall B/C - server-seitig verhält sich normalize_ingredient_name()
     * für einen unaliasierten Namen genauso, siehe services/nutrition.py:
     * get_nutrition_entry). */
    function resolveNutritionCanonical(name) {
        return Object.prototype.hasOwnProperty.call(ALIASES, name) ? ALIASES[name] : name;
    }

    function renderHint(hintEl, name) {
        hintEl.innerHTML = '';
        hintEl.classList.remove('text-muted');
        if (!name) return;

        const aliasWrap = document.createElement('div');
        hintEl.appendChild(aliasWrap);
        renderAliasPart(aliasWrap, name, hintEl);

        const nutritionWrap = document.createElement('div');
        hintEl.appendChild(nutritionWrap);
        renderNutritionPart(nutritionWrap, name, hintEl);
    }

    function renderAliasPart(wrap, name, hintEl) {
        if (Object.prototype.hasOwnProperty.call(ALIASES, name)) {
            // Fall A
            wrap.classList.add('text-muted');
            wrap.innerHTML = `→ wird als „<b>${escapeHtml(ALIASES[name])}</b>" zusammengefasst`;
            return;
        }

        if (canonicalNames.has(name)) {
            // Fall B
            const examples = rawNamesFor(name).slice(0, 3).join(', ');
            wrap.classList.add('text-muted');
            wrap.innerHTML = `🧺 Grundzutat${examples ? ' (z.B. für ' + escapeHtml(examples) + ')' : ''}`;
            return;
        }

        // Fall C: weder Alias noch Grundzutat - Mini-Formular zum Setzen anbieten
        const group = document.createElement('div');
        group.className = 'input-group input-group-sm mt-1';
        group.innerHTML = `
            <input type="text" class="form-control form-control-sm alias-target-input" placeholder="Alias setzen, z.B. Nudeln" list="canonical-names-datalist">
            <button type="button" class="btn btn-outline-secondary alias-set-btn">Setzen</button>
        `;
        const input = group.querySelector('.alias-target-input');
        const button = group.querySelector('.alias-set-btn');
        button.addEventListener('click', () => submitAlias(name, input.value.trim(), hintEl));
        input.addEventListener('keydown', e => {
            if (e.key === 'Enter') { e.preventDefault(); submitAlias(name, input.value.trim(), hintEl); }
        });
        wrap.appendChild(group);
    }

    /** Zeigt, sofern für die aufgelöste kanonische Zutat noch KEIN
     * Nährwert-Eintrag existiert, ein Mini-Formular zum sofortigen
     * Nachtragen an (POST /api/ingredient-nutrition/set, siehe
     * routes/settings.py: api_set_ingredient_nutrition). Existiert
     * bereits ein Eintrag, wird nichts angezeigt. */
    function renderNutritionPart(wrap, name, hintEl) {
        const canonical = resolveNutritionCanonical(name);
        if (Object.prototype.hasOwnProperty.call(NUTRITION, canonical)) return;

        const box = document.createElement('div');
        box.className = 'mt-1 p-2 border rounded';
        box.innerHTML = `
            <div class="text-danger small fw-bold mb-2">⚠️ Keine Nährwerte für „${escapeHtml(canonical)}" hinterlegt</div>
            <div class="row g-2">
                <div class="col-6 col-sm-3">
                    <label class="form-label small text-muted mb-1">Bezug</label>
                    <select class="form-select form-select-sm nutrition-ref-unit">
                        <option value="g" selected>pro 100 g</option>
                        <option value="ml">pro 100 ml</option>
                        <option value="Stk">pro 1 Stk</option>
                    </select>
                </div>
                <div class="col-4 col-sm-3">
                    <label class="form-label small text-muted mb-1">Eiweiß (g)</label>
                    <input type="number" step="0.1" class="form-control form-control-sm nutrition-protein" placeholder="0">
                </div>
                <div class="col-4 col-sm-3">
                    <label class="form-label small text-muted mb-1">Kohlh. (g)</label>
                    <input type="number" step="0.1" class="form-control form-control-sm nutrition-carbs" placeholder="0">
                </div>
                <div class="col-4 col-sm-3">
                    <label class="form-label small text-muted mb-1">Fett (g)</label>
                    <input type="number" step="0.1" class="form-control form-control-sm nutrition-fat" placeholder="0">
                </div>
            </div>
            <button type="button" class="btn btn-sm btn-outline-danger mt-2 nutrition-set-btn">Nährwerte speichern</button>
        `;
        // Kcal wird nirgends eingegeben, nur aus Eiweiß/Kohlenhydraten/Fett
        // errechnet (services/nutrition.py: compute_calories()) - hier gibt
        // es dafür also bewusst kein Eingabefeld, auch keine Live-Anzeige
        // (die kompakte Inline-Box hat dafür keinen Platz, die berechneten
        // Kcal sind auf der Nährwertverwaltungsseite einsehbar).
        box.querySelector('.nutrition-set-btn').addEventListener('click', () => submitNutrition(canonical, box, name, hintEl));
        wrap.appendChild(box);
    }

    function submitAlias(rawName, canonicalName, hintEl) {
        if (!canonicalName) return;
        fetch('/api/ingredient-alias/set', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': window.CSRF_TOKEN },
            body: JSON.stringify({ raw_name: rawName, canonical_name: canonicalName }),
        })
        .then(response => response.json().then(data => ({ ok: response.ok, data })))
        .then(({ ok, data }) => {
            if (!ok) { alert('Hinweis: ' + (data.error || 'Alias konnte nicht gesetzt werden.')); return; }
            ALIASES[data.raw_name] = data.canonical_name;
            canonicalNames = new Set(Object.values(ALIASES));
            fillUnitFromNutrition(hintEl, data.canonical_name);
            fillCategoryFromAlias(hintEl, data.category);
            renderHint(hintEl, data.raw_name);
        })
        .catch(() => alert('Hinweis: Alias konnte nicht gesetzt werden.'));
    }

    /** Übernimmt beim Setzen eines Alias automatisch die für die
     * kanonische Zutat bereits verwendete Einkaufslisten-Kategorie (vom
     * Server anhand bestehender Zutat-Zeilen geraten, siehe
     * routes/settings.py: api_set_ingredient_alias/services/shopping.py:
     * infer_category) in das Kategorie-Feld DIESER Zutatenzeile - nur,
     * wenn dort noch die Standardauswahl "Sonstiges" (leerer Wert) steht,
     * eine bereits bewusst getroffene Auswahl wird nie überschrieben.
     * Damit landen alle auf denselben Namen gleichgesetzten Zutaten (z.B.
     * "Spaghetti"/"Fusilli" -> "Nudeln") konsistent in derselben Gruppe
     * auf der Einkaufsliste, statt je nach Rezept unterschiedlich
     * einsortiert zu sein. */
    function fillCategoryFromAlias(hintEl, category) {
        if (!category) return;
        const categorySelect = hintEl.closest('.ingredient-row')?.querySelector('[name="ing_category[]"]');
        if (categorySelect && !categorySelect.value) {
            categorySelect.value = category;
        }
    }

    /** Übernimmt beim Setzen eines Alias automatisch die für die
     * kanonische Zutat bereits hinterlegte Einheit (reference_unit aus
     * window.INGREDIENT_NUTRITION) in das Einheit-Feld DIESER Zutatenzeile
     * - nur, wenn das Feld noch leer ist (ein bereits eingetragener Wert
     * wird nie überschrieben) und nur, wenn überhaupt schon ein
     * Nährwert-Eintrag existiert. Verhindert genau das Problem, dass
     * gleichgesetzte Zutaten mit uneinheitlichen Einheiten in der
     * Einkaufsliste als mehrere Posten auftauchen (siehe
     * services/ingredient_aliases.py). */
    function fillUnitFromNutrition(hintEl, canonicalName) {
        const entry = NUTRITION[canonicalName];
        if (!entry || !entry.reference_unit) return;
        const unitInput = hintEl.closest('.ingredient-row')?.querySelector('[name="ing_unit[]"]');
        if (unitInput && !unitInput.value.trim()) {
            unitInput.value = entry.reference_unit;
        }
    }

    function submitNutrition(canonicalName, box, name, hintEl) {
        const unit = box.querySelector('.nutrition-ref-unit').value;
        const protein = parseFloat(box.querySelector('.nutrition-protein').value) || 0;
        const carbs = parseFloat(box.querySelector('.nutrition-carbs').value) || 0;
        const fat = parseFloat(box.querySelector('.nutrition-fat').value) || 0;

        fetch('/api/ingredient-nutrition/set', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': window.CSRF_TOKEN },
            body: JSON.stringify({
                name: canonicalName, reference_unit: unit,
                protein, carbs, fat,
            }),
        })
        .then(response => response.json().then(data => ({ ok: response.ok, data })))
        .then(({ ok, data }) => {
            if (!ok) { alert('Hinweis: ' + (data.error || 'Nährwerte konnten nicht gespeichert werden.')); return; }
            NUTRITION[data.canonical_name] = data;
            renderHint(hintEl, name);
        })
        .catch(() => alert('Hinweis: Nährwerte konnten nicht gespeichert werden.'));
    }

    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    function hintContainerFor(input) {
        return input.closest('.ingredient-row')?.querySelector('.ingredient-alias-hint') || null;
    }

    document.body.addEventListener('input', event => {
        if (!event.target.matches('input[name="ing_name[]"]')) return;
        const hintEl = hintContainerFor(event.target);
        if (!hintEl) return;
        renderHint(hintEl, titleCase(event.target.value));
    });

    /** Nächstgelegener gemeinsamer Rahmen einer Zutatenzeile: das
     * umschließende <form> (bei recipe_edit_list.html genau EIN
     * Bearbeiten-Modal, bei recipe_create.html das einzige Formular der
     * Seite). Grenzt die folgenden DOM-Abfragen bewusst auf dieses eine
     * Rezept ein statt document-weit zu suchen - auf recipe_edit_list.html
     * liegen leicht 50+ Bearbeiten-Modals gleichzeitig im DOM (nur per CSS
     * versteckt), ein ungebremstes document.querySelectorAll(...) bei
     * JEDEM Fokuswechsel machte sich dadurch spürbar als Ruckeln bemerkbar. */
    function formScopeOf(el) {
        return el.closest('form') || document.body;
    }

    /** Leert den Alias-/Nährwert-Hinweis JEDER Zutatenzeile DESSELBEN
     * Rezepts außer der übergebenen - der Hinweis (inkl. des ggf.
     * enthaltenen "Nährwerte nachtragen"-Kastens) soll immer nur an GENAU
     * EINER Zeile stehen, nämlich der gerade fokussierten/bearbeiteten,
     * statt an allen gleichzeitig (das wäre bei einer Zutatenliste mit
     * vielen Zeilen schnell unübersichtlich). */
    function clearOtherHints(exceptHintEl) {
        formScopeOf(exceptHintEl).querySelectorAll('.ingredient-alias-hint').forEach(el => {
            if (el !== exceptHintEl && el.innerHTML) el.innerHTML = '';
        });
    }

    /** Zeigt den Hinweis für das gerade fokussierte Namensfeld (und leert
     * alle übrigen, siehe oben) - sowohl beim echten Hineinklicken als
     * auch, wenn ein Klick auf die Alias-Anzeige (.ing-name-display,
     * siehe openIngredientNameField weiter unten) das darunterliegende
     * <input> programmatisch fokussiert. 'focusin' statt 'focus', da Letzteres
     * nicht bubbelt und sich damit nicht auf document.body delegieren
     * ließe. Bewusst KEIN Leeren beim Verlassen des Felds (blur/focusout):
     * die Hinweis-Box enthält selbst anklickbare Buttons ("Alias setzen",
     * "Nährwerte speichern") - ein Leeren beim Blur würde deren Klick
     * (blur feuert VOR click) ins Leere laufen lassen. Der Hinweis bleibt
     * daher stehen, bis eine ANDERE Zutatenzeile fokussiert wird. */
    document.body.addEventListener('focusin', event => {
        if (!event.target.matches('input[name="ing_name[]"]')) return;
        const hintEl = hintContainerFor(event.target);
        if (!hintEl) return;
        clearOtherHints(hintEl);
        renderHint(hintEl, titleCase(event.target.value));
    });

    /** Zeigt bei bereits bestehenden Zutatenzeilen (recipe_edit_list.html)
     * standardmäßig den aufgelösten Alias-Namen (server-seitig als
     * .ing-name-display-<span> vorbefüllt, siehe dort) statt des
     * tatsächlich gespeicherten Namens - erst ein Klick/Tastatur-Aktivieren
     * blendet das eigentliche, editierbare <input> ein (dessen Wert sich
     * dadurch NIE von selbst ändert).
     *
     * Komplett über Event-Delegation auf document/document.body (wie der
     * Rest dieser Datei) statt über einen einmaligen Durchlauf mit
     * direkten Listenern pro Zeile: recipe_edit_list.html hat leicht 50+
     * Bearbeiten-Modals mit je mehreren Zutatenzeilen gleichzeitig im DOM
     * (nur per CSS versteckt) - mehrere hundert direkt angehängte
     * click/keydown/blur-Listener beim Laden der Seite machten sich als
     * spürbares Ruckeln bemerkbar, Delegation kommt dagegen mit einer
     * Handvoll Listenern für die GESAMTE Seite aus.
     *
     * Zum Schließen (zurück auf die Alias-Anzeige) wird bewusst NICHT auf
     * das blur-Ereignis des <input> gesetzt: das würde voraussetzen, dass
     * ein Klick auf ein anderes Element dessen Fokus übernimmt - manche
     * Browser (v.a. Safari) verschieben den Tastaturfokus bei einem Klick
     * aber NUR auf echte Formularfelder, nicht auf ein einfaches <span>,
     * wodurch das bisherige Feld dort nie zuverlässig blurte. Stattdessen
     * ein waschechter 'click'-Listener auf dem gesamten Dokument, der
     * JEDES noch offene Feld schließt, dessen Zutatenzeile (.ingredient-
     * row - bewusst die GANZE Zeile inkl. Alias-/Nährwert-Hinweis, nicht
     * nur die Namens-Spalte, damit ein Klick auf "Alias setzen"/"Nährwerte
     * speichern" für dieselbe Zeile es nicht versehentlich mit-schließt)
     * den Klick NICHT enthält - unabhängig davon, ob der Browser dabei
     * überhaupt einen Fokuswechsel für nötig hält. Per Tastatur (Tab)
     * ergänzt der focusin-Listener ganz unten dasselbe zusätzlich
     * zuverlässig, da Tab in jedem Browser echte Fokus-Ereignisse auslöst. */
    function ingNameInputFor(display) {
        const input = display.nextElementSibling;
        return (input && input.matches('.ing-name-input')) ? input : null;
    }
    function ingNameDisplayFor(input) {
        const display = input.previousElementSibling;
        return (display && display.matches('.ing-name-display')) ? display : null;
    }

    function revertIngredientNameField(input) {
        const display = ingNameDisplayFor(input);
        if (!display) return;
        display.textContent = ALIASES[titleCase(input.value)] || input.value;
        display.classList.remove('d-none');
        input.classList.add('d-none');
    }

    function revertAllOpenIngredientNames(exceptInput, scopeEl) {
        formScopeOf(scopeEl || exceptInput || document.body).querySelectorAll('.ing-name-input:not(.d-none)').forEach(openInput => {
            if (openInput !== exceptInput) revertIngredientNameField(openInput);
        });
    }

    function openIngredientNameField(display) {
        const input = ingNameInputFor(display);
        if (!input) return;
        revertAllOpenIngredientNames(input, input);
        display.classList.add('d-none');
        input.classList.remove('d-none');
        input.focus();
        input.select();
    }

    document.body.addEventListener('click', event => {
        const display = event.target.closest('.ing-name-display');
        if (display) openIngredientNameField(display);
    });
    document.body.addEventListener('keydown', event => {
        if (!event.target.matches('.ing-name-display')) return;
        if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); openIngredientNameField(event.target); }
    });
    document.addEventListener('click', event => {
        // formScopeOf() statt document.querySelectorAll(...): dieser
        // Listener feuert bei JEDEM Klick irgendwo auf der Seite (nicht
        // nur auf Zutatenfeldern) - ungebremst über alle 50+ gleichzeitig
        // im DOM liegenden Bearbeiten-Modals hinweg gesucht, wäre das
        // spürbar langsam gewesen (siehe Kommentar bei formScopeOf).
        formScopeOf(event.target).querySelectorAll('.ing-name-input:not(.d-none)').forEach(openInput => {
            const row = openInput.closest('.ingredient-row');
            if (row && !row.contains(event.target)) revertIngredientNameField(openInput);
        });
    });
    document.body.addEventListener('focusin', event => {
        revertAllOpenIngredientNames(event.target.matches('.ing-name-input') ? event.target : null, event.target);
    });
})();
