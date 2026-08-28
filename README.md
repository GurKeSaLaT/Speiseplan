# 🍽️ Speiseplan

Ein selbst gehosteter Wochen-Speiseplaner mit dauerhaftem Kalender: Rezepte
mit Nährwerten und Zutaten pflegen, Wochen per Klick oder Drag-and-Drop
zusammenstellen, den Rest automatisch balanciert auffüllen lassen und am
Ende direkt eine konsolidierte Einkaufsliste bekommen.

## Features

- **Dauerhafter Plan-Kalender** – jede geplante Woche wird pro Kalendertag
  in der Datenbank gespeichert, nicht nur flüchtig angezeigt. Die
  Startseite zeigt die aktuelle Woche mit Navigation (vorherige/nächste
  Woche, Datumssprung); unbeplante Wochen zeigen einen
  "Neuen Wochenplan erstellen"-Button.
- **Rezeptverwaltung** – Gerichte mit Kategorie, Nährwerten (Kalorien,
  Eiweiß, Kohlenhydrate, Fett), Personenzahl und einer beliebigen
  Zutatenliste anlegen, bearbeiten und löschen.
- **Wochenplanung per Drag-and-Drop** – Gerichte aus der Live-Suche auf
  einzelne Wochentage ziehen oder klicken, Tage per Drag-and-Drop
  komplett tauschen (auch auf der fertigen Plan-Seite), einzelne Tage
  von der Planung ausnehmen.
- **Zusatzgerichte/Beilagen** – Rezepte lassen sich als Beilage markieren.
  Sie belegen keinen eigenen Tages-Slot, sondern werden zusätzlich zum
  Hauptgericht hinzugefügt – auch an Tagen ohne Hauptgericht – entweder
  fest vor dem Erstellen des Plans oder nachträglich per Würfel-Button.
- **Automatisches, balanciertes Auffüllen** – Tage ohne feste Zuweisung
  werden zufällig, aber möglichst gleichmäßig über alle Kategorien verteilt
  aufgefüllt, ohne dieselbe Kategorie an zwei aufeinanderfolgenden Tagen zu
  wiederholen (wenn vermeidbar).
- **Saison-Zuordnung** – Rezepte können mehrere Standard-Saisons und/oder
  einen eigenen Zeitraum bekommen; die automatische Auswahl bevorzugt
  gerade verfügbare Gerichte, schränkt die manuelle Auswahl aber nie ein.
- **Favoriten** – als Favorit markierte Rezepte werden beim Würfeln
  häufiger gezogen als andere.
- **Personenzahl & Mengenskalierung** – jeder Wochentag hat ein eigenes
  Personen-Feld, das die Zutatenmengen dieses Tages in der Einkaufsliste
  hoch-/runterrechnet.
- **Wochen-Nährwertübersicht** – Summe und Durchschnitt von Kalorien und
  Makros über die ganze Woche.
- **Einkaufsliste** – Zutaten aller geplanten Haupt- und Zusatzgerichte
  werden automatisch zusammengerechnet und lassen sich beim Einkaufen
  abhaken.

Eine laufende Liste weiterer Ideen (umgesetzt und geplant) steht in
[IDEAS.md](IDEAS.md).

## Tech-Stack

- [Flask](https://flask.palletsprojects.com/) + [Flask-SQLAlchemy](https://flask-sqlalchemy.palletsprojects.com/),
  Routen als Blueprints organisiert (siehe Projektstruktur)
- SQLite als Datenbank (liegt in `instance/speiseplan.db`)
- [Bootstrap 5](https://getbootstrap.com/) (lokal eingebunden, kein CDN)
- Vanilla JavaScript für Drag-and-Drop, Live-Suche und die dynamische
  Plan-/Einkaufslisten-Aktualisierung; Server-Daten werden dem Frontend
  über ein `window.PLAN_DATA`-JSON-Objekt (Jinja `tojson`) bereitgestellt

## Setup

```bash
git clone git@github.com:GurKeSaLaT/Speiseplan.git
cd Speiseplan

python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

python3 app.py
```

Die App läuft danach unter `http://127.0.0.1:5000` und leitet direkt auf
die aktuelle Kalenderwoche weiter. Die SQLite-Datenbank wird beim ersten
Start automatisch unter `instance/speiseplan.db` inklusive
Standardkategorien angelegt; bei späteren Updates werden fehlende
Tabellen/Spalten automatisch nachmigriert.

### Mit Docker

```bash
docker build -t speiseplan .
docker run -p 5000:5000 speiseplan
```

## Projektstruktur

```
app.py                     App-Setup, Blueprint-Registrierung, DB-Migration
models.py                  SQLAlchemy-Modelle (Category, Recipe, RecipeSeason, Ingredient, PlanDay)
routes/
  plan.py                  Kalender-Wochenansicht, Plan erstellen, Würfeln/Tauschen (Blueprint "plan")
  recipes.py                Rezept-CRUD (Blueprint "recipes")
  categories.py             Kategorie-CRUD (Blueprint "categories")
  manage.py                 Verwaltungs-Startseite (Blueprint "manage")
services/
  planning.py               Wochen-/Datums-Helfer, Kategorie-Balance, Rezeptauswahl, Favoriten-Gewichtung
  seasons.py                 Saison-Zuordnung (Standard-Saisons + eigene Zeiträume)
templates/                  Jinja2-Templates (Plan-Kalender, Wochenplan erstellen, Verwaltung)
static/
  plan.js                    Live-Interaktionen der Plan-Seite (würfeln, tauschen, Einkaufsliste, ...)
  create_week.js             Live-Suche & Drag-and-Drop beim Wochenplan-Erstellen
  bootstrap.*, style.css     Lokales Bootstrap 5 + eigenes Stylesheet
instance/speiseplan.db      SQLite-Datenbank
```

## Lizenz

Veröffentlicht unter der [MIT-Lizenz](LICENSE).
