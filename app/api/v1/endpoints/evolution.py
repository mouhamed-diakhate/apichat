"""Webhook des messages entrants Evolution API v2."""
import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

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


logger = logging.getLogger("evolution_endpoint")
router = APIRouter()


def _phone_from_evolution_identifier(value: object) -> str:
    """Extrait le numéro d'un JID Evolution sans conserver son suffixe device."""
    local_part = str(value or "").strip().split("@", 1)[0].split(":", 1)[0]
    return "".join(char for char in local_part if char.isdigit())


def _is_phone_identifier(value: object) -> bool:
    """Indique si un identifiant représente un téléphone plutôt qu'un LID."""
    identifier = str(value or "").strip().lower()
    if not identifier or "@lid" in identifier:
        return False
    if "@" not in identifier:
        return bool(_phone_from_evolution_identifier(identifier))
    domain = identifier.rsplit("@", 1)[1]
    return domain in {"s.whatsapp.net", "c.us"}


def _extract_sender_phone(data: dict[str, Any], key: dict[str, Any]) -> str:
    """Résout le numéro réel d'un expéditeur, y compris les conversations LID.

    Avec Baileys, ``remoteJid`` peut être un identifiant interne ``@lid``.
    Evolution fournit alors normalement ``remoteJidAlt`` ou ``senderPn`` avec
    le JID du téléphone réel. Il faut impérativement le préférer : l'API
    d'envoi refuse un LID utilisé comme numéro WhatsApp.
    """
    remote_jid = key.get("remoteJid")
    # Dans une discussion classique, remoteJid est déjà le téléphone : il est
    # plus fiable que les champs secondaires et doit rester prioritaire.
    if _is_phone_identifier(remote_jid):
        return _phone_from_evolution_identifier(remote_jid)

    candidates = (
        key.get("remoteJidAlt"),
        data.get("remoteJidAlt"),
        key.get("senderPn"),
        data.get("senderPn"),
    )
    for candidate in candidates:
        if not _is_phone_identifier(candidate):
            continue
        phone = _phone_from_evolution_identifier(candidate)
        if phone:
            return phone
    return ""


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
        logger.exception("Impossible de mettre a jour le message entrant Evolution")


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
        logger.exception("Echec d'envoi de la reponse Evolution")
        return False


def _handle_inbound_message(
    db: Session,
    *,
    sender_phone: str,
    user_text: str,
    action_id: str | None,
) -> None:
    """Commite le message client avant l'IA ou tout envoi sortant."""
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
        logger.exception("Echec de capture du message Evolution entrant")

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

        if not _send_menu_response(sender_phone, response):
            return
        try:
            if wa_user is None:
                wa_user = get_or_create_whatsapp_user(db, sender_phone)
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
        except Exception:
            db.rollback()
            logger.exception("Echec de sauvegarde de la reponse Evolution guidee")
        return

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
        logger.exception("Echec de sauvegarde de la session Evolution")

    intent = session.selected_service or "general"
    if intent == "general" and reply.outils_utilises:
        tool_map = {
            "search_faq": "faq",
            "lookup_order": "tracking",
            "create_quotation": "quotation",
            "create_operation": "operation",
            "create_complaint": "claim",
        }
        intent = next((tool_map[tool] for tool in reply.outils_utilises if tool in tool_map), intent)
    if intent == "general" and user_text and len(user_text.strip()) > 3:
        try:
            intent = ai_service.detect_intent(user_text)
        except Exception:
            logger.exception("Echec de detection d'intention Evolution")

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
        logger.exception("Echec d'envoi de la reponse IA Evolution")
        return
    if sent is False:
        logger.warning("La reponse IA Evolution n'a pas ete envoyee")
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
        logger.exception("Echec de sauvegarde de la reponse IA Evolution")


@router.post("/webhook", summary="Reception des messages entrants Evolution API")
async def receive_evolution_webhook(request: Request, db: Session = Depends(get_db)):
    """Recoit un evenement messages.upsert en provenance d'Evolution API."""
    try:
        body: dict[str, Any] = await request.json()
    except Exception:
        return {"status": "ok"}

    event = body.get("event") or body.get("type")
    data = body.get("data") or {}
    if event not in ("messages.upsert", "MESSAGES_UPSERT", "SEND_MESSAGE", "messages-upsert"):
        return {"status": "ok", "ignored": "event_type"}

    key = data.get("key", {})
    if key.get("fromMe", False):
        return {"status": "ok", "ignored": "from_me"}

    remote_jid = key.get("remoteJid", "")
    if "@g.us" in remote_jid:
        return {"status": "ok", "ignored": "group"}

    sender_phone = _extract_sender_phone(data, key)
    if not sender_phone:
        if "@lid" in remote_jid.lower():
            logger.warning("Message Evolution ignore : LID sans numero alternatif exploitable")
            return {"status": "ok", "ignored": "unresolved_lid"}
        return {"status": "ok", "ignored": "no_phone"}

    message_obj = data.get("message") or {}
    user_text = ""
    action_id = None
    if "conversation" in message_obj:
        user_text = message_obj.get("conversation", "").strip()
    elif "extendedTextMessage" in message_obj:
        user_text = message_obj.get("extendedTextMessage", {}).get("text", "").strip()
    elif "buttonsResponseMessage" in message_obj:
        button = message_obj.get("buttonsResponseMessage", {})
        action_id = button.get("selectedButtonId")
        user_text = button.get("selectedDisplayText", "")
    elif "listResponseMessage" in message_obj:
        list_response = message_obj.get("listResponseMessage", {})
        selection = list_response.get("singleSelectReply", {})
        action_id = selection.get("selectedRowId") or selection.get("id")
        user_text = selection.get("title") or list_response.get("title", "")
    elif "interactiveResponseMessage" in message_obj:
        # Certaines versions Evolution encapsulent les clics dans un flow natif.
        native_response = (
            message_obj.get("interactiveResponseMessage", {})
            .get("nativeFlowResponseMessage", {})
        )
        try:
            selection = json.loads(native_response.get("paramsJson") or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            selection = {}
        action_id = (
            selection.get("id")
            or selection.get("selectedId")
            or selection.get("selectedRowId")
            or selection.get("selected_row_id")
            or selection.get("rowId")
            or selection.get("row_id")
        )
        user_text = (
            selection.get("title")
            or selection.get("displayText")
            or selection.get("selectedDisplayText")
            or ""
        )

    if not user_text and not action_id:
        return {"status": "ok", "ignored": "empty_content"}

    _handle_inbound_message(
        db,
        sender_phone=sender_phone,
        user_text=user_text,
        action_id=action_id,
    )
    return {"status": "ok"}
