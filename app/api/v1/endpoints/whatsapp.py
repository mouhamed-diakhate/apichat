"""
Endpoint Webhook WhatsApp Cloud API (Meta).
- GET /api/v1/whatsapp/webhook : Validation du webhook par Meta.
- POST /api/v1/whatsapp/webhook : Réception et traitement des messages WhatsApp entrants.
"""
import json
import logging
from fastapi import APIRouter, Request, Response, Depends, Query, HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.models.user import User
from app.models.chat import ChatMessage
from app.services.session_manager import process_interactive_step
from app.services.ai_service import ai_service
from app.services.whatsapp_service import whatsapp_service

logger = logging.getLogger("whatsapp_endpoint")
router = APIRouter()


@router.get("/webhook", summary="Validation du Webhook par Meta")
def verify_webhook(
    hub_mode: str | None = Query(None, alias="hub.mode"),
    hub_verify_token: str | None = Query(None, alias="hub.verify_token"),
    hub_challenge: str | None = Query(None, alias="hub.challenge"),
):
    """
    Endpoint appelé par Meta lors de la configuration du Webhook.
    Vérifie que hub.verify_token correspond à WHATSAPP_VERIFY_TOKEN.
    """
    expected_token = settings.WHATSAPP_VERIFY_TOKEN
    if hub_mode == "subscribe" and hub_verify_token == expected_token:
        logger.info("[WhatsApp Webhook] Validation réussie par Meta !")
        print(f"[WhatsApp Webhook] Challenge validé avec succès !")
        return Response(content=hub_challenge, media_type="text/plain")

    logger.warning(f"[WhatsApp Webhook] Échec de validation token. Reçu: {hub_verify_token}")
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Token de vérification invalide"
    )


@router.post("/webhook", summary="Réception des messages WhatsApp entrants")
async def receive_message(request: Request, db: Session = Depends(get_db)):
    """
    Répond aux événements envoyés par Meta lorsqu'un utilisateur envoie un message WhatsApp.
    """
    try:
        body = await request.json()
    except Exception:
        return {"status": "ok"}

    # Extraire le message du payload Meta
    entry = body.get("entry", [])
    if not entry:
        return {"status": "ok"}

    changes = entry[0].get("changes", [])
    if not changes:
        return {"status": "ok"}

    value = changes[0].get("value", {})
    messages = value.get("messages", [])

    if not messages:
        return {"status": "ok"}

    msg_data = messages[0]
    sender_phone = msg_data.get("from")  # Numéro de l'expéditeur ex: 221770001122
    msg_type = msg_data.get("type")

    user_text = ""
    action_id = None

    if msg_type == "text":
        user_text = msg_data.get("text", {}).get("body", "").strip()
    elif msg_type == "interactive":
        button_reply = msg_data.get("interactive", {}).get("button_reply", {})
        action_id = button_reply.get("id")
        user_text = button_reply.get("title", "")

    if not sender_phone:
        return {"status": "ok"}

    print(f"\n[WhatsApp Inbound] Message de +{sender_phone} : text='{user_text}', action_id='{action_id}'")

    # 1. Machine à états interactifs (Langue -> Menu -> Agent IA)
    response, session = process_interactive_step(
        session_id=sender_phone,
        user_input=user_text,
        action_id=action_id
    )

    # Si on est encore dans les étapes d'accueil / choix de langue / menu principal
    if response is not None:
        buttons = response.get("buttons", [])
        text = response.get("text", "")
        if buttons:
            whatsapp_service.send_button_message(sender_phone, text, buttons)
        else:
            whatsapp_service.send_text_message(sender_phone, text)
        return {"status": "ok"}

    # 2. Si l'agent IA est actif
    language = session.language or "fr"
    history_list = session.history[-10:] if session.history else []

    reply = ai_service.process_message(
        message=user_text,
        history=history_list,
        language=language
    )

    session.history.append({"role": "user", "content": user_text})
    session.history.append({"role": "assistant", "content": reply.texte})

    # Envoyer la réponse au client sur WhatsApp
    whatsapp_service.send_text_message(sender_phone, reply.texte)

    # Persistance en BD pour le Dashboard
    try:
        wa_user = db.query(User).filter(User.email == f"wa_{sender_phone}@texmiles.sn").first()
        if not wa_user:
            wa_user = User(
                email=f"wa_{sender_phone}@texmiles.sn",
                hashed_password="whatsapp_user",
                full_name=f"Client WhatsApp +{sender_phone}",
                is_active=True
            )
            db.add(wa_user)
            db.commit()
            db.refresh(wa_user)

        intent = session.selected_service or "general"
        if user_text and len(user_text) > 3:
            try:
                intent = ai_service.detect_intent(user_text)
            except Exception:
                pass

        user_msg = ChatMessage(
            user_id=wa_user.id,
            role="user",
            content=user_text,
            intent=intent,
            language=language
        )
        db.add(user_msg)

        outils_json = json.dumps(reply.outils_utilises) if reply.outils_utilises else None
        assistant_msg = ChatMessage(
            user_id=wa_user.id,
            role="assistant",
            content=reply.texte,
            intent=intent,
            language=language,
            escalade=reply.escalade,
            raison_escalade=reply.raison_escalade,
            ticket_id=reply.ticket_id,
            outils_utilises=outils_json
        )
        db.add(assistant_msg)
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error(f"[WhatsApp DB] Erreur de sauvegarde : {e}")

    return {"status": "ok"}
