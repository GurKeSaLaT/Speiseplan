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
- **Saison-Zuordnung für Rezepte.** Neues `Recipe.season`-Feld
  (Frühling/Sommer/Herbst/Winter, leer = ganzjährig). Die automatische
  Auswahl (`choose_recipe()`) bevorzugt die aktuelle Saison, weicht aber auf
  jede Saison aus, wenn nötig - manuelle Auswahl ist nie eingeschränkt.

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

3. **Favoriten/Bewertung.** Rezepte markieren oder bewerten (z.B. Sterne),
   sodass beliebte Gerichte beim Würfeln häufiger drankommen als selten
   gekochte.

4. **Portionsanzahl & Mengenskalierung.** Aktuell sind Nährwerte/Zutaten fix
   "pro Portion" hinterlegt. Eine Personenzahl je Plan (oder je Tag) würde
   die Einkaufsliste automatisch mit hochrechnen.

5. **Zutaten-Kategorien für die Einkaufsliste.** Zutaten nach Supermarkt-
   Bereich gruppieren (Gemüse, Milchprodukte, Tiefkühl, ...) statt nur
   alphabetisch, um den Einkauf zu erleichtern.

6. **Wochen-Nährwertübersicht.** Summe/Durchschnitt von Kalorien und Makros
   über die ganze Woche anzeigen, nicht nur pro Tag.

7. **Rezept-Import.** Rezepte per URL oder Copy-Paste aus einer bestehenden
   Quelle importieren, statt jede Zutat manuell einzutippen.
