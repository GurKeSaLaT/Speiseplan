/**
 * ingredient_category_select.js - Hilfsfunktion für das Zutaten-Formular
 * (templates/recipe_form.html, sowohl im Anlegen- als auch im
 * Bearbeiten-Modus): baut die <option>-Liste für eine Einkaufslisten-
 * Kategorie-Auswahl aus window.SHOPPING_CATEGORIES (siehe base.html).
 * static/recipe_form.js nutzt sie beim per JavaScript hinzugefügten
 * Zutatenzeilen (rformAddIngredientRow) - eigene Datei statt inline
 * dupliziert, seit Anlegen und Bearbeiten dasselbe Template teilen.
 */
function categoryOptionsHtml() {
    let html = '<option value="" selected>Sonstiges</option>';
    (window.SHOPPING_CATEGORIES || []).forEach(cat => {
        html += `<option value="${cat}">${cat}</option>`;
    });
    return html;
}
