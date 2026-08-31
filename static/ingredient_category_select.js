/**
 * ingredient_category_select.js - helper function for the ingredient form
 * (templates/recipe_form.html, both in create and edit mode): builds the
 * <option> list for a shopping list category selector from
 * window.SHOPPING_CATEGORIES (see base.html).
 * static/recipe_form.js uses it for ingredient rows added via JavaScript
 * (rformAddIngredientRow) - a separate file instead of duplicating it
 * inline, ever since create and edit share the same template.
 */
function categoryOptionsHtml() {
    let html = '<option value="" selected>Other</option>';
    (window.SHOPPING_CATEGORIES || []).forEach(cat => {
        html += `<option value="${cat}">${cat}</option>`;
    });
    return html;
}
