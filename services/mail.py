"""Email sending for plan invitations (see routes/sharing.py:
invite_member()) - deliberately just ONE call site (send_invite_email), so
that actual sending can be retrofitted later at exactly this spot, without
touching the rest of the app.

Currently there is NO actual sending yet (no SMTP server/credentials
available, see clarification with the user) - the invitation is instead
logged AND shown directly on /manage/sharing (see routes/sharing.py:
sharing_view(), templates/sharing.html: "Pending invitations"), the log
entry is just the second, redundant place to find it. Actual sending later
(e.g. via smtplib from the standard library, no new dependency needed)
would replace only the function body here."""

from flask import current_app


def send_invite_email(to_email, plan_name, invite_link):
    current_app.logger.info(
        "Invitation to %s for plan '%s': %s", to_email, plan_name, invite_link
    )
