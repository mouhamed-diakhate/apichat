"""Webhook WhatsApp Cloud API (Meta)."""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.models.chat import ChatMessage
from app.models.user import User
from app.services.ai_service import ai_service
from app.services.conversation_capture import (
    capture_assistant_message,
    capture_inbound_message,
    enrich_inbound_message,
    get_or_create_whatsapp_user,
)
from app.services.session_manager import _persist_session, process_interactive_step
from app.services.whatsapp_service import whatsapp_service


logger = logging.getLogger("whatsapp_endpoint")
router = APIRouter()


def _response_text(response: dict) -> str:
    text = response.get("text") or ""
    labels = [button.get("label") for button in response.get("buttons", []) if button.get("label")]
    return f"{text}\n\n" + "\n".join(f"- {label}" for label in labels) if labels else text


def _safe_enrich(
    db: Session,
    inbound: ChatMessage | None,
    *,
    intent: str,
    language: str,
    escalade: bool = False,
    raison_escalade: str | None = None,
    ticket_id: str | None = None,
) -> None:
    try:
        enrich_inbound_message(
            db,
            inbound,
            intent=intent,
            language=language,
            escalade=escalade,
            raison_escalade=raison_escalade,
            ticket_id=ticket_id,
        )
    except Exception:
        db.rollback()
        logger.exception("Impossible de mettre a jour le message entrant WhatsApp")


def _persist_menu_response(
    db: Session,
    *,
    wa_user: User,
    sender_phone: str,
    response: dict,
    intent: str,
    language: str,
    escalade: bool,
    ticket_id: str | None,
) -> None:
    capture_assistant_message(
        db,
        user=wa_user,
        content=_response_text(response),
        session_id=sender_phone,
        intent=intent,
        language=language,
        escalade=escalade,
        raison_escalade="Transmission a un agent humain" if escalade else None,
        ticket_id=ticket_id,
    )


def _send_menu_response(sender_phone: str, response: dict) -> bool:
    try:
        buttons = response.get("buttons", [])
        text = response.get("text", "")
        sent = whatsapp_service.send_options_message(
            sender_phone,
            text,
            buttons,
            presentation=response.get("presentation"),
            title=response.get("menu_title"),
            button_text=response.get("menu_button_text"),
            footer="TexMiles",
        )
        return sent is not False
    except Exception:
        logger.exception("Echec d'envoi de la reponse WhatsApp")
        return False


