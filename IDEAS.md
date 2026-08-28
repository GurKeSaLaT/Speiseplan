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

## Vorgeschlagen

1. **Nährwerte aus den Zutaten errechnen.** Statt Kalorien/Eiweiß/Kohlenhydrate/
   Fett manuell pro Rezept einzutragen, direkt aus den hinterlegten Zutaten
   und deren Menge berechnen. Braucht eine Nährwert-Referenz pro Zutat
   (z.B. Werte je 100g an `Ingredient`/eine eigene Zutaten-Stammdaten-Tabelle)
   plus Einheiten-Umrechnung (g/ml/Stück), da `Ingredient.unit` aktuell
   Freitext ist.

## Weitere Ideen (von Claude vorgeschlagen)

2. **Dauerhafter Plan-Kalender.** Aktuell wird ein generierter Plan nicht
   gespeichert - er existiert nur serverseitig gerendert bzw. im Browser,
   solange die Plan-Seite offen ist. Sinnvoller wäre ein echtes
   Kalender-Modell (z.B. eine `PlanEntry`-Tabelle: Datum, Rezept-ID,
   Haupt-/Beilage), das jeden erstellten/geänderten Tag dauerhaft
   persistiert. Das ist die Grundlage für:
   - Wiederholungssperre über mehrere Wochen (Gerichte meiden, die erst
     kürzlich dran waren)
   - Rückblick auf vergangene Wochen ("Was gab's letzten Mittwoch?")
   - spätere Auswertungen (z.B. wie oft welche Kategorie/welches Rezept
     vorkam)

   Größerer Umbau: aktuell ist die Plan-Seite reine Anzeige eines einmalig
   generierten Ergebnisses ohne DB-Anbindung; müsste auf Speichern pro
   Tag/Woche umgestellt werden.

3. **Zutaten-Kategorien für die Einkaufsliste.** Zutaten nach Supermarkt-
   Bereich gruppieren (Gemüse, Milchprodukte, Tiefkühl, ...) statt nur
   alphabetisch, um den Einkauf zu erleichtern.

4. **Rezept-Import.** Rezepte per URL oder Copy-Paste aus einer bestehenden
   Quelle importieren, statt jede Zutat manuell einzutippen.
