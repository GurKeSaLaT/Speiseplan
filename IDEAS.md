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

## Weitere Ideen (von Claude vorgeschlagen)

5. **Wiederholungssperre über mehrere Wochen.** Aktuell wird ein generierter
   Plan nicht gespeichert, daher kann sich ein Gericht direkt in der
   Folgewoche wiederholen. Mit einer kleinen Plan-Historie (letzte
   Erstellungsdaten pro Rezept) ließe sich das bei der automatischen Auswahl
   vermeiden.

6. **Favoriten/Bewertung.** Rezepte markieren oder bewerten (z.B. Sterne),
   sodass beliebte Gerichte beim Würfeln häufiger drankommen als selten
   gekochte.

7. **Portionsanzahl & Mengenskalierung.** Aktuell sind Nährwerte/Zutaten fix
   "pro Portion" hinterlegt. Eine Personenzahl je Plan (oder je Tag) würde
   die Einkaufsliste automatisch mit hochrechnen.

8. **Zutaten-Kategorien für die Einkaufsliste.** Zutaten nach Supermarkt-
   Bereich gruppieren (Gemüse, Milchprodukte, Tiefkühl, ...) statt nur
   alphabetisch, um den Einkauf zu erleichtern.

9. **Wochen-Nährwertübersicht.** Summe/Durchschnitt von Kalorien und Makros
   über die ganze Woche anzeigen, nicht nur pro Tag.

10. **Rezept-Import.** Rezepte per URL oder Copy-Paste aus einer bestehenden
    Quelle importieren, statt jede Zutat manuell einzutippen.
