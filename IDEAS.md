# Ideen für Erweiterungen

Backlog für zukünftige Features - noch nicht umgesetzt, nur gesammelt.

## Umgesetzt

- **Tage im fertigen Plan tauschen.** Tageskarten auf `plan.html` sind jetzt
  per Drag-and-Drop komplett tauschbar (Hauptgericht, Beilage und
  Ausnahme-Status), rein clientseitig.
- **Beilage auch an Tagen ohne Hauptgericht.** Die Beilagen-Zuweisung ist von
  der Hauptgericht-Exklusion entkoppelt; "ausgenommen" blockiert nur noch das
  Hauptgericht.
- **Keine gleiche Kategorie an zwei aufeinanderfolgenden Tagen.**
  `assign_balanced_categories()` in `app.py` meidet beim automatischen
  Auffüllen und beim Reroll die Kategorie des direkten Vorgänger-/
  Nachfolgetags, weicht das aber auf statt einen Tag leer zu lassen.
- **Saison-Zuordnung für Rezepte.** Rezepte können mehrere Standard-Saisons
  (Frühling/Sommer/Herbst/Winter) und/oder einen eigenen Zeitraum bekommen,
  leer = ganzjährig. Die automatische Auswahl (`choose_recipe()`) bevorzugt
  gerade verfügbare Rezepte, weicht aber auf alle aus, wenn nötig - manuelle
  Auswahl ist nie eingeschränkt.
- **Portionsanzahl & Mengenskalierung.** Neues `Recipe.servings`-Feld: für
  wie viele Personen die eingetragenen Zutatenmengen ausgelegt sind. Auf der
  Plan-Seite hat jeder Wochentag ein eigenes Personen-Feld (Default 2), das
  die Zutatenmengen dieses Tages in der Einkaufsliste hoch-/runterrechnet.
  Nährwerte bleiben unskaliert (die sind pro Portion/Person). Die
  Personenzahl ist an den Wochentag gebunden, nicht ans Gericht - wandert
  beim Tage-Tausch also nicht mit.
- **Favoriten.** Neues `Recipe.is_favorite`-Feld. Favoriten werden bei der
  automatischen Auswahl/beim Würfeln (`weighted_recipe_choice()`) mit
  `FAVORITE_WEIGHT`-facher Wahrscheinlichkeit gezogen (aktuell 3x), statt
  gleichverteilt zu würfeln - kein Rating, nur ein Ja/Nein-Bonus.
- **Wochen-Nährwertübersicht.** Auf der Plan-Seite zeigt eine Karte die
  Wochensumme und den Ø-Wert pro geplantem Tag für Kalorien/Eiweiß/
  Kohlenhydrate/Fett (über alle Haupt- und Zusatzgerichte), live
  aktualisiert bei jeder Änderung am Plan.
- **Dauerhafter Plan-Kalender.** Neues `PlanDay`-Modell: ein Datensatz pro
  echtem Kalendertag (Hauptgericht, Beilage, Ausnahme-Status, Personenzahl),
  keine flüchtige Anzeige mehr. Die Plan-Seite (`/plan/<Montag-Datum>`) ist
  jetzt die Hauptseite, mit Wochen-Navigation (vor/zurück, Datumssprung) im
  Kopf. Wochen ohne Plan zeigen einen "Neuen Wochenplan erstellen"-Button,
  der zur bisherigen Tageszuweisungs-Seite führt (jetzt `/plan/<Datum>/create`,
  nur noch darüber erreichbar). Alle Live-Aktionen (würfeln, tauschen,
  Beilage entfernen, Personenzahl ändern) schreiben direkt in die Datenbank.
  Legt die Grundlage für spätere Auswertungen (z.B. wie oft welche Kategorie/
  welches Rezept vorkam), aber noch **ohne** wochenübergreifende
  Wiederholungssperre oder Rückblicks-/Auswertungsansicht - beides wäre mit
  den vorhandenen Daten jetzt leicht nachrüstbar.
- **Zutaten-Kategorien für die Einkaufsliste.** Neues `Ingredient.category`-
  Feld (fester Wertebereich aus `services/shopping.py: SHOPPING_CATEGORIES`,
  in Einkaufsreihenfolge: Obst/Gemüse, Milchprodukte, Hygieneartikel,
  Getränke, Teigwaren, Konserven, Tiefkühlware, Rest = Sonstiges). Wird beim
  Zutat-Eintragen per Dropdown gewählt und gruppiert/sortiert die
  Einkaufsliste entsprechend statt rein alphabetisch. Bestehende Zutaten
  landen bis zur nächsten Bearbeitung in Sonstiges.
- **Manuell Artikel zur Einkaufsliste hinzufügen.** Neues Modell
  `ExtraShoppingItem` (an eine Kalenderwoche gebunden, kein Rezept nötig) -
  z.B. für Hygieneartikel oder Getränke, die zu keinem Gericht gehören.
  Eigener Lösch-Button pro manuellem Posten, reiht sich in dieselbe
  kategorisierte Sortierung ein wie die Rezept-Zutaten.
