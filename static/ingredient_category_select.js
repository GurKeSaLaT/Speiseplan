/** Shopping-category <option>s for ingredient rows added by recipe_form.js. */
function categoryOptionsHtml() {
    let html = `<option value="" selected>${window.I18N.category_other_label}</option>`;
    (window.SHOPPING_CATEGORIES || []).forEach(cat => {
        html += `<option value="${cat}">${cat}</option>`;
    });
    return html;
}
