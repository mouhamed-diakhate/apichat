"""Envoi de messages WhatsApp texte, boutons rapides et listes natives."""
from __future__ import annotations

import json
import logging
import urllib.request

from app.core.config import settings


logger = logging.getLogger("whatsapp_service")

MAX_REPLY_BUTTONS = 3
MAX_LIST_ROWS = 10


def _short(value: object, limit: int) -> str:
    """Normalise une chaine pour les limites imposees par les APIs WhatsApp."""
    return str(value or "").strip()[:limit]


def _clean_phone(phone: str) -> str:
    return "".join(char for char in str(phone or "") if char.isdigit())


def _option_label(option: dict) -> str:
    """Choisit un libelle court specifique a WhatsApp quand il est fourni."""
    return str(option.get("whatsapp_label") or option.get("label") or "")


class WhatsAppService:
    """Client Meta Cloud API avec delegation optionnelle vers Evolution."""

    @property
    def base_url(self) -> str:
        return f"https://graph.facebook.com/v18.0/{settings.WHATSAPP_PHONE_NUMBER_ID}/messages"

    def send_text_message(self, to: str, text: str) -> bool:
        """Envoie un texte simple au client."""
        if settings.WHATSAPP_PROVIDER.lower() == "evolution":
            from app.services.evolution_service import evolution_service

            return evolution_service.send_text_message(to, text)

        if not settings.WHATSAPP_API_TOKEN or not settings.WHATSAPP_PHONE_NUMBER_ID:
            logger.warning("[WhatsApp] Identifiants Meta absents")
            return False

        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": _clean_phone(to),
            "type": "text",
            "text": {"preview_url": False, "body": text},
        }
        return self._send_request(payload)

    def send_options_message(
        self,
        to: str,
        text: str,
        options: list[dict],
        *,
        presentation: str | None = None,
        title: str | None = None,
        button_text: str | None = None,
        footer: str | None = None,
    ) -> bool:
        """Choisit automatiquement le composant WhatsApp adapte au menu.

        Les reponses rapides sont limitees a trois options. Les menus de langue
        et de services sont donc envoyes sous forme de liste native.
        """
        normalized = [option for option in options if option.get("id") and option.get("label")]
        if not normalized:
            return self.send_text_message(to, text)

        # Evolution/Baileys 2.3.x peut repondre 201/PENDING pour un composant
        # natif tout en ne le livrant sur aucun client WhatsApp. On ne tente
        # donc pas ce format tant qu'il n'a pas ete active explicitement apres
        # validation de la version Evolution installee.
        if (
            settings.WHATSAPP_PROVIDER.lower() == "evolution"
            and not settings.EVOLUTION_INTERACTIVE_ENABLED
        ):
            from app.services.evolution_service import evolution_service

            logger.info("[WhatsApp] Menu texte fiable utilise pour Evolution")
            return evolution_service.send_text_options(to, text, normalized)

        if presentation == "list" or len(normalized) > MAX_REPLY_BUTTONS:
            return self.send_list_message(
                to,
                text,
                normalized,
                title=title,
                button_text=button_text,
                footer=footer,
            )
        return self.send_button_message(to, text, normalized, title=title, footer=footer)

    def send_button_message(
        self,
        to: str,
        text: str,
        buttons: list[dict],
        *,
        title: str | None = None,
        footer: str | None = None,
    ) -> bool:
        """Envoie jusqu'a trois boutons rapides natifs."""
        if len(buttons) > MAX_REPLY_BUTTONS:
            return self.send_list_message(to, text, buttons, title=title, footer=footer)

        if settings.WHATSAPP_PROVIDER.lower() == "evolution":
            from app.services.evolution_service import evolution_service

            return evolution_service.send_button_message(
                to,
                text,
                buttons,
                title=title,
                footer=footer,
            )

        if not settings.WHATSAPP_API_TOKEN or not settings.WHATSAPP_PHONE_NUMBER_ID:
            logger.warning("[WhatsApp] Identifiants Meta absents")
            return False

        formatted_buttons = [
            {
                "type": "reply",
                "reply": {
                    "id": _short(button["id"], 200),
                    "title": _short(_option_label(button), 20),
                },
            }
            for button in buttons[:MAX_REPLY_BUTTONS]
            if button.get("id") and button.get("label")
        ]
        if not formatted_buttons:
            return self.send_text_message(to, text)

        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": _clean_phone(to),
            "type": "interactive",
            "interactive": {
                "type": "button",
                "body": {"text": _short(text, 1024)},
                "action": {"buttons": formatted_buttons},
            },
        }
        return self._send_request(payload)

    def send_list_message(
        self,
        to: str,
        text: str,
        rows: list[dict],
        *,
        title: str | None = None,
        button_text: str | None = None,
        footer: str | None = None,
    ) -> bool:
        """Envoie une liste native : un CTA ouvre les options du service."""
        if settings.WHATSAPP_PROVIDER.lower() == "evolution":
            from app.services.evolution_service import evolution_service

            return evolution_service.send_list_message(
                to,
                text,
                rows,
                title=title,
                button_text=button_text,
                footer=footer,
            )

        if not settings.WHATSAPP_API_TOKEN or not settings.WHATSAPP_PHONE_NUMBER_ID:
            logger.warning("[WhatsApp] Identifiants Meta absents")
            return False

        formatted_rows = []
        for row in rows[:MAX_LIST_ROWS]:
            row_id = _short(row.get("id"), 200)
            row_title = _short(_option_label(row), 24)
            if not row_id or not row_title:
                continue
            item = {"id": row_id, "title": row_title}
            description = _short(row.get("description"), 72)
            if description:
                item["description"] = description
            formatted_rows.append(item)

        if not formatted_rows:
            return self.send_text_message(to, text)

        header = _short(title or "TexMiles", 60)
        section_title = _short(title or "Options", 24)
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": _clean_phone(to),
            "type": "interactive",
            "interactive": {
                "type": "list",
                "header": {"type": "text", "text": header},
                "body": {"text": _short(text, 1024)},
                "footer": {"text": _short(footer or "TexMiles", 60)},
                "action": {
                    "button": _short(button_text or "Voir les options", 20),
                    "sections": [{"title": section_title, "rows": formatted_rows}],
                },
            },
        }
        return self._send_request(payload)

    def send_contact_message(self, to: str, name: str, phone: str) -> bool:
        """Envoie une carte de contact WhatsApp via Meta."""
        if not settings.WHATSAPP_API_TOKEN or not settings.WHATSAPP_PHONE_NUMBER_ID:
            logger.warning("[WhatsApp] Identifiants Meta absents")
            return False

        clean_phone = _clean_phone(phone)
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": _clean_phone(to),
            "type": "contacts",
            "contacts": [{
                "name": {"formatted_name": name, "first_name": name},
                "phones": [{"phone": f"+{clean_phone}", "type": "WORK", "wa_id": clean_phone}],
            }],
        }
        return self._send_request(payload)

    def _send_request(self, payload: dict) -> bool:
        """Execute la requete HTTP POST vers Meta."""
        headers = {
            "Authorization": f"Bearer {settings.WHATSAPP_API_TOKEN}",
            "Content-Type": "application/json",
        }
        request = urllib.request.Request(
            self.base_url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                result = json.loads(response.read().decode("utf-8"))
                logger.info("[WhatsApp Meta] Message envoye a %s: %s", payload.get("to"), result)
                return True
        except Exception as exc:
            logger.error("[WhatsApp Meta] Echec d'envoi a %s: %s", payload.get("to"), exc)
            return False


whatsapp_service = WhatsAppService()
