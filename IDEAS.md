# Ideen für Erweiterungen

Backlog für zukünftige Features - noch nicht umgesetzt, nur gesammelt.

## Vorgeschlagen

1. **Tage im fertigen Plan tauschen.** Auf der Plan-Seite (`plan.html`) gibt es
   bisher nur den Re-Roll-Würfel pro Tag. Drag-and-Drop-Tausch existiert
   aktuell nur auf der Planungsseite (`index.html`) vor dem Erstellen des
   Plans - müsste auf die fertige Plan-Ansicht übertragen werden (inkl.
   serverseitigem Abgleich, welches Rezept an welchem Tag steht).

2. **Beilage auch an Tagen ohne Hauptgericht.** Betrifft vor allem von der
   Planung ausgenommene Tage (🚫): aktuell blockiert "ausgenommen" sowohl
   Haupt- als auch Zusatzgericht (siehe `toggleExcludeDay()` in `index.html`
   und die `{% if i not in excluded_days %}`-Bedingung in `plan.html`). Die
   Beilagen-Zuweisung müsste von der Hauptgericht-Exklusion entkoppelt
   werden, damit z.B. ein reiner Beilagen-Tag möglich ist.

3. **Auswahl-Logik erweitern**
   - a. Keine gleiche Kategorie an zwei aufeinanderfolgenden Tagen (z.B.
     nicht Montag und Dienstag beide "Pasta"). `get_balanced_category_slots()`
     in `app.py` müsste dafür eine Nachbarschaftsbedingung statt nur die
     Gesamt-Balance berücksichtigen.

4. **Saison-Zuordnung für Rezepte.** Neues Feld an `Recipe` (z.B.
   Frühling/Sommer/Herbst/Winter oder ein Monatsbereich), das beim
   automatischen Auffüllen und beim Würfeln berücksichtigt wird - z.B.
   Kürbisgerichte nur im Herbst, Grillgerichte nur im Sommer.

5. **Nährwerte aus den Zutaten errechnen.** Statt Kalorien/Eiweiß/Kohlenhydrate/
   Fett manuell pro Rezept einzutragen, direkt aus den hinterlegten Zutaten
   und deren Menge berechnen. Braucht eine Nährwert-Referenz pro Zutat
   (z.B. Werte je 100g an `Ingredient`/eine eigene Zutaten-Stammdaten-Tabelle)
   plus Einheiten-Umrechnung (g/ml/Stück), da `Ingredient.unit` aktuell
   Freitext ist.

## Weitere Ideen (von Claude vorgeschlagen)

6. **Dauerhafter Plan-Kalender.** Aktuell wird ein generierter Plan nicht
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

7. **Favoriten/Bewertung.** Rezepte markieren oder bewerten (z.B. Sterne),
   sodass beliebte Gerichte beim Würfeln häufiger drankommen als selten
   gekochte.

8. **Portionsanzahl & Mengenskalierung.** Aktuell sind Nährwerte/Zutaten fix
   "pro Portion" hinterlegt. Eine Personenzahl je Plan (oder je Tag) würde
   die Einkaufsliste automatisch mit hochrechnen.

9. **Zutaten-Kategorien für die Einkaufsliste.** Zutaten nach Supermarkt-
   Bereich gruppieren (Gemüse, Milchprodukte, Tiefkühl, ...) statt nur
   alphabetisch, um den Einkauf zu erleichtern.

10. **Wochen-Nährwertübersicht.** Summe/Durchschnitt von Kalorien und Makros
    über die ganze Woche anzeigen, nicht nur pro Tag.

11. **Rezept-Import.** Rezepte per URL oder Copy-Paste aus einer bestehenden
    Quelle importieren, statt jede Zutat manuell einzutippen.
