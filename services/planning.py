"""Kern-Planungslogik: Wochen-/Datums-Helfer, Favoriten-Gewichtung, balancierte
Kategorie-Zuteilung und die zentrale Rezept-Auswahl (choose_recipe), die von
den Plan-Routen (Generieren, Reroll) genutzt wird."""

import random
from collections import Counter
from datetime import date, timedelta

from models import Recipe, PlanDay
from services.seasons import recipe_available_now

DAY_NAMES_DE = ['Montag', 'Dienstag', 'Mittwoch', 'Donnerstag', 'Freitag', 'Samstag', 'Sonntag']

# Wie viel wahrscheinlicher ein Favorit bei der automatischen/Zufalls-Auswahl
# gezogen wird, verglichen mit einem nicht favorisierten Rezept.
FAVORITE_WEIGHT = 3


def weighted_recipe_choice(recipes):
    """Wie random.choice(), gewichtet Favoriten aber mit FAVORITE_WEIGHT stärker."""
    weights = [FAVORITE_WEIGHT if r.is_favorite else 1 for r in recipes]
    return random.choices(recipes, weights=weights, k=1)[0]


# --- WOCHEN-KALENDER-HELFER ---

def monday_of(d):
    return d - timedelta(days=d.weekday())


def week_dates_for(start):
    return [start + timedelta(days=i) for i in range(7)]


def parse_iso_date(value):
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def week_neighbor_exclude_ids(day_date, field_name):
    """Rezept-IDs (main_recipe_id oder side_recipe_id) aller ANDEREN Tage in
    derselben Kalenderwoche wie day_date - für die Dubletten-Vermeidung beim
    (Neu-)Würfeln innerhalb einer Woche."""
    start = monday_of(day_date)
    dates = week_dates_for(start)
    rows = PlanDay.query.filter(PlanDay.date.in_(dates)).all()
    ids = set()
    for pd in rows:
        if pd.date == day_date:
            continue
        rid = getattr(pd, field_name)
        if rid:
            ids.add(rid)
    return ids


# --- KATEGORIE-BALANCE & REZEPT-AUSWAHL ---

def assign_balanced_categories(all_categories, days_to_fill, final_plan, preexisting_counts=None):
    """Weist jedem aufzufüllenden Tag (days_to_fill, Tag-Indizes 0-6) eine Kategorie zu:
    möglichst gleichmäßig über die Woche balanciert, aber nach Möglichkeit nie dieselbe
    Kategorie wie der direkte Vorgänger- oder Nachfolgetag (bereits fest belegte Tage
    zählen dabei als bekannter Nachbar). Ist das nicht vermeidbar (z.B. nur eine
    Kategorie insgesamt vorhanden), wird die Nachbarschaftsregel zugunsten der Balance
    aufgeweicht statt einen Tag unbefüllt zu lassen."""
    cat_ids = [c.id for c in all_categories]
    if not cat_ids:
        return {}

    counts = Counter(preexisting_counts or {})
    for cid in cat_ids:
        counts.setdefault(cid, 0)

    known_category_by_day = {
        i: final_plan[i].category_id for i in range(7) if final_plan[i] is not None
    }

    assigned = {}
    for day_index in days_to_fill:
        neighbor_cats = {
            known_category_by_day[n] for n in (day_index - 1, day_index + 1)
            if 0 <= n <= 6 and n in known_category_by_day
        }

        def sort_key(cid):
            return (cid in neighbor_cats, counts[cid])

        best_key = min(sort_key(cid) for cid in cat_ids)
        candidates = [cid for cid in cat_ids if sort_key(cid) == best_key]
        choice = random.choice(candidates)

        assigned[day_index] = choice
        counts[choice] += 1
        known_category_by_day[day_index] = choice

    return assigned


def choose_recipe(is_side_dish, exclude_ids, category_id=None, prefer_season=True):
    """Wählt ein passendes, noch nicht verwendetes Rezept aus (Favoriten dabei
    stärker gewichtet, siehe weighted_recipe_choice). Bevorzugt (falls
    prefer_season) gerade jahreszeitlich verfügbare Rezepte (siehe
    recipe_available_now), weicht aber auf alle aus, wenn dafür keine Kandidaten
    existieren - eine Saison-Zuordnung schränkt die automatische Auswahl also nie
    komplett ein."""
    base_query = Recipe.query.filter(
        Recipe.is_side_dish.is_(is_side_dish),
        ~Recipe.id.in_(exclude_ids)
    )
    if category_id is not None:
        base_query = base_query.filter(Recipe.category_id == category_id)

    candidates = base_query.all()
    if not candidates:
        return None

    if prefer_season:
        seasonal_candidates = [r for r in candidates if recipe_available_now(r)]
        if seasonal_candidates:
            return weighted_recipe_choice(seasonal_candidates)

    return weighted_recipe_choice(candidates)


def jsonify_recipe(recipe):
    # Hilfsfunktion, um Rezeptdaten lesbar für JavaScript bereitzustellen
    return {
        "id": recipe.id,
        "name": recipe.name,
        "category_name": recipe.category.name,
        "category_id": recipe.category_id,
        "servings": recipe.servings,
        "calories": recipe.calories,
        "protein": recipe.protein,
        "carbs": recipe.carbs,
        "fat": recipe.fat,
        "ingredients": [{"name": ing.name.strip().title(), "amount": ing.amount, "unit": ing.unit} for ing in recipe.ingredients]
    }
