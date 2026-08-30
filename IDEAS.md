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
  SSRF-Sicherheitsgründen bewusst hart auf eine Allowlist (`ALLOWED_HOSTS`)
  beschränkt - ließe sich um weitere schema.org/Recipe-kompatible
  Kochseiten erweitern, da der Parser selbst nicht chefkoch-spezifisch ist
  (siehe der folgende Eintrag, der genau das umgesetzt hat).
- **Rezept-Import auf acht weitere deutschsprachige Kochseiten
  ausgeweitet.** `ALLOWED_HOSTS` in `services/recipe_import.py` umfasst
  jetzt zusätzlich zu chefkoch.de: lecker.de, essen-und-trinken.de,
  eatsmarter.de, kuechengoetter.de, gutekueche.de UND gutekueche.at (zwei
  getrennte, baugleiche Seiten für Deutschland/Österreich), daskochrezept.de,
  brigitte.de und emmikochteinfach.de - jede einzeln per Live-Abruf
  geprüft, ob sie tatsächlich ein `"@type": "Recipe"`-JSON-LD-Objekt
  einbettet, BEVOR sie aufgenommen wurde (kein reines Domain-Raten). Bewusst
  NICHT aufgenommen: kochbar.de (Inhalte werden rein clientseitig per
  JavaScript nachgeladen, `requests` sieht davon nichts), ichkoche.at (keine
  JSON-LD-Daten überhaupt) und springlane.de (markiert seine Rezeptseiten
  als `"Article"`, nicht als `"Recipe"`) - für alle drei bräuchte es
  entweder HTML-Scraping oder eine echte Browser-Engine, beides ein
  deutlich größerer (und brüchigerer) Umbau als das Ergänzen einer Domain.
  `KNOWN_UNITS` (siehe `_parse_ingredient_line`) um ausgeschriebene
  Einheiten wie "Gramm"/"Esslöffel" erweitert, die chefkoch.de kaum, andere
  der neuen Seiten aber regelmäßig statt Abkürzungen verwenden.
- **Hell-/Dunkelmodus.** Drei Einstellungen (System/Hell/Dunkel), Umschalter
  in der Verwaltung als `btn-check`-Radiogruppe. `templates/base.html`
  wendet die gespeicherte Einstellung (localStorage, pro Browser/Gerät) ganz
  am Anfang von `<head>` an, noch vor den CSS-Links, damit kein falsches
  Theme aufblitzt - über dasselbe `data-bs-theme`-Attribut, auf das
  Bootstrap 5.3 selbst reagiert und darüber fast alle eigenen Komponenten
  automatisch anpasst. `static/style.css` definiert dafür eigene Farb-Tokens
  unter `[data-bs-theme="dark"]` neu, plus gezielte Korrekturen für die
  wenigen Bootstrap-Klassen (`.text-dark`, `.bg-light`/`.bg-white`,
  `.btn-dark`/`.btn-outline-dark`, `.bg-dark`), die "dark"/"light" als
  reinen, nicht themefähigen Farbnamen verstehen statt sich zusammen mit dem
  Rest der Seite anzupassen.
- **Einheiten-Vereinheitlichung.** Neues `services/units.py`: fasst
  unterschiedliche Schreibweisen derselben Einheit zusammen (z.B.
  "g"/"Gramm"/"gr" oder "kg"/"Kilo"/"Kilogramm") und rechnet Mengen aus
  zwei Familien mit eindeutiger Basiseinheit - Masse -> Gramm, Volumen
  (inkl. Küchenmaßen TL/EL/Tasse/cup, feste Näherungswerte 5/15/250 ml) ->
  Milliliter - beim Speichern IMMER auf diese Basis um ("1 kg" wird zu
  "1000 g", "2 EL" zu "30 ml"). Greift sowohl beim manuellen Anlegen/
  Bearbeiten eines Rezepts (`routes/recipes.py`) als auch beim Import
  (`services/recipe_import.py: _parse_ingredient_line`) sowie einmalig für
  Bestandsdaten (`renormalize_existing_ingredients()`, läuft idempotent bei
  jedem App-Start in `app.py: init_db()` - eine bereits kanonische Zeile
  bleibt unverändert). Nicht umrechenbare, stückbasierte Einheiten (Stk,
  Bund, Prise, Dose, ...) bleiben unangetastet.

  Neues Singleton-Modell `AppSettings` (`services/settings.py`) speichert,
  in welcher Einheit je Familie ANGEZEIGT werden soll (g oder kg, ml oder
  l) - eigene Verwaltungsseite `/manage/units` (Blueprint `settings`,
  Kachel "📏 Einheiten" auf `/manage`). Die kanonisch gespeicherten Werte
  bleiben davon unberührt; `convert_for_display()` rechnet NUR für die
  Anzeige um, an jeder Stelle, an der Zutatenmengen zu sehen sind:
  `jsonify_recipe()` (Einkaufsliste, Wochenplan-Seite - da die
  clientseitige Aggregation in `rebuildShoppingList()` gleichnamige
  Zutaten rein nach "Name+Einheit" gruppiert, ist entscheidend, dass ALLE
  Vorkommen einer Familie serverseitig konsistent in derselben Einheit
  ankommen), das Rezept-Bearbeiten-Formular (`recipe_edit_view()`)
  und die Import-Vorschau (`import_recipe_preview()`). Die Umrechnung ist
  exakt und verlustfrei umkehrbar (Faktor 1000), ein Speichern ohne
  Änderung eines in Kilogramm angezeigten Werts liefert über
  `normalize_amount_unit()` wieder exakt denselben kanonischen Gramm-Wert.