- **Weiche Wiederholungs-Gewichtung (keine harte Sperre).** Neue Funktion
  `services/planning.py: recent_usage_counts()` zählt, wie oft ein Rezept in
  den letzten `REPETITION_LOOKBACK_WEEKS` Wochen (aktuell 8) VOR dem gerade
  geplanten Tag im Plan-Kalender vorkam. `weighted_recipe_choice()`
  reduziert die Ziehungswahrscheinlichkeit je Verwendung um den Faktor
  1/(Anzahl+1) - nie verwendet = volle Chance, häufig verwendet = kleine,
  aber nie null Chance. Multipliziert sich mit der bestehenden
  Favoriten-Gewichtung. Da die Saison-Vorauswahl in `choose_recipe()`
  bereits VOR dieser Gewichtung greift, werden dadurch automatisch auch
  gerade saisonale Rezepte bevorzugt, ohne einen eigenen dritten Faktor.
- **Manuelle Rezeptauswahl auf der Plan-Seite.** Sowohl Hauptgericht als
  auch jede einzelne Beilage lassen sich per ✏️-Button statt zu würfeln
  auch direkt aus allen Rezepten auswählen (Such-/Auswahlbox, ersetzt die
  Anzeige an Ort und Stelle). Bewusst OHNE jede der beim Würfeln geltenden
  Automatik-Regeln (Kategorie-Balance, Nachbarschaft, Wochen-Dubletten,
  Wiederholungs-Gewichtung) - eine manuelle Auswahl ist ein expliziter
  Nutzerwunsch. Setzt bei einem ausgenommenen Tag `excluded` automatisch
  zurück (`routes/plan/day_actions.py: set_main_day`).
- **Beliebig viele Beilagen pro Tag.** Neue Tabelle `PlanDaySide` ersetzt
  die frühere `PlanDay.side_recipe_id`-Einzelspalte (Migration in `app.py`
  inkl. Tabellen-Neuaufbau, da SQLite eine per Fremdschlüssel referenzierte
  Spalte nicht direkt per `DROP COLUMN` entfernen lässt). Ein Tag kann jetzt
  beliebig viele Beilagen gleichzeitig haben, jede einzeln würfelbar/manuell
  ersetzbar/entfernbar (`side/add`, `side/<id>/reroll`, `side/<id>/set`,
  `side/<id>/remove`) und per Drag-and-Drop einzeln auf einen anderen Tag
  verschiebbar (`side/<id>/move/<datum>`, `static/plan.js: moveSideDish`) -
  ohne den Rest des Ziel-/Quelltags anzutasten. Wird die ganze Tageskarte
  (Hauptgericht) verschoben/getauscht, wandern alle ihre Beilagen mit.
  Auch beim Erstellen einer neuen Woche (`create_week.html`) lassen sich
  einem Tag mehrere Beilagen zuweisen (verteilt sich automatisch auf den
  Tag mit den bisher wenigsten).
- **Rezept-Import von chefkoch.de.** Neue Felder `Recipe.source_url`
  (Link) und `Recipe.instructions` (Anleitung als Freitext), beide auch von
  Hand nutzbar. Neuer Service `services/recipe_import.py`: liest die
  eingebetteten schema.org/Recipe-JSON-LD-Strukturdaten einer chefkoch.de-
  Seite aus (dasselbe Format, mit dem Suchmaschinen Rezepte crawlen -
  robuster als HTML-Scraping, da es sich praktisch nie ändert) und liefert
  Name, Portionszahl, Nährwerte (falls vorhanden), Zutaten (Best-Effort in
  Menge/Einheit/Name zerlegt) und Zubereitungsschritte. Der Import-Button
  auf der Rezept-Erstellen-Seite befüllt damit NUR das Formular - der
  Nutzer prüft/ergänzt (insbesondere die Kategorie, die sich nicht
  automatisch zuordnen lässt) und speichert danach ganz normal. Aus
  SSRF-Sicherheitsgründen bewusst hart auf chefkoch.de beschränkt
  (`ALLOWED_HOSTS`) - ließe sich später um weitere schema.org/Recipe-
  kompatible Kochseiten erweitern, da der Parser selbst nicht
  chefkoch-spezifisch ist.

## Vorgeschlagen

1. **Nährwerte aus den Zutaten errechnen.** Statt Kalorien/Eiweiß/Kohlenhydrate/
   Fett manuell pro Rezept einzutragen, direkt aus den hinterlegten Zutaten
   und deren Menge berechnen. Braucht eine Nährwert-Referenz pro Zutat
   (z.B. Werte je 100g an `Ingredient`/eine eigene Zutaten-Stammdaten-Tabelle)
   plus Einheiten-Umrechnung (g/ml/Stück), da `Ingredient.unit` aktuell
   Freitext ist.
2. **Rezept-Import auf weitere Kochseiten ausweiten.** Der bestehende
   chefkoch.de-Import (siehe oben) liest bereits Standard-schema.org/
   Recipe-Strukturdaten - andere Kochseiten (z.B. Kptncook, Lecker.de,
   Essen&Trinken) ließen sich vermutlich einfach durch Ergänzen ihrer
   Domain in `ALLOWED_HOSTS` unterstützen, sofern sie dasselbe Format nutzen.
