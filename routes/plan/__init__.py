"""Der Wochenplan-Kalender: Anzeige, Erstellen und alle Live-Interaktionen
(würfeln, manuell auswählen, tauschen, Beilagen hinzufügen/entfernen/
verschieben, Personenzahl ändern) mit dem dauerhaft in PlanDay/PlanDaySide
gespeicherten Plan.

Dieses Paket ersetzt das frühere einzelne routes/plan.py, das mit der
Zeit auf über 800 Zeilen angewachsen war (Seiten-Routen, Tages-Aktionen,
Beilagen-Aktionen und Einkaufslisten-Aktionen alle in einer Datei) - jetzt
auf drei thematisch getrennte Dateien verteilt, die sich alle DENSELBEN
Blueprint plan_bp teilen (hier definiert, dort per @plan_bp.route(...)
importiert und befüllt):

- pages.py: Seiten-Routen (/, /plan/<start_date>, /plan/<start_date>/create,
  /plan/<start_date>/generate) - liefern ganze HTML-Seiten bzw. leiten weiter.
- day_actions.py: AJAX-Endpunkte für einzelne Kalendertage (Hauptgericht
  würfeln/auswählen, Beilagen hinzufügen/würfeln/auswählen/entfernen/
  verschieben, Personenzahl, Tage tauschen).
- shopping.py: AJAX-Endpunkte für manuell zur Einkaufsliste hinzugefügte
  Posten (ExtraShoppingItem), die zu keinem Rezept gehören.

app.py importiert weiterhin unverändert `from routes.plan import plan_bp` -
dass hier ein Paket statt eines einzelnen Moduls steht, ändert daran (und
an allen `url_for('plan.xxx')`-Aufrufen in den Templates, die weiterhin den
Blueprint-Namen "plan" verwenden) nichts.
"""

from flask import Blueprint

plan_bp = Blueprint('plan', __name__)

# Die Importe hier lösen erst das eigentliche Route-Registrieren aus: jede
# der drei Dateien dekoriert ihre Funktionen mit @plan_bp.route(...), was
# erst beim Ausführen des jeweiligen Moduls passiert. Ohne diese Importe
# (auch wenn plan_bp scheinbar "ungenutzt" aussieht) wären die Routen
# schlicht nicht registriert.
from routes.plan import pages, day_actions, shopping  # noqa: E402,F401
