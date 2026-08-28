/**
 * ingredient_category_select.js - Gemeinsam von recipe_create.html und
 * recipe_edit_list.html genutzte Hilfsfunktion für die Zutaten-Formulare:
 * baut die <option>-Liste für eine Einkaufslisten-Kategorie-Auswahl aus
 * window.SHOPPING_CATEGORIES (siehe base.html). Beide Seiten fügen damit
 * per JavaScript weitere Zutatenzeilen hinzu (addIngredientField bzw.
 * addEditIngredientField) und brauchen dafür identisches Options-Markup -
 * vorher an zwei Stellen dupliziert, jetzt an einer gepflegt.
 */
function categoryOptionsHtml() {
    let html = '<option value="" selected>Sonstiges</option>';
    (window.SHOPPING_CATEGORIES || []).forEach(cat => {
        html += `<option value="${cat}">${cat}</option>`;
    });
    return html;
}
