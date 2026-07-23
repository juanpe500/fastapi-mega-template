"""Email sending. Uses SMTP when SMTP_HOST is configured, otherwise logs the
message to the console so every flow works with zero setup in development.

Sends are dispatched to a worker thread so request handlers don't block.
"""
from __future__ import annotations

import asyncio
import smtplib
from email.message import EmailMessage

from app.config import settings
from app.logging_config import logger


def _send_sync(to: str, subject: str, body: str, html: str | None = None) -> None:
    if not settings.SMTP_HOST:
        logger.info(
            "[email:console] To=%s | Subject=%s\n%s", to, subject, html or body
        )
        return

    msg = EmailMessage()
    msg["From"] = settings.EMAIL_FROM
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    if html:
        msg.add_alternative(html, subtype="html")

    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=20) as server:
        if settings.SMTP_STARTTLS:
            server.starttls()
        if settings.SMTP_USER:
            server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
        server.send_message(msg)
    logger.info("[email:sent] To=%s | Subject=%s", to, subject)


async def send_email(to: str, subject: str, body: str, html: str | None = None) -> None:
    # Skip addresses that hard-bounced or complained. A failed check must never
    # block a send, so it's best-effort.
    try:
        from app.services import suppression

        if await suppression.is_suppressed_email(to):
            logger.info("[email:suppressed] skipped %s (Subject=%s)", to, subject)
            return
    except Exception as exc:  # pragma: no cover
        logger.warning("Suppression check failed for %s: %s", to, exc)

    try:
        await asyncio.to_thread(_send_sync, to, subject, body, html)
    except Exception as exc:  # pragma: no cover — never let email failures 500 a request
        logger.error("Email send failed to %s: %s", to, exc)


def render_email(template: str, **context) -> str:
    """Render an email body from app/templates/emails/ (no request needed)."""
    from app.templating import templates

    tpl = templates.env.get_template(f"emails/{template}")
    return tpl.render(APP_NAME=settings.APP_NAME, BASE_URL=settings.BASE_URL, **context)


# --- convenience wrappers ----------------------------------------------------
async def send_verification_email(to: str, token: str) -> None:
    link = f"{settings.BASE_URL}/verify?token={token}"
    await send_email(
        to,
        f"Verify your {settings.APP_NAME} account",
        f"Confirm your email: {link}",
        html=render_email("verify.html", link=link),
    )


async def send_password_reset_email(to: str, token: str) -> None:
    link = f"{settings.BASE_URL}/reset?token={token}"
    await send_email(
        to,
        f"Reset your {settings.APP_NAME} password",
        f"Reset your password: {link}",
        html=render_email("reset.html", link=link),
    )


async def send_ticket_notification(to: str, ticket_id: str, subject: str) -> None:
    link = f"{settings.BASE_URL}/account/tickets/{ticket_id}"
    await send_email(
        to,
        f"[Support] {subject}",
        f"There's a new reply on your ticket: {link}",
        html=render_email("ticket_reply.html", link=link, subject=subject),
    )
