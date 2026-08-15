"""
Endpoint Webhook WhatsApp pour Meta Cloud API.
Connecte directement le Meta Cloud API à session_manager.py.
"""

import os
import logging
from typing import Dict, Any
from fastapi import APIRouter, Request, Response, HTTPException, status
from app.services.session_manager import process_interactive_step

logger = logging.getLogger(__name__)
router = APIRouter()

META_VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "texmiles_2026")


@router.get("/webhook", summary="Vérification du Webhook par Meta Cloud API")
async def verify_webhook(request: Request):
    """
    Endpoint obligatoire appelé par Meta lors de la configuration du Webhook.
    """
    params = request.query_params
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")

    if mode == "subscribe" and token == META_VERIFY_TOKEN:
        logger.info("Webhook Meta vérifié avec succès !")
        return Response(content=challenge, media_type="text/plain")
    else:
        logger.warning(f"Échec vérification token Meta : {token}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Token de vérification invalide."
        )


@router.post("/webhook", summary="Réception des messages entrants WhatsApp")
async def handle_whatsapp_webhook(payload: Dict[str, Any]):
    """
    Reçoit les notifications de messages de Meta WhatsApp Cloud API.
    """
    try:
        entries = payload.get("entry", [])
        for entry in entries:
            changes = entry.get("changes", [])
            for change in changes:
                value = change.get("value", {})
                messages = value.get("messages", [])

                for msg in messages:
                    wa_id = msg.get("from")  # Numéro de téléphone WhatsApp du client
                    msg_type = msg.get("type")

                    user_text = ""
                    action_id = None

                    if msg_type == "text":
                        user_text = msg.get("text", {}).get("body", "")
                    elif msg_type == "interactive":
                        # Bouton ou liste cliqué
                        interactive = msg.get("interactive", {})
                        if interactive.get("type") == "button_reply":
                            action_id = interactive.get("button_reply", {}).get("id")
                            user_text = interactive.get("button_reply", {}).get("title", "")
                        elif interactive.get("type") == "list_reply":
                            action_id = interactive.get("list_reply", {}).get("id")
                            user_text = interactive.get("list_reply", {}).get("title", "")

                    if wa_id:
                        # Traiter le message avec le session_manager
                        response, session = process_interactive_step(
                            session_id=wa_id,
                            user_input=user_text,
                            action_id=action_id
                        )
                        logger.info(f"[WhatsApp] Message de {wa_id} | État: {session.state} | Réponse: {response}")
                        # TODO: Envoi vers l'API Meta Cloud via whatsapp_service (quand la clé Meta sera configurée)

        return {"status": "ok"}
    except Exception as e:
        logger.error(f"Erreur lors du traitement du Webhook WhatsApp : {e}")
        return {"status": "error", "detail": str(e)}
