"""
Service central : fait le pont entre l'API (endpoints) et le moteur d'intelligence.

Il combine les deux apports du projet :
  1. La DÉTECTION D'INTENTION (héritée de l'agent superviseur) — une classification
     courte du message, utile pour les statistiques du tableau de bord.
  2. L'ORCHESTRATEUR (le "cerveau") — qui traite réellement la demande via des outils
     (suivi de commande, FAQ, réclamation) et applique les garde-fous.

Les deux réutilisent la MÊME connexion au modèle (le provider construit une seule fois),
donc changer de fournisseur dans le .env change tout d'un coup.
"""

import json
import logging

from app.intelligence.config import build_assistant
from app.intelligence.orchestrator import AssistantReply, MESSAGE_REPLI

logger = logging.getLogger(__name__)

# Prompt de classification : renvoie une intention parmi une liste fermée, en JSON brut.
SYSTEM_INTENT_PROMPT = """
You are an intent classifier for a customer support AI assistant.
Analyze the user message and output ONLY a raw JSON object: {"intent": "..."}.
"intent" must be one of:
- "faq": questions about company, pricing, rules, services, delivery info.
- "tracking": order status / tracking (keywords like CMD, order number).
- "claim": complaints, refunds, damaged/missing items, returns.
- "satisfaction": feedback, appreciation or dissatisfaction.
- "human": requests to speak to a real person / human agent.
- "general": greetings, chit-chat, thanks, or anything else.
No markdown, no ```json fences. Just the JSON object. Example: {"intent": "general"}
"""


def parse_intent(text: str) -> str:
    """Extrait l'intention du JSON renvoyé par le modèle, de façon robuste."""
    text = (text or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end != -1:
        text = text[start:end + 1]
    try:
        data = json.loads(text)
        return data.get("intent", "general")
    except Exception as e:
        logger.warning(f"Intent JSON illisible ({e}). Contenu brut : {text!r}")
        return "general"


class AIService:
    """Façade appelée par les endpoints : détection d'intention + orchestrateur.

    Le moteur est construit PARESSEUSEMENT (à la 1re utilisation), pas à l'import.
    Ainsi le serveur démarre même si la clé API n'est pas encore configurée, et les
    tests (qui remplacent ces méthodes par des mocks) tournent sans aucune clé.
    Un assistant est mis en cache PAR LANGUE pour servir la bonne FAQ sans reconstruction.
    """

    def __init__(self) -> None:
        self._assistants: dict = {}  # cache {langue: Assistant}

    def _ensure(self, language: str = "fr") -> None:
        if language not in self._assistants:
            self._assistants[language] = build_assistant(language=language)

    @property
    def provider(self):
        self._ensure()
        return self._assistants["fr"].provider

    def detect_intent(self, message: str) -> str:
        """Classe le message (analytics du tableau de bord). Jamais bloquant."""
        try:
            return parse_intent(self.provider.complete_text(SYSTEM_INTENT_PROMPT, message))
        except Exception as e:
            logger.error(f"Échec détection d'intention : {e}")
            return "general"

    def process_message(self, message: str, history: list[dict], language: str = "fr") -> AssistantReply:
        """Fait traiter le message par l'orchestrateur IA dans la bonne langue."""
        try:
            self._ensure(language=language)
        except Exception as e:
            # Erreur de configuration (ex. clé API manquante) : on répond proprement
            # au lieu de laisser planter l'API.
            logger.error(f"Impossible de construire le moteur IA : {e}")
            return AssistantReply(
                texte=MESSAGE_REPLI,
                escalade=True,
                raison_escalade="configuration IA indisponible",
            )
        return self._assistants[language].handle(message, history, language=language)


# Instance globale du service (le moteur lui-même est construit à la 1re utilisation).
ai_service = AIService()
