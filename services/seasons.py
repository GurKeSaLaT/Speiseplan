"""Saison-Zuordnung für Rezepte.

Ein Rezept kann null, eine oder mehrere "Verfügbarkeitszeiträume"
(RecipeSeason-Zeilen) haben: entweder vordefinierte Standard-Saisons
(Frühling/Sommer/Herbst/Winter, siehe SEASON_PRESETS) oder einen frei
gewählten eigenen Zeitraum, oder eine Mischung aus beidem. Alle Zeiträume
sind jahresunabhängig (nur Monat+Tag, kein Jahr) und unterstützen den
Jahreswechsel (z.B. Winter: 1.12. bis 28.2., läuft über Silvester).

Dieses Modul kapselt die komplette Logik rund um diese Zeiträume:
- Verfügbarkeitsprüfung für "ist das Rezept gerade dran?" (recipe_available_now)
- Formular-Parsing beim Anlegen/Bearbeiten eines Rezepts (parse_recipe_seasons,
  save_recipe_seasons)
- Aufbereitung für die Bearbeiten-Ansicht: welche Checkboxen vorbelegen,
  welches Datum ins eigene-Zeitraum-Feld schreiben (describe_recipe_seasons),
  und wie die Zeiträume als Badges angezeigt werden (format_recipe_seasons)

Wichtig: die Saison-Zuordnung schränkt NUR die automatische Auswahl beim
Würfeln/Auffüllen ein (siehe services/planning.py: choose_recipe). Die
manuelle Auswahl eines Rezepts über die Suche auf der Erstellen-Seite ist
davon nie betroffen - ein Rezept "aus der falschen Saison" lässt sich dort
jederzeit trotzdem fest einplanen.
"""

from datetime import date

from models import db, RecipeSeason

# Die vier wählbaren Standard-Saisons, in dieser Reihenfolge auch als
# Checkboxen in recipe_form.html angezeigt.
SEASONS = ['Frühling', 'Sommer', 'Herbst', 'Winter']

# Feste (Startmonat, Starttag, Endmonat, Endtag)-Zeiträume je Standard-Saison.
# Wintern läuft über den Jahreswechsel (Start > Ende) - date_in_range()
# weiter unten behandelt diesen Fall korrekt.
SEASON_PRESETS = {
    'Frühling': (3, 1, 5, 31),
    'Sommer': (6, 1, 8, 31),
    'Herbst': (9, 1, 11, 30),
    'Winter': (12, 1, 2, 28),
}

# Umgekehrtes Nachschlage-Dict (Zeitraum-Tupel -> Saison-Name), damit sich
# aus einer gespeicherten RecipeSeason-Zeile erkennen lässt, ob sie exakt
# einer Standard-Saison entspricht oder ein frei gewählter eigener Zeitraum
# ist. Wird sowohl beim Vorbefüllen des Bearbeiten-Formulars als auch bei
# der Badge-Beschriftung gebraucht.
SEASON_PRESET_BY_RANGE = {v: k for k, v in SEASON_PRESETS.items()}


def _season_range(rs):
    """Extrahiert aus einer RecipeSeason-Zeile das reine (Startmonat,
    Starttag, Endmonat, Endtag)-Tupel, im selben Format wie SEASON_PRESETS -
    so lassen sich beide direkt per Dict-Lookup vergleichen."""
    return (rs.start_month, rs.start_day, rs.end_month, rs.end_day)


def date_in_range(month, day, start_month, start_day, end_month, end_day):
    """Prüft, ob ein gegebenes (month, day) innerhalb eines jahresunabhängigen
    Monat/Tag-Zeitraums liegt.

    Normalfall (start <= end, z.B. Sommer 1.6.-31.8.): einfacher
    Bereichsvergleich. Sonderfall (start > end, z.B. Winter 1.12.-28.2.):
    der Zeitraum läuft über den Jahreswechsel, daher gilt (month, day) als
    "im Zeitraum", wenn es entweder noch VOR Silvester nach dem Start liegt
    ODER schon NACH Neujahr aber noch vor dem Ende liegt.
    """
    current = (month, day)
    start = (start_month, start_day)
    end = (end_month, end_day)
    if start <= end:
        return start <= current <= end
    return current >= start or current <= end


def recipe_available_now(recipe):
    """Ist dieses Rezept HEUTE (nach Kalendertag, nicht Uhrzeit) für die
    automatische Auswahl verfügbar?

    Ein Rezept ohne jegliche RecipeSeason-Zeilen gilt als ganzjährig
    verfügbar (das ist der Standardfall - die meisten Rezepte haben keine
    Saison-Einschränkung). Sind Zeiträume hinterlegt, reicht es, wenn der
    heutige Tag in MINDESTENS EINEN davon fällt (ODER-Verknüpfung, nicht
    UND) - ein Rezept mit "Sommer" und "Herbst" ist z.B. von Juni bis
    November durchgehend verfügbar.
    """
    if not recipe.seasons:
        return True
    today = date.today()
    return any(date_in_range(today.month, today.day, *_season_range(rs)) for rs in recipe.seasons)


