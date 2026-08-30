"""Zutaten-Gleichsetzung für die Einkaufsliste: ordnet konkrete
Zutatennamen (z.B. "Spaghetti", "Fusilli") einem gemeinsamen, übergeordneten
Namen zu (z.B. "Nudeln"), damit die Einkaufsliste sie als EINEN Posten
zusammenfasst statt als mehrere. Siehe models.py: IngredientAlias für die
Speicherung und routes/settings.py für die Verwaltungs-Seite, auf der
Nutzer diese Zuordnung selbst pflegen.

Betrifft ausschließlich die Einkaufsliste (services/planning.py:
jsonify_recipe) - die Zutatenliste eines einzelnen Rezepts (Anlegen/
Bearbeiten-Formular) zeigt weiterhin den ursprünglich eingetragenen Namen,
unverändert von jeder hier gepflegten Zuordnung.

Jeder Plan pflegt seine EIGENE Gleichsetzung (siehe models.py:
IngredientAlias.plan_id) - dieselbe Zutat kann in zwei Plänen
unterschiedlich (oder gar nicht) gruppiert sein. Für ein Rezept, das per
RecipePlanLink in mehreren Plänen sichtbar ist, gilt beim Betrachten
IMMER die Gleichsetzung des GERADE AKTIVEN Plans, nicht die seines
Eigentümer-Plans.
"""

from models import Ingredient, IngredientAlias, db
from services.recipe_visibility import visible_recipe_ids_subquery


def normalize_name(raw_name):
    """Dieselbe Normalisierung wie jsonify_recipe() für Zutatennamen
    (.strip().title()) - Groß-/Kleinschreibung und Leerraum sollen beim
    Nachschlagen/Anlegen eines Alias keine Rolle spielen. Öffentlich (kein
    führender Unterstrich mehr), da routes/settings.py sie auch für die
    AJAX-Antwort von api_set_ingredient_alias() braucht."""
    return (raw_name or '').strip().title()


def normalize_ingredient_name(plan_id, raw_name):
    """Liefert den für die Einkaufsliste zu verwendenden Namen: den (im
    Kontext von plan_id) gepflegten kanonischen Namen, falls raw_name
    (nach Normalisierung) einen Alias-Eintrag hat, sonst raw_name selbst
    (normalisiert) - ein unbekannter Zutatenname bleibt also einfach er
    selbst, keine Gruppierung ist der Standardfall."""
    key = normalize_name(raw_name)
    alias = IngredientAlias.query.filter_by(plan_id=plan_id, raw_name=key).first()
    return alias.canonical_name if alias else key


def list_known_ingredient_names(plan_id):
    """Alle aktuell in einem für plan_id SICHTBAREN Rezept verwendeten
    Zutatennamen (normalisiert, dedupliziert, alphabetisch) - Grundlage
    für die Verwaltungs-Seite, die JEDEN bekannten Namen als Zeile zeigt,
    auch ohne bestehenden Alias (siehe routes/settings.py:
    ingredient_aliases_view). "Sichtbar" schließt sowohl eigene als auch
    per RecipePlanLink eingebundene Rezepte ein (siehe
    services/recipe_visibility.py)."""
    names = (
        db.session.query(Ingredient.name)
        .filter(Ingredient.recipe_id.in_(visible_recipe_ids_subquery(plan_id)))
        .distinct().all()
    )
    return sorted({normalize_name(n[0]) for n in names if n[0] and n[0].strip()})


def get_all_aliases(plan_id):
    """Alle für plan_id gepflegten Alias-Zuordnungen als Dict {raw_name:
    canonical_name}."""
    return {a.raw_name: a.canonical_name for a in IngredientAlias.query.filter_by(plan_id=plan_id).all()}


def set_alias(plan_id, raw_name, canonical_name):
    """Legt eine Zuordnung für plan_id an oder aktualisiert sie. Ist
    canonical_name (nach Normalisierung) identisch mit raw_name, wird ein
    eventuell bestehender Alias stattdessen GELÖSCHT - "sich selbst
    zugeordnet" ist gleichbedeutend mit "kein Alias", das spart unnötige
    Zeilen."""
    key = normalize_name(raw_name)
    canonical = normalize_name(canonical_name)
    if not key:
        return
    if canonical == key:
        delete_alias(plan_id, key)
        return

    alias = IngredientAlias.query.filter_by(plan_id=plan_id, raw_name=key).first()
    if alias:
        alias.canonical_name = canonical
    else:
        db.session.add(IngredientAlias(plan_id=plan_id, raw_name=key, canonical_name=canonical))
    db.session.commit()


def delete_alias(plan_id, raw_name):
    """Entfernt eine Zuordnung wieder (der Zutatenname gruppiert sich
    danach nur noch mit sich selbst) - kein Fehler, falls keine existiert."""
    key = normalize_name(raw_name)
    IngredientAlias.query.filter_by(plan_id=plan_id, raw_name=key).delete()
    db.session.commit()
