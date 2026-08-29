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
 * window.INGREDIENT_ALIASES ({raw_name: canonical_name}, siehe
 * app.py: inject_ingredient_aliases()) muss VOR diesem Skript im DOM
 * eingebettet sein. Arbeitet rein über Event-Delegation auf document.body,
 * damit sowohl serverseitig gerenderte Zeilen als auch per JS dynamisch
 * hinzugefügte Zutatenzeilen (addIngredientField/addEditIngredientField)
 * ohne separate Initialisierung funktionieren - auch bei mehreren
 * unabhängigen Formularen gleichzeitig im DOM (je ein Bearbeiten-Modal
 * pro Rezept auf recipe_edit_list.html).
 */

(function () {
    const ALIASES = window.INGREDIENT_ALIASES || {};

    // Menge aller kanonischen Zielnamen, für den schnellen "ist das
    // selbst eine Grundzutat?"-Check (Fall B). Wird bei jedem neu
    // gesetzten Alias (siehe setAlias unten) mit aktualisiert.
    let canonicalNames = new Set(Object.values(ALIASES));

    /** Python-.title()-Äquivalent (grob) für einen clientseitigen
     * Vorab-Check - muss nicht perfekt sein, da set_alias() serverseitig
     * ohnehin die maßgebliche Normalisierung übernimmt (siehe
     * services/ingredient_aliases.py: normalize_name). */
    function titleCase(value) {
        return value.trim().replace(/[^\s-]+/g, word =>
            word.charAt(0).toUpperCase() + word.slice(1).toLowerCase()
        );
    }

    function rawNamesFor(canonical) {
        return Object.entries(ALIASES)
            .filter(([, c]) => c === canonical)
            .map(([raw]) => raw);
    }

    function renderHint(hintEl, name) {
        hintEl.innerHTML = '';
        hintEl.classList.remove('text-muted');
        if (!name) return;

        if (Object.prototype.hasOwnProperty.call(ALIASES, name)) {
            // Fall A
            hintEl.classList.add('text-muted');
            hintEl.innerHTML = `→ wird als „<b>${escapeHtml(ALIASES[name])}</b>" zusammengefasst`;
            return;
        }

        if (canonicalNames.has(name)) {
            // Fall B
            const examples = rawNamesFor(name).slice(0, 3).join(', ');
            hintEl.classList.add('text-muted');
            hintEl.innerHTML = `🧺 Grundzutat${examples ? ' (z.B. für ' + escapeHtml(examples) + ')' : ''}`;
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
        hintEl.appendChild(group);
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
            renderHint(hintEl, data.raw_name);
        })
        .catch(() => alert('Hinweis: Alias konnte nicht gesetzt werden.'));
    }

    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    function hintContainerFor(input) {
        return input.closest('.col-4, .col-12')?.querySelector('.ingredient-alias-hint') || null;
    }

    document.body.addEventListener('input', event => {
        if (!event.target.matches('input[name="ing_name[]"]')) return;
        const hintEl = hintContainerFor(event.target);
        if (!hintEl) return;
        renderHint(hintEl, titleCase(event.target.value));
    });
})();
