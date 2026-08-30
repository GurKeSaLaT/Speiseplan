# 🍽️ Speiseplan

Ein selbst gehosteter Wochen-Speiseplaner mit dauerhaftem Kalender: Rezepte
mit Nährwerten und Zutaten pflegen, Wochen per Klick oder Drag-and-Drop
zusammenstellen, den Rest automatisch balanciert auffüllen lassen und am
Ende direkt eine konsolidierte Einkaufsliste bekommen.

## Features

- **Nutzerkonten & geteilte Pläne** – Registrierung per Name/E-Mail/Passwort,
  Login über die E-Mail-Adresse. Jeder Nutzer kann sich beliebig viele eigene
  Wochenpläne anlegen (Umschalter in der Seitenleiste, Standard ist der
  gesternte Plan) und einzelne Pläne per E-Mail-Adresse mit anderen teilen –
  existiert dazu bereits ein Konto, ist der Plan sofort geteilt, sonst wird
  eine Einladung zum Registrieren "verschickt" (aktuell nur geloggt und als
  Link auf der Freigabeseite angezeigt, da noch kein SMTP angebunden ist).
  Rezepte, Kategorien, Einheiten und Zutaten-Gleichsetzung gehören jeweils
  EINEM Plan; ein Rezept lässt sich zusätzlich in weitere eigene Pläne
  einbinden (echte Verknüpfung, keine Kopie). Jede Tageskachel im
  Wochenplan zeigt zusätzlich (pro Plan abschaltbar), was an dem Tag in den
  ÜBRIGEN eigenen Plänen gekocht wird.
- **Dauerhafter Plan-Kalender** – jede geplante Woche wird pro Kalendertag
  in der Datenbank gespeichert, nicht nur flüchtig angezeigt. Die
  Startseite zeigt die aktuelle Woche mit Navigation (vorherige/nächste
  Woche, Datumssprung); unbeplante Wochen zeigen einen
  "Neuen Wochenplan erstellen"-Button.
- **Hell-/Dunkelmodus** – folgt standardmäßig der Betriebssystem-Einstellung,
  lässt sich in der Verwaltung (⚙️ → 🎨 Darstellung) aber auch fest auf Hell
  oder Dunkel stellen. Die Auswahl wird pro Browser/Gerät gespeichert.
- **Rezeptverwaltung** – Gerichte mit Kategorie, Nährwerten (Kalorien,
  Eiweiß, Kohlenhydrate, Fett), Personenzahl, einer beliebigen Zutatenliste,
  Link und Zubereitungsanleitung anlegen, bearbeiten und löschen.
- **Einheiten-Vereinheitlichung** – Zutatenmengen werden beim Eintragen und
  Importieren automatisch auf eine kanonische Form gebracht (Masse → Gramm,
  Volumen inkl. TL/EL/Tasse → Milliliter; "1 kg" wird intern zu "1000 g").
  In der Verwaltung (⚙️ → 📏 Einheiten) lässt sich einstellen, ob Mengen in
  g/kg bzw. ml/l angezeigt werden - gilt überall dort, wo Mengen zu sehen
  sind (Rezept-Bearbeiten, Import-Vorschau, Einkaufsliste).
- **Zutaten gleichsetzen** – in der Verwaltung (⚙️ → 🔗 Zutaten gleichsetzen)
  lässt sich festlegen, dass z.B. "Spaghetti" und "Fusilli" auf der
  Einkaufsliste als "Nudeln" zusammengefasst werden. Betrifft nur die
  Einkaufsliste - Rezepte zeigen weiterhin ihren eigenen Zutatennamen.
- **Rezept-Import von neun deutschsprachigen Kochseiten** – chefkoch.de,
  lecker.de, essen-und-trinken.de, EAT SMARTER, Küchengötter,
  gutekueche.de/.at, DasKochrezept, BRIGITTE und Emmikochteinfach. Ein Link
  genügt: Name, Portionszahl, Nährwerte (falls angegeben), Zutaten und
  Anleitung werden automatisch ausgelesen und ins Anlegen-Formular
  übernommen; gespeichert wird erst nach Prüfung/Ergänzung (v.a. der
  Kategorie) durch den Nutzer.
- **Wochenplanung per Drag-and-Drop** – Gerichte aus der Live-Suche auf
  einzelne Wochentage ziehen oder klicken, Tage per Drag-and-Drop
  komplett tauschen (auch auf der fertigen Plan-Seite, Beilagen wandern
  dabei mit), einzelne Tage von der Planung ausnehmen. Auf der fertigen
  Plan-Seite lässt sich jedes Hauptgericht und jede Beilage per ✏️-Button
  auch manuell aus allen Rezepten auswählen statt nur zu würfeln.
- **Zusatzgerichte/Beilagen** – Rezepte lassen sich als Beilage markieren.
  Sie belegen keinen eigenen Tages-Slot, sondern werden zusätzlich zum
  Hauptgericht hinzugefügt – auch an Tagen ohne Hauptgericht – entweder
  fest vor dem Erstellen des Plans oder nachträglich per Würfel-/
  Auswahl-Button. Ein Tag kann beliebig viele Beilagen gleichzeitig haben;
  jede einzelne lässt sich unabhängig neu würfeln, ersetzen, entfernen oder
  per Drag-and-Drop auf einen anderen Tag verschieben.
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

Die App läuft danach unter `http://127.0.0.1:5000` und leitet auf die
Login-Seite weiter. `instance/speiseplan.db` ist im Repo mit
Beispieldaten (rund 100 importierte Rezepte samt Zutaten-Gleichsetzung)
sowie zwei generischen Demo-Konten versioniert, damit sich die App nach
dem Setup direkt sinnvoll ausprobieren lässt, statt mit einer leeren
Datenbank zu starten:

