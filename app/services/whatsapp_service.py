"""
Service WhatsApp Cloud API — Envoi de messages (Texte & Boutons interactifs).
"""
import urllib.request
import json
import logging
from app.core.config import settings

logger = logging.getLogger("whatsapp_service")


class WhatsAppService:
    """Service gérant la communication avec l'API Graph de Meta WhatsApp Cloud API."""

    def __init__(self):
        self.api_token = settings.WHATSAPP_API_TOKEN
        self.phone_number_id = settings.WHATSAPP_PHONE_NUMBER_ID

    @property
    def base_url(self):
        return f"https://graph.facebook.com/v18.0/{settings.WHATSAPP_PHONE_NUMBER_ID}/messages"

    def send_text_message(self, to: str, text: str) -> bool:
        """Envoie un message texte simple à un numéro WhatsApp."""
        token = settings.WHATSAPP_API_TOKEN
        phone_id = settings.WHATSAPP_PHONE_NUMBER_ID
        if not token or not phone_id:
            logger.warning("[WhatsApp] Identifiants WhatsApp manquants dans .env")
            return False

        clean_to = to.replace("+", "").replace(" ", "").strip()

        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": clean_to,
            "type": "text",
            "text": {
                "preview_url": False,
                "body": text
            }
        }

        return self._send_request(payload)

    def send_button_message(self, to: str, text: str, buttons: list[dict]) -> bool:
        """
        Envoie un message interactif avec des boutons cliquables WhatsApp (Max 3 boutons).
        format de buttons: [{'id': 'lang_fr', 'label': 'Français 🇫🇷'}, ...]
        """
        token = settings.WHATSAPP_API_TOKEN
        phone_id = settings.WHATSAPP_PHONE_NUMBER_ID
        if not token or not phone_id:
            logger.warning("[WhatsApp] Identifiants WhatsApp manquants dans .env")
            return False

        clean_to = to.replace("+", "").replace(" ", "").strip()

        formatted_buttons = []
        for btn in buttons[:3]:
            formatted_buttons.append({
                "type": "reply",
                "reply": {
                    "id": btn["id"],
                    "title": btn["label"][:20]  # Max 20 caractères
                }
            })

        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": clean_to,
            "type": "interactive",
            "interactive": {
                "type": "button",
                "body": {
                    "text": text
                },
                "action": {
                    "buttons": formatted_buttons
                }
            }
        }

        return self._send_request(payload)

    def _send_request(self, payload: dict) -> bool:
        """Exécute la requête HTTP POST vers l'API Graph de Meta."""
        token = settings.WHATSAPP_API_TOKEN
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(self.base_url, data=data, headers=headers, method="POST")

        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                logger.info(f"[WhatsApp OK] Message envoyé avec succès : {result}")
                print(f"[WhatsApp OK] Message envoyé avec succès à {payload.get('to')}")
                return True
        except Exception as e:
            logger.error(f"[WhatsApp Erreur] Échec d'envoi Meta API : {e}")
            print(f"[WhatsApp Erreur] {e}")
            return False


# Singleton réutilisable
whatsapp_service = WhatsAppService()
