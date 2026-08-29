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
"""

from models import Ingredient, IngredientAlias, db


def _normalize_key(raw_name):
    """Dieselbe Normalisierung wie jsonify_recipe() für Zutatennamen
    (.strip().title()) - Groß-/Kleinschreibung und Leerraum sollen beim
    Nachschlagen/Anlegen eines Alias keine Rolle spielen."""
    return (raw_name or '').strip().title()


def normalize_ingredient_name(raw_name):
    """Liefert den für die Einkaufsliste zu verwendenden Namen: den
    gepflegten kanonischen Namen, falls raw_name (nach Normalisierung)
    einen Alias-Eintrag hat, sonst raw_name selbst (normalisiert) - ein
    unbekannter Zutatenname bleibt also einfach er selbst, keine
    Gruppierung ist der Standardfall."""
    key = _normalize_key(raw_name)
    alias = IngredientAlias.query.filter_by(raw_name=key).first()
    return alias.canonical_name if alias else key


def list_known_ingredient_names():
    """Alle aktuell in irgendeinem Rezept verwendeten Zutatennamen
    (normalisiert, dedupliziert, alphabetisch) - Grundlage für die
    Verwaltungs-Seite, die JEDEN bekannten Namen als Zeile zeigt, auch
    ohne bestehenden Alias (siehe routes/settings.py: ingredient_aliases_view)."""
    names = db.session.query(Ingredient.name).distinct().all()
    return sorted({_normalize_key(n[0]) for n in names if n[0] and n[0].strip()})


def get_all_aliases():
    """Alle gepflegten Alias-Zuordnungen als Dict {raw_name: canonical_name}."""
    return {a.raw_name: a.canonical_name for a in IngredientAlias.query.all()}


def set_alias(raw_name, canonical_name):
    """Legt eine Zuordnung an oder aktualisiert sie. Ist canonical_name
    (nach Normalisierung) identisch mit raw_name, wird ein eventuell
    bestehender Alias stattdessen GELÖSCHT - "sich selbst zugeordnet" ist
    gleichbedeutend mit "kein Alias", das spart unnötige Zeilen."""
    key = _normalize_key(raw_name)
    canonical = _normalize_key(canonical_name)
    if not key:
        return
    if canonical == key:
        delete_alias(key)
        return

    alias = IngredientAlias.query.filter_by(raw_name=key).first()
    if alias:
        alias.canonical_name = canonical
    else:
        db.session.add(IngredientAlias(raw_name=key, canonical_name=canonical))
    db.session.commit()


def delete_alias(raw_name):
    """Entfernt eine Zuordnung wieder (der Zutatenname gruppiert sich
    danach nur noch mit sich selbst) - kein Fehler, falls keine existiert."""
    key = _normalize_key(raw_name)
    IngredientAlias.query.filter_by(raw_name=key).delete()
    db.session.commit()
