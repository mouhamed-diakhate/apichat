"""Persistance durable des messages entrants et sortants.

Le tableau de bord s'appuie sur ces enregistrements pour afficher une
conversation dès la réception du premier message client, même si le traitement
IA ou l'envoi de la réponse échoue ensuite.
"""
from __future__ import annotations

import json
import logging
from uuid import uuid4

from sqlalchemy.orm import Session

from app.models.chat import ChatMessage
from app.models.user import User


GUEST_EMAIL = "invite@texmiles.sn"
logger = logging.getLogger("conversation_capture")


def resolve_session_id(session_id: str | None, *, channel: str = "web") -> str:
    """Retourne un identifiant de conversation non vide, borné à la colonne SQL."""
    candidate = (session_id or "").strip()
    if candidate:
        return candidate[:100]
    return f"{channel}_{uuid4().hex}"


def get_or_create_guest_user(db: Session) -> User:
    """Retourne le compte technique associé aux visiteurs Web anonymes."""
    guest_user = db.query(User).filter(User.email == GUEST_EMAIL).first()
    if guest_user:
        return guest_user

    guest_user = User(
        email=GUEST_EMAIL,
        hashed_password="guest_no_login",
        full_name="Visiteur Invité",
        is_active=True,
        is_superuser=False,
    )
    db.add(guest_user)
    db.commit()
    db.refresh(guest_user)
    return guest_user


def get_or_create_whatsapp_user(db: Session, sender_phone: str) -> User:
    """Retourne le client technique correspondant à un numéro WhatsApp."""
    email = f"wa_{sender_phone}@texmiles.sn"
    wa_user = db.query(User).filter(User.email == email).first()
    if wa_user:
        return wa_user

    wa_user = User(
        email=email,
        hashed_password="whatsapp_user",
        full_name=f"Client WhatsApp +{sender_phone}",
        is_active=True,
    )
    db.add(wa_user)
    db.commit()
    db.refresh(wa_user)
    return wa_user


def capture_inbound_message(
    db: Session,
    *,
    user: User,
    content: str,
    session_id: str,
    intent: str = "general",
    language: str = "fr",
) -> ChatMessage | None:
    """Enregistre immédiatement un message client dans sa propre transaction.

    Un appel IA ultérieur ne peut donc jamais annuler cette capture par un
    ``rollback``. Les métadonnées (intention, ticket, escalade) sont enrichies
    après le traitement lorsque celui-ci aboutit.
    """
    text = (content or "").strip()
    if not text:
        return None

    message = ChatMessage(
        user_id=user.id,
        role="user",
        content=text,
        intent=intent,
        language=language,
        session_id=session_id,
    )
    db.add(message)
    db.commit()
    db.refresh(message)
    return message


def enrich_inbound_message(
    db: Session,
    message: ChatMessage | None,
    *,
    intent: str | None = None,
    language: str | None = None,
    escalade: bool | None = None,
    raison_escalade: str | None = None,
    ticket_id: str | None = None,
) -> None:
    """Complète le message entrant sans remettre en cause sa capture initiale."""
    if message is None:
        return

    if intent:
        message.intent = intent
    if language:
        message.language = language
    if escalade is not None:
        message.escalade = escalade
    message.raison_escalade = raison_escalade
    message.ticket_id = ticket_id
    db.commit()
    db.refresh(message)

    # Ce point est commun aux canaux Web, Meta et Evolution. L'alerte est
    # creee uniquement apres que l'escalade du message client soit durable.
    # Le service est idempotent et isole ses propres erreurs : une alerte en
    # panne ne doit jamais faire echouer la reponse au client.
    if escalade is True and message.role == "user":
        try:
            from app.services.notification_service import create_escalation_notifications

            create_escalation_notifications(db, message)
        except Exception:
            db.rollback()
            logger.exception("Impossible de notifier les agents de l'escalade")


def capture_assistant_message(
    db: Session,
    *,
    user: User,
    content: str,
    session_id: str | None,
    intent: str | None = None,
    language: str | None = None,
    escalade: bool | None = None,
    raison_escalade: str | None = None,
    ticket_id: str | None = None,
    outils_utilises: list[str] | None = None,
    sources: list[dict] | None = None,
) -> ChatMessage:
    """Enregistre la réponse dans une transaction distincte du message client."""
    message = ChatMessage(
        user_id=user.id,
        role="assistant",
        content=content or "",
        intent=intent,
        language=language,
        escalade=escalade,
        raison_escalade=raison_escalade,
        ticket_id=ticket_id,
        outils_utilises=json.dumps(outils_utilises) if outils_utilises else None,
        sources_utilisees=json.dumps(sources, ensure_ascii=False) if sources else None,
        session_id=session_id,
    )
    db.add(message)
    db.commit()
    db.refresh(message)
    return message
