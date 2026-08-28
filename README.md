# 🍽️ Speiseplan

Ein selbst gehosteter Wochen-Speiseplaner: Rezepte mit Nährwerten und Zutaten
pflegen, per Klick oder Drag-and-Drop auf die Wochentage verteilen, den Rest
automatisch nach Kategorie balanciert auffüllen lassen und am Ende direkt
eine konsolidierte Einkaufsliste bekommen.

## Features

- **Rezeptverwaltung** – Gerichte mit Kategorie, Nährwerten (Kalorien,
  Eiweiß, Kohlenhydrate, Fett) und einer beliebigen Zutatenliste anlegen,
  bearbeiten und löschen.
- **Wochenplanung per Drag-and-Drop** – Gerichte aus der Live-Suche auf
  einzelne Wochentage ziehen oder klicken, Tage untereinander per
  Drag-and-Drop tauschen, einzelne Tage von der Planung ausnehmen.
- **Zusatzgerichte/Beilagen** – Rezepte lassen sich als Beilage markieren.
  Sie belegen keinen eigenen Tages-Slot, sondern werden zusätzlich zum
  Hauptgericht hinzugefügt – entweder fest vor dem Erstellen des Plans oder
  nachträglich per Würfel-Button auf der Plan-Seite.
- **Automatisches, balanciertes Auffüllen** – Tage ohne feste Zuweisung
  werden beim Erstellen des Plans zufällig, aber möglichst gleichmäßig über
  alle Kategorien verteilt aufgefüllt.
- **Einzelne Tage neu würfeln** – Sowohl Hauptgericht als auch Beilage lassen
  sich auf der fertigen Plan-Seite unabhängig voneinander neu würfeln.
- **Einkaufsliste** – Zutaten aller geplanten Haupt- und Zusatzgerichte
  werden automatisch zusammengerechnet und lassen sich beim Einkaufen
  abhaken.

## Tech-Stack

- [Flask](https://flask.palletsprojects.com/) + [Flask-SQLAlchemy](https://flask-sqlalchemy.palletsprojects.com/)
- SQLite als Datenbank (liegt in `instance/speiseplan.db`)
- [Bootstrap 5](https://getbootstrap.com/) (lokal eingebunden, kein CDN)
- Vanilla JavaScript für Drag-and-Drop, Live-Suche und die dynamische
  Plan-/Einkaufslisten-Aktualisierung

## Setup

```bash
git clone git@github.com:GurKeSaLaT/Speiseplan.git
cd Speiseplan

python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

python3 app.py
```

Die App läuft danach unter `http://127.0.0.1:5000`. Die SQLite-Datenbank
wird beim ersten Start automatisch unter `instance/speiseplan.db` inklusive
Standardkategorien angelegt; bei späteren Updates werden fehlende Spalten
automatisch nachmigriert.

### Mit Docker

```bash
docker build -t speiseplan .
docker run -p 5000:5000 speiseplan
```

## Projektstruktur

```
app.py                     Flask-Routen & Planungs-/Würfel-Logik
models.py                  SQLAlchemy-Modelle (Category, Recipe, Ingredient)
templates/                 Jinja2-Templates (Wochenplaner, Verwaltung, Plan)
static/                    Lokales Bootstrap 5 + eigenes Stylesheet
instance/speiseplan.db     SQLite-Datenbank
```

## Lizenz

Veröffentlicht unter der [MIT-Lizenz](LICENSE).
