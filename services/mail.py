"""Mail-Versand für Plan-Einladungen (siehe routes/sharing.py:
invite_member()) - bewusst nur EIN Aufrufpunkt (send_invite_email), damit
sich echter Versand später an genau dieser Stelle nachrüsten lässt, ohne
den Rest der App anzufassen.

Aktuell noch KEIN echter Versand (kein SMTP-Server/keine Zugangsdaten
vorhanden, siehe Klärung mit dem Nutzer) - die Einladung wird stattdessen
geloggt UND direkt auf /manage/sharing angezeigt (siehe
routes/sharing.py: sharing_view(), templates/sharing.html: "Ausstehende
Einladungen"), der Log-Eintrag ist nur die zweite, redundante Fundstelle.
Ein echter Versand später (z.B. per smtplib aus der Standardbibliothek,
keine neue Abhängigkeit nötig) würde ausschließlich den Funktionskörper
hier ersetzen."""

from flask import current_app


def send_invite_email(to_email, plan_name, invite_link):
    current_app.logger.info(
        "Einladung an %s für Plan '%s': %s", to_email, plan_name, invite_link
    )