def _handle_inbound_message(
    db: Session,
    *,
    sender_phone: str,
    user_text: str,
    action_id: str | None,
) -> None:
    """Capture l'entree, puis traite le parcours ou l'IA dans un second temps."""
    wa_user: User | None = None
    inbound: ChatMessage | None = None
    display_message = (user_text or "").strip() or (action_id or "").strip()

    try:
        wa_user = get_or_create_whatsapp_user(db, sender_phone)
        inbound = capture_inbound_message(
            db,
            user=wa_user,
            content=display_message,
            session_id=sender_phone,
            intent="menu",
        )
    except Exception:
        db.rollback()
        logger.exception("Echec de capture du message WhatsApp entrant")

    # db permet de restaurer le parcours apres un redemarrage du service.
    response, session = process_interactive_step(
        session_id=sender_phone,
        user_input=user_text,
        action_id=action_id,
        db=db,
    )
    _persist_session(session, db=db)
    language = session.language or "fr"

    if response is not None:
        intent = response.get("intent") or session.selected_service or "menu"
        ticket_id = response.get("ticket_id") or response.get("reference")
        escalade = bool(response.get("escalade", False))
        _safe_enrich(
            db,
            inbound,
            intent=intent,
            language=language,
            escalade=escalade,
            raison_escalade="Transmission a un agent humain" if escalade else None,
            ticket_id=ticket_id,
        )

        # Si l'envoi echoue, aucune fausse reponse ne masque le message client :
        # le dashboard le conserve alors comme conversation a traiter.
        if not _send_menu_response(sender_phone, response):
            return
        try:
            if wa_user is None:
                wa_user = get_or_create_whatsapp_user(db, sender_phone)
            _persist_menu_response(
                db,
                wa_user=wa_user,
                sender_phone=sender_phone,
                response=response,
                intent=intent,
                language=language,
                escalade=escalade,
                ticket_id=ticket_id,
            )
        except Exception:
            db.rollback()
            logger.exception("Echec de sauvegarde de la reponse WhatsApp guidee")
        return

    # Etat agent actif : le message client est deja commite avant cet appel IA.
    reply = ai_service.process_message(
        message=user_text,
        history=session.history[-10:] if session.history else [],
        language=language,
        session_id=sender_phone,
    )
    session.history.append({"role": "user", "content": user_text})
    session.history.append({"role": "assistant", "content": reply.texte})
    try:
        _persist_session(session, db=db)
    except Exception:
        logger.exception("Echec de sauvegarde de la session WhatsApp")

    intent = session.selected_service or "general"
    if user_text and len(user_text.strip()) > 3:
        try:
            detected = ai_service.detect_intent(user_text)
            if detected != "general" or not session.selected_service:
                intent = detected
        except Exception:
            logger.exception("Echec de detection d'intention WhatsApp")

    _safe_enrich(
        db,
        inbound,
        intent=intent,
        language=language,
        escalade=reply.escalade,
        raison_escalade=reply.raison_escalade,
        ticket_id=reply.ticket_id,
    )

    try:
        sent = whatsapp_service.send_text_message(sender_phone, reply.texte)
    except Exception:
        logger.exception("Echec d'envoi de la reponse IA WhatsApp")
        return
    if sent is False:
        logger.warning("La reponse IA WhatsApp n'a pas ete envoyee")
        return
    try:
        if wa_user is None:
            wa_user = get_or_create_whatsapp_user(db, sender_phone)
        capture_assistant_message(
            db,
            user=wa_user,
            content=reply.texte,
            session_id=sender_phone,
            intent=intent,
            language=language,
            escalade=reply.escalade,
            raison_escalade=reply.raison_escalade,
            ticket_id=reply.ticket_id,
            outils_utilises=reply.outils_utilises,
            sources=reply.sources,
        )
    except Exception:
        db.rollback()
        logger.exception("Echec de sauvegarde de la reponse IA WhatsApp")


@router.get("/webhook", summary="Validation du Webhook par Meta")
def verify_webhook(
    hub_mode: str | None = Query(None, alias="hub.mode"),
    hub_verify_token: str | None = Query(None, alias="hub.verify_token"),
    hub_challenge: str | None = Query(None, alias="hub.challenge"),
):
    """Valide le webhook appele par Meta."""
    if hub_mode == "subscribe" and hub_verify_token == settings.WHATSAPP_VERIFY_TOKEN:
        return Response(content=hub_challenge, media_type="text/plain")
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Token de verification invalide")


@router.post("/webhook", summary="Reception des messages WhatsApp entrants")
async def receive_message(request: Request, db: Session = Depends(get_db)):
    """Capture tous les messages entrants presents dans le lot Meta."""
    try:
        body = await request.json()
    except Exception:
        return {"status": "ok"}

    for entry in body.get("entry", []):
        for change in entry.get("changes", []):
            messages = change.get("value", {}).get("messages", [])
            for msg_data in messages:
                sender_phone = msg_data.get("from")
                if not sender_phone:
                    continue

                user_text = ""
                action_id = None
                if msg_data.get("type") == "text":
                    user_text = msg_data.get("text", {}).get("body", "").strip()
                elif msg_data.get("type") == "interactive":
                    interactive = msg_data.get("interactive", {})
                    button_reply = interactive.get("button_reply", {})
                    list_reply = interactive.get("list_reply", {})
                    selected = button_reply or list_reply
                    action_id = selected.get("id")
                    user_text = selected.get("title", "")

                if not user_text and not action_id:
                    continue
                _handle_inbound_message(
                    db,
                    sender_phone=sender_phone,
                    user_text=user_text,
                    action_id=action_id,
                )

    return {"status": "ok"}
