"""Creation idempotente des notifications d'escalade destinees aux agents."""
from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.models.chat import ChatMessage
from app.models.notification import AgentNotification
from app.models.user import User


logger = logging.getLogger("notification_service")


def _body_for_escalation(message: ChatMessage) -> str:
    """Construit un resume court sans dupliquer toute la conversation."""
    reason = (message.raison_escalade or "Transmission a un agent humain").strip()
    ticket = f" Ticket : {message.ticket_id}." if message.ticket_id else ""
    preview = (message.content or "").strip().replace("\n", " ")[:180]
    message_part = f" Dernier message : {preview}" if preview else ""
    return f"{reason}.{ticket}{message_part}".strip()


def create_escalation_notifications(db: Session, source_message: ChatMessage) -> int:
    """Notifie chaque superviseur actif une seule fois pour un message escalade.

    Les comptes techniques clients WhatsApp et invites ne sont pas admissibles :
    dans le modele actuel, les agents internes sont les comptes actifs avec le
    droit de supervision ``is_superuser``.

    Une erreur de notification ne doit jamais faire echouer le traitement du
    message client. La capture et l'escalade sont deja commit avant cet appel.
    """
    if not source_message.id or source_message.role != "user" or not source_message.escalade:
        return 0

    try:
        agent_ids = [
            user_id
            for (user_id,) in (
                db.query(User.id)
                .filter(User.is_active.is_(True), User.is_superuser.is_(True))
                .all()
            )
        ]
        if not agent_ids:
            return 0

        existing_recipients = {
            recipient_id
            for (recipient_id,) in (
                db.query(AgentNotification.recipient_user_id)
                .filter(
                    AgentNotification.source_message_id == source_message.id,
                    AgentNotification.type == "escalation",
                    AgentNotification.recipient_user_id.in_(agent_ids),
                )
                .all()
            )
        }
        title = "Nouvelle escalade client"
        body = _body_for_escalation(source_message)
        for agent_id in agent_ids:
            if agent_id in existing_recipients:
                continue
            db.add(
                AgentNotification(
                    recipient_user_id=agent_id,
                    source_message_id=source_message.id,
                    type="escalation",
                    title=title,
                    body=body,
                    ticket_id=source_message.ticket_id,
                )
            )
        db.commit()
        return len(set(agent_ids) - existing_recipients)
    except Exception:
        db.rollback()
        logger.exception(
            "Impossible de creer les notifications pour l'escalade du message %s",
            source_message.id,
        )
        return 0
