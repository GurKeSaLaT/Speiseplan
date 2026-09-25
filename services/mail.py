"""Invitation emails. No SMTP is configured yet, so invites are only logged
(and shown on /manage/sharing); real sending would replace this function
body."""

from flask import current_app


def send_invite_email(to_email, plan_name, invite_link):
    current_app.logger.info(
        "Invitation to %s for plan '%s': %s", to_email, plan_name, invite_link
    )
