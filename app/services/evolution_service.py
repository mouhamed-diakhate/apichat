"""Client Evolution API v2 pour les messages WhatsApp TexMiles."""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request

from app.core.config import settings


logger = logging.getLogger("evolution_service")


def _clean_phone(phone: str) -> str:
    return "".join(char for char in str(phone or "") if char.isdigit())


def _short(value: object, limit: int) -> str:
    return str(value or "").strip()[:limit]


def _option_label(option: dict) -> str:
    """Choisit un libelle court specifique a WhatsApp quand il est fourni."""
    return str(option.get("whatsapp_label") or option.get("label") or "")


class EvolutionService:
    """Client des endpoints Evolution, avec repli texte si necessaire."""

    @property
    def api_url(self) -> str:
        return settings.EVOLUTION_API_URL.rstrip("/")

    @property
    def instance(self) -> str:
        return settings.EVOLUTION_INSTANCE_NAME

    @property
    def headers(self) -> dict:
        headers = {"Content-Type": "application/json"}
        if settings.EVOLUTION_API_KEY:
            headers["apikey"] = settings.EVOLUTION_API_KEY
        return headers

    def send_text_message(self, to: str, text: str) -> bool:
        """Envoie un texte simple via Evolution API."""
        url = f"{self.api_url}/message/sendText/{self.instance}"
        payload = {
            "number": _clean_phone(to),
            "text": text,
            "delay": 800,
            "linkPreview": False,
        }
        return self._send_request(url, payload)

    def send_button_message(
        self,
        to: str,
        text: str,
        buttons: list[dict],
        *,
        title: str | None = None,
        footer: str | None = None,
    ) -> bool:
        """Envoie jusqu'a trois boutons de reponse natifs Evolution."""
        if len(buttons) > 3:
            return self.send_list_message(to, text, buttons, title=title, footer=footer)

        formatted = []
        for button in buttons[:3]:
            action_id = _short(button.get("id"), 200)
            label = _short(_option_label(button), 20)
            if action_id and label:
                # Evolution v2.3.7 exige explicitement ``type`` pour chaque
                # bouton, sans quoi l'API renvoie 400 et le code bascule sur
                # le menu texte numéroté.
                formatted.append({
                    "type": "reply",
                    "title": label,
                    "displayText": label,
                    "id": action_id,
                })
        if not formatted:
            return self.send_text_message(to, text)

        url = f"{self.api_url}/message/sendButtons/{self.instance}"
        payload = {
            "number": _clean_phone(to),
            "title": _short(title or "TexMiles", 60),
            "description": _short(text, 1024),
            "footer": _short(footer or "TexMiles", 60),
            "buttons": formatted,
            "delay": 800,
            "linkPreview": False,
        }
        if self._send_request(url, payload):
            return True

        logger.warning("[Evolution] Boutons natifs indisponibles, repli en texte")
        return self.send_text_options(to, text, buttons)

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
        """Envoie une liste native avec un bouton ouvrant les services."""
        formatted_rows = []
        for row in rows[:10]:
            row_id = _short(row.get("id"), 200)
            row_title = _short(_option_label(row), 24)
            if not row_id or not row_title:
                continue
            formatted_rows.append({
                "title": row_title,
                "description": _short(row.get("description"), 72),
                "rowId": row_id,
            })
        if not formatted_rows:
            return self.send_text_message(to, text)

        url = f"{self.api_url}/message/sendList/{self.instance}"
        payload = {
            "number": _clean_phone(to),
            "title": _short(title or "TexMiles", 60),
            "description": _short(text, 1024),
            "buttonText": _short(button_text or "Voir les options", 20),
            "footerText": _short(footer or "TexMiles", 60),
            "sections": [{
                "title": _short(title or "Options", 24),
                "rows": formatted_rows,
            }],
            "delay": 800,
        }
        if self._send_request(url, payload):
            return True

        logger.warning("[Evolution] Liste native indisponible, repli en texte")
        return self.send_text_options(to, text, rows)

    def send_text_options(self, to: str, text: str, options: list[dict]) -> bool:
        """Envoie un menu numerote fiable lorsque les composants natifs sont indisponibles."""
        lines = [text, ""]
        for index, option in enumerate(options, 1):
            lines.append(f"*{index}.* {option.get('label', '')}")
        lines.append("\n_Répondez avec le numéro de votre choix._")
        return self.send_text_message(to, "\n".join(lines))

    def _send_request(self, url: str, payload: dict) -> bool:
        """Execute une requete HTTP POST vers Evolution API."""
        try:
            request = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers=self.headers,
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=10) as response:
                result = json.loads(response.read().decode("utf-8"))
                logger.info("[Evolution] Message envoye a %s: %s", payload.get("number"), result)
                return True
        except urllib.error.HTTPError as exc:
            # Le détail renvoyé par Evolution explique notamment pourquoi un
            # composant natif a dû repasser en texte. Il ne contient pas la
            # clé API et reste donc exploitable dans les logs de l'application.
            detail = exc.read().decode("utf-8", "replace")[:1000]
            logger.warning("[Evolution] %s -> HTTP %s: %s", url, exc.code, detail)
            return False
        except Exception as exc:
            logger.warning("[Evolution] %s -> %s", url, exc)
            return False


evolution_service = EvolutionService()