- **Zutaten gleichsetzen.** Neues Modell `IngredientAlias` (`raw_name`
  eindeutig -> `canonical_name`) + `services/ingredient_aliases.py`:
  ordnet konkrete Zutatennamen (z.B. "Spaghetti", "Fusilli") einem
  gemeinsamen Namen zu (z.B. "Nudeln"), NUR für die Einkaufsliste - die
  Zutatenliste eines einzelnen Rezepts zeigt immer den ursprünglich
  eingetragenen Namen unverändert. `normalize_ingredient_name()` wird in
  `jsonify_recipe()` anstelle des bisherigen reinen `.strip().title()`
  aufgerufen (macht das intern weiterhin, plus Alias-Ersetzung, falls
  vorhanden) - ein Zutatenname ohne Eintrag bleibt einfach er selbst,
  keine Gruppierung ist der Standardfall. Eigene Verwaltungsseite
  `/manage/ingredient-aliases` (Blueprint `settings`, Kachel auf
  `/manage`): eine Zeile pro aktuell in irgendeinem Rezept verwendetem
  Zutatennamen mit editierbarem "gilt als"-Feld, alle auf einmal per
  Formular speicherbar (parallele `raw_name[]`/`canonical_name[]`-Listen,
  analog zu den Zutatenzeilen der Rezept-Formulare) statt eines
  Rundtrips pro Zeile - bei potenziell hunderten Zutaten sonst
  unpraktisch. Ein Feld, das unverändert bleibt (gilt weiterhin nur sich
  selbst), erzeugt keinen Alias-Datensatz.

## Vorgeschlagen

1. **Nährwerte aus den Zutaten errechnen.** Statt Kalorien/Eiweiß/Kohlenhydrate/
   Fett manuell pro Rezept einzutragen, direkt aus den hinterlegten Zutaten
   und deren Menge berechnen. Braucht eine Nährwert-Referenz pro Zutat
   (z.B. Werte je 100g an `Ingredient`/eine eigene Zutaten-Stammdaten-Tabelle).
   Die Einheiten-Umrechnung (g/ml) gibt es seit `services/units.py` bereits -
   nur stückbasierte Einheiten (Stk, Bund, ...) bräuchten für exakte
   Nährwerte weiterhin eine Zutat-spezifische Gewichtsangabe.
2. **Rezept-Import auf noch mehr Kochseiten ausweiten.** Der Import
   unterstützt inzwischen 9 Seiten (siehe "Umgesetzt" oben) - weitere
   schema.org/Recipe-kompatible Seiten (z.B. internationale Portale, Blogs)
   lassen sich genauso per Live-Prüfung + Domain-Ergänzung in
   `ALLOWED_HOSTS` hinzufügen. Kptncook wäre z.B. eine App ohne
   öffentliche Rezept-Webseiten und daher so nicht unterstützbar.

## Wartet auf echten Mailversand

Alles hier ist erst sinnvoll umsetzbar, sobald `services/mail.py` echte
Mails verschickt statt sie nur zu loggen (siehe dortiger Docstring - noch
keine SMTP-Zugangsdaten vorhanden).

1. **Benachrichtigung bei Plan-Einladung.** Aktuell merkt ein eingeladener
   Nutzer eine Freigabe nur, wenn er selbst auf `/manage/sharing`
   nachschaut - die eigentliche Einladungs-Mail (`send_invite_email()`)
   wird nur geloggt und zusätzlich als kopierbarer Link auf der
   Freigabeseite angezeigt (siehe `templates/sharing.html`: "Ausstehende
   Einladungen").
2. **Passwort-Reset per E-Mail.** Es gibt aktuell keine
   "Passwort vergessen"-Funktion - ein vergessenes Passwort lässt sich
   nirgends selbst zurücksetzen. Bräuchte einen zeitlich begrenzten
   Reset-Link, der per Mail verschickt wird (analog zum
   Einladungs-Link-Mechanismus).
3. **E-Mail-Verifizierung bei der Registrierung.** `routes/auth.py:
   register()` prüft die eingegebene Adresse aktuell nur auf grobe Form
   (`services/auth.py: EMAIL_PATTERN`), nicht auf tatsächliche
   Erreichbarkeit - ein Bestätigungslink wäre ohne echten Mailversand
   nicht sinnvoll umsetzbar.