| E-Mail                  | Passwort  |
|--------------------------|-----------|
| `nutzer1@example.com`    | `Nutzer1` |
| `nutzer2@example.com`    | `Nutzer2` |

Über den "Konto erstellen"-Button auf der Login-Seite lässt sich
jederzeit ein weiteres, eigenes Konto anlegen. Bei späteren Updates
werden fehlende Tabellen/Spalten automatisch nachmigriert. Für das
Docker-Deployment ist das Beispieldaten-Detail irrelevant - dort wird
`instance/` als Volume auf ein Verzeichnis außerhalb des Containers
gemountet (siehe unten), das immer Vorrang vor dem im Image enthaltenen
Datenbankstand hat.

Standardmäßig lauscht der Server auf allen Netzwerk-Schnittstellen
(`0.0.0.0`) - für einen rein lokalen Testlauf, der nicht aus dem
LAN erreichbar sein soll, `HOST=127.0.0.1 python3 app.py` verwenden.

### Mit Docker

```bash
docker build -t speiseplan .
docker run -p 5000:5000 speiseplan
```

## Tests

```bash
pip install -r requirements.txt -r requirements-dev.txt
pytest
```

Läuft komplett gegen eine eigene, temporäre SQLite-Datenbank (siehe
`tests/conftest.py` und `DATABASE_URL` in `app.py`) - `instance/speiseplan.db`
bleibt dabei unangetastet.

## Projektstruktur

```
app.py                        App-Setup, Blueprint-Registrierung, DB-Migration
models.py                     SQLAlchemy-Modelle (User, Plan, PlanMembership, PendingPlanInvite,
                               Category, Recipe, RecipePlanLink, RecipeSeason, Ingredient,
                               PlanDay, PlanDaySide, ExtraShoppingItem, AppSettings,
                               IngredientAlias, IngredientNutrition)
routes/
  auth.py                     Login, Registrierung, Logout, aktiven Plan wechseln (Blueprint "auth")
  account.py                  Eigenes Profil/Passwort ändern, Konto löschen (Blueprint "account")
  plans.py                    Plan anlegen/umbenennen/löschen (Blueprint "plans")
  sharing.py                  Mitglieder/Einladungen/Stern eines Plans, Plan verlassen (Blueprint "sharing")
  plan/                       Kalender-Wochenansicht, Plan erstellen, Würfeln/Tauschen/manuelle
                               Auswahl, Beilagen, Einkaufsliste (Blueprint "plan", auf drei
                               Dateien verteilt, die sich denselben Blueprint teilen):
    pages.py                    Seiten-Routen (/, /plan/<start>, .../create, .../generate)
    day_actions.py              AJAX: Hauptgericht/Beilagen würfeln/auswählen/verschieben, Tage tauschen
    shopping.py                 AJAX: manuelle Einkaufslisten-Artikel
  recipes.py                  Rezept-CRUD + Rezept-Import + Plan-Verknüpfung (Blueprint "recipes")
  categories.py                Kategorie-CRUD (Blueprint "categories")
  manage.py                    Verwaltungs-Startseite (Blueprint "manage")
  settings.py                  Einheiten- + Zutaten-Gleichsetzung-Einstellungen (Blueprint "settings")
services/
  auth.py                      Login/Session, aktiver Plan, Tab-Auswahl-Helfer (current_plan(),
                                selected_plan_id(), default_plan_id())
  accounts.py                  Eigenes Profil/Passwort ändern, Konto löschen
  plans.py                     Plan-Lebenszyklus (anlegen/löschen, Einladungen annehmen)
  mail.py                      Einladungs-Mail-Versand (aktuell nur geloggt, kein SMTP angebunden)
  recipe_visibility.py         Welche Rezepte für einen Plan sichtbar sind (Eigentümer + Verknüpfungen)
  planning.py                  Wochen-/Datums-Helfer, Kategorie-Balance, Rezeptauswahl,
                                Favoriten-/Wiederholungs-Gewichtung
  seasons.py                   Saison-Zuordnung (Standard-Saisons + eigene Zeiträume)
  shopping.py                  Feste Einkaufslisten-Kategorie-Reihenfolge
  recipe_import.py             Rezept-Import von 9 Kochseiten (schema.org/Recipe-JSON-LD auslesen)
  units.py                     Einheiten-Normalisierung/-Umrechnung (Masse -> g, Volumen -> ml)
  settings.py                  Speicherung der Anzeige-Einheiten-Einstellung (AppSettings)
  ingredient_aliases.py        Zutaten-Gleichsetzung für die Einkaufsliste (IngredientAlias)
templates/                    Jinja2-Templates (Login/Registrierung, Plan-Kalender,
                               Wochenplan erstellen, Verwaltung, Freigabe, Profil)
static/
  plan.js                       Plan-Seite: Zustand, Tageskarten, Hauptgericht, Tages-Tausch
  plan-manual-select.js          Wiederverwendbare Rezeptsuche-Box (Hauptgericht + Beilagen)
  plan-sides.js                  Beilagen: hinzufügen/würfeln/auswählen/entfernen/verschieben
  plan-shopping.js               Wochen-Nährwertübersicht + Einkaufsliste
  create_week.js                Live-Suche & Drag-and-Drop beim Wochenplan-Erstellen
  ingredient_category_select.js Von den Rezept-Formularen gemeinsam genutztes Options-Markup
  bootstrap.*, style.css        Lokales Bootstrap 5 + eigenes Stylesheet
instance/speiseplan.db        SQLite-Datenbank
```

## Lizenz

Veröffentlicht unter der [MIT-Lizenz](LICENSE).
