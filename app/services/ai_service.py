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
import re
import threading

from app.intelligence.config import build_assistant
from app.intelligence.orchestrator import Assistant, AssistantReply, MESSAGE_REPLI

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Classification d'intention SANS appel API
# ---------------------------------------------------------------------------
# Mots-clés par intention. L'ordre compte : on teste les intentions spécifiques
# avant les générales pour éviter les faux positifs.
_INTENT_PATTERNS: list[tuple[str, list[str]]] = [
    ("tracking",  [r"\bcmd\b", r"\bcmd\d+", r"numéro de commande", r"suivi", r"tracking", r"status", r"suivre mon colis", r"où est mon colis", r"état de la commande"]),
    ("claim",     [r"réclamation", r"plainte", r"endommagé", r"perdu", r"manquant", r"rembours", r"retour", r"claim", r"damaged", r"lost"]),
    ("satisfaction", [r"satisf", r"avis", r"merci", r"bravo", r"nul", r"déçu", r"excellent", r"feedback"]),
    ("human",     [r"agent", r"humain", r"personne", r"conseiller", r"opérateur", r"human", r"speak to"]),
    ("faq",       [r"horaire", r"délai", r"zone", r"tarif", r"prix", r"frais", r"paiement", r"retrait", r"fonctionn", r"comment", r"how", r"what", r"livraison", r"colis", r"expédition"]),
    ("general",   []),  # fallback
]


def _detect_intent_local(message: str) -> str:
    """Classifie l'intention localement via regex, sans appel API."""
    text = message.lower()
    for intent, patterns in _INTENT_PATTERNS:
        if not patterns:  # fallback
            return intent
        if any(re.search(p, text) for p in patterns):
            return intent
    return "general"


def _intent_from_reply(reply: AssistantReply, message: str) -> str:
    """Déduit l'intention depuis les métadonnées de la réponse (outils utilisés) +
    classification locale si aucun outil n'a été utilisé."""
    tool_intent_map = {
        "lookup_order":    "tracking",
        "create_complaint": "claim",
        "search_faq":      "faq",
        "escalate_to_human": "human",
        "create_quotation": "quotation",
        "create_operation": "operation",
    }
    for tool in (reply.outils_utilises or []):
        if tool in tool_intent_map:
            return tool_intent_map[tool]
    return _detect_intent_local(message)


class AIService:
    """Façade appelée par les endpoints : détection d'intention + orchestrateur.

    Le moteur est construit PARESSEUSEMENT (à la 1re utilisation), pas à l'import.
    Ainsi le serveur démarre même si la clé API n'est pas encore configurée, et les
    tests (qui remplacent ces méthodes par des mocks) tournent sans aucune clé.
    Un assistant est mis en cache PAR LANGUE pour servir la bonne FAQ sans reconstruction.
    """

    def __init__(self) -> None:
        self._assistants: dict = {}  # cache {langue: Assistant}
        self._assistants_lock = threading.RLock()

    def _ensure(self, language: str = "fr") -> None:
        self._get_assistant(language)

    def _get_assistant(self, language: str) -> Assistant:
        """Retourne une instance cohérente même pendant une invalidation FAQ."""
        with self._assistants_lock:
            assistant = self._assistants.get(language)
            if assistant is None:
                assistant = build_assistant(language=language)
                self._assistants[language] = assistant
            return assistant

    def invalidate_knowledge_cache(self) -> None:
        """Force la reconstruction de FAQ et de l'index RAG au prochain message.

        Toutes les langues sont retirées, car celles sans fichier dédié utilisent
        ``faq.fr.json`` comme source de repli. L'index vectoriel persistant est
        lui-même invalidé par son empreinte dès que la FAQ a changé.
        """
        with self._assistants_lock:
            self._assistants.clear()

    @property
    def provider(self):
        return self._get_assistant("fr").provider

    def detect_intent(self, message: str) -> str:
        """Classe le message via regex locale — aucun appel API, jamais bloquant."""
        return _detect_intent_local(message)

    def process_message(
        self,
        message: str,
        history: list[dict],
        language: str = "fr",
        session_id: str | None = None,
    ) -> AssistantReply:
        """Fait traiter le message par l'orchestrateur IA dans la bonne langue (avec A/B testing)."""
        try:
            assistant = self._get_assistant(language)
        except Exception as e:
            # Erreur de configuration (ex. clé API manquante) : on répond proprement
            # au lieu de laisser planter l'API.
            logger.error(f"Impossible de construire le moteur IA : {e}")
            return AssistantReply(
                texte=MESSAGE_REPLI,
                escalade=True,
                raison_escalade="configuration IA indisponible",
            )
        return assistant.handle(
            message,
            history,
            language=language,
            session_id=session_id,
        )

    def process_message_with_intent(
        self,
        message: str,
        history: list[dict],
        language: str = "fr",
        session_id: str | None = None,
    ) -> tuple[AssistantReply, str]:
        """Retourne (reply, intent) en UN SEUL appel au LLM.

        L'intention est déduite des outils utilisés par l'orchestrateur
        (plus précis que la regex pure) puis affinée localement si besoin.
        Utiliser cette méthode dans les endpoints pour éviter le double appel API.
        """
        reply = self.process_message(message, history, language=language, session_id=session_id)
        intent = _intent_from_reply(reply, message)
        return reply, intent



# Instance globale du service (le moteur lui-même est construit à la 1re utilisation).
ai_service = AIService()