def parse_recipe_seasons(form):
    """Liest die Saison-Auswahl aus dem Rezept-Formular (Erstellen oder
    Bearbeiten) und übersetzt sie in eine Liste von
    (start_month, start_day, end_month, end_day)-Tupeln, die anschließend
    1:1 als RecipeSeason-Zeilen gespeichert werden können.

    Zwei Formularquellen werden kombiniert:
    1. `seasons` (Mehrfachauswahl-Checkboxen, ein Wert pro angehakter
       Standard-Saison) -> wird über SEASON_PRESETS in ein Zeitraum-Tupel
       übersetzt.
    2. `season_custom_start`/`season_custom_end` (zwei <input type="date">-
       Felder) -> das Jahr aus dem Datumsstring (Format "YYYY-MM-DD") wird
       verworfen, nur Monat und Tag zählen. Nur übernommen, wenn BEIDE
       Felder ausgefüllt sind; ungültige/unvollständige Eingaben werden
       stillschweigend ignoriert statt einen Fehler zu werfen, damit ein
       Tippfehler im Datumsfeld nicht das gesamte Speichern blockiert.

    Beide Quellen sind frei kombinierbar - ein Rezept kann z.B. "Sommer"
    UND einen eigenen Zeitraum gleichzeitig haben.
    """
    ranges = []
    for season_name in form.getlist('seasons'):
        preset = SEASON_PRESETS.get(season_name)
        if preset:
            ranges.append(preset)

    custom_start = form.get('season_custom_start')
    custom_end = form.get('season_custom_end')
    if custom_start and custom_end:
        try:
            # "YYYY-MM-DD".split('-')[1:] -> ["MM", "DD"], das Jahr wird
            # bewusst nicht weiterverwendet.
            start_month, start_day = (int(p) for p in custom_start.split('-')[1:])
            end_month, end_day = (int(p) for p in custom_end.split('-')[1:])
            ranges.append((start_month, start_day, end_month, end_day))
        except (ValueError, IndexError):
            pass

    return ranges


def save_recipe_seasons(recipe_id, form):
    """Ersetzt sämtliche RecipeSeason-Zeilen eines Rezepts durch die aktuell
    im Formular ausgewählten Zeiträume.

    Löscht zunächst ALLE bestehenden Zeiträume dieses Rezepts (statt sie
    einzeln abzugleichen) und legt sie aus dem Formularinhalt komplett neu
    an - einfacher als ein Diff, und beim Erstellen eines neuen Rezepts
    (noch keine bestehenden Zeilen) ist die DELETE-Anweisung ein
    No-op. Committet hier bewusst NICHT selbst; das übernimmt der
    aufrufende Route-Handler zusammen mit den übrigen Änderungen am Rezept
    in derselben Transaktion.
    """
    RecipeSeason.query.filter_by(recipe_id=recipe_id).delete()
    for start_month, start_day, end_month, end_day in parse_recipe_seasons(form):
        db.session.add(RecipeSeason(
            recipe_id=recipe_id,
            start_month=start_month, start_day=start_day,
            end_month=end_month, end_day=end_day
        ))


def describe_recipe_seasons(recipe):
    """Bereitet die Saison-Daten eines Rezepts für die Bearbeiten-Ansicht auf.

    Geht alle RecipeSeason-Zeilen des Rezepts durch und sortiert sie in zwei
    Kategorien: exakte Treffer auf eine Standard-Saison (deren Checkbox im
    Formular vorbelegt/angehakt werden soll) und alles andere (ein frei
    gewählter eigener Zeitraum). Da das Formular nur EIN Eingabefeld-Paar
    für einen eigenen Zeitraum hat, wird nur der ERSTE nicht-standardmäßige
    Zeitraum als custom_range zurückgegeben - sollte ein Rezept
    theoretisch mehrere eigene Zeiträume haben (z.B. durch direkten
    Datenbankzugriff), gehen die weiteren beim nächsten Speichern verloren.

    Rückgabe: (selected_presets, custom_range) - ein Set von Saison-Namen
    (z.B. {"Sommer", "Herbst"}) und entweder eine einzelne RecipeSeason-Zeile
    oder None.
    """
    selected_presets = set()
    custom_range = None
    for rs in recipe.seasons:
        preset_name = SEASON_PRESET_BY_RANGE.get(_season_range(rs))
        if preset_name:
            selected_presets.add(preset_name)
        elif custom_range is None:
            custom_range = rs
    return selected_presets, custom_range


def format_recipe_seasons(recipe):
    """Baut aus den Saison-Zeiträumen eines Rezepts kurze, menschenlesbare
    Labels für die Badge-Anzeige in der Rezeptliste.

    Ein Zeitraum, der exakt einer Standard-Saison entspricht, wird mit
    ihrem Namen beschriftet ("Sommer"); alle anderen (eigene) Zeiträume
    werden als "Tag.Monat.–Tag.Monat." formatiert (z.B. "15.5.–20.6.").
    Gibt eine Liste zurück (ein Label pro Zeitraum), damit die Vorlage
    für jedes Element ein eigenes Badge rendern kann.
    """
    labels = []
    for rs in recipe.seasons:
        preset_name = SEASON_PRESET_BY_RANGE.get(_season_range(rs))
        if preset_name:
            labels.append(preset_name)
        else:
            labels.append(f"{rs.start_day}.{rs.start_month}.–{rs.end_day}.{rs.end_month}.")
    return labels
