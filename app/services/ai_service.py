"""
Service central de gestion des appels d'IA et de routage de l'Agent Superviseur.
"""
import json
import logging
from openai import OpenAI

from app.core.config import settings

logger = logging.getLogger(__name__)

SYSTEM_INTENT_PROMPT = """
You are an intent and language classifier for a customer support AI assistant.
Your task is to analyze the user message and output a JSON object containing:
1. "intent": One of the following categories:
   - "faq": questions about company, pricing, FAQ, rules, services, information.
   - "tracking": requests to track a package, order status, order delivery, using keywords like CMD, order number, track.
   - "claim": complaints, refunds, damaged items, return of products, issues with service/order.
   - "satisfaction": feedback, appreciation, expressions of satisfaction or dissatisfaction.
   - "human": requests to speak to a real person, human agent, live support, call support.
   - "general": greetings, chit-chat, thanks, or general queries that don't fit any category.
2. "language": The language code of the message (e.g., "fr" for French, "wo" for Wolof, "en" for English).

You must reply with ONLY a raw JSON block. No markdown, no formatting, no wrapping in ```json ... ```. Just the JSON object.
Example:
{"intent": "general", "language": "fr"}
"""


def parse_json_safely(text: str) -> dict:
    """Extrait et décode le JSON de la réponse du modèle de manière robuste."""
    text = text.strip()
    if text.startswith("```json"):
        text = text[7:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()

    # Recherche les délimiteurs d'un objet JSON
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1:
        text = text[start:end+1]

    try:
        data = json.loads(text)
        # S'assurer que les clés nécessaires sont présentes
        if "intent" not in data:
            data["intent"] = "general"
        if "language" not in data:
            data["language"] = "fr"
        return data
    except Exception as e:
        logger.warning(f"Failed to parse JSON response from LLM: {e}. Raw content: {text}")
        return {"intent": "general", "language": "fr"}


class AIService:
    """Service central unifiant les appels IA et le routage Multi-Agents."""

    def __init__(self) -> None:
        self.provider = settings.AI_PROVIDER
        
        # Configuration du client en fonction du fournisseur choisi
        if self.provider == "ollama":
            # Utilise une clé API si configurée (pour Groq, OpenRouter, etc.), sinon "ollama" par défaut
            api_key = settings.GEMINI_API_KEY or settings.OPENAI_API_KEY or "ollama"
            self.client = OpenAI(
                base_url=settings.OLLAMA_BASE_URL,
                api_key=api_key
            )
            self.model = settings.OLLAMA_MODEL
        elif self.provider == "openai":
            self.client = OpenAI(api_key=settings.OPENAI_API_KEY)
            self.model = "gpt-4o-mini"
        else:
            # Fallback en mode simulé ou autre provider
            self.client = None
            self.model = ""
            logger.warning(f"Provider '{self.provider}' non configuré pour les clients standards. Mode dégradé actif.")

    def detect_intent_and_language(self, message: str) -> dict:
        """Détecte l'intention et la langue de l'utilisateur."""
        if not self.client:
            return {"intent": "general", "language": "fr"}

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": SYSTEM_INTENT_PROMPT},
                    {"role": "user", "content": message}
                ],
                temperature=0.0,
            )
            content = response.choices[0].message.content or ""
            return parse_json_safely(content)
        except Exception as e:
            logger.error(f"Error in intent detection: {e}")
            return {"intent": "general", "language": "fr"}

    def supervisor_route(self, intent: str, message: str, history: list[dict], language: str = "fr") -> str:
        """Route le message vers l'agent adéquat selon l'intention détectée."""
        # Routage vers les agents spécialisés (mockés en Phase 3, implémentés en Phase 4)
        if intent == "tracking":
            return self._mock_tracking_agent(language)
        elif intent == "claim":
            return self._mock_claim_agent(language)
        elif intent == "faq":
            return self._mock_faq_agent(language)
        elif intent == "satisfaction":
            return self._mock_satisfaction_agent(language)
        elif intent == "human":
            return self._mock_human_agent(language)
        else:
            # Agent général / Conversationnel (s'appuie sur le LLM)
            return self._run_general_agent(message, history, language)

    # ---------------------------------------------------------------------------
    # Mocks des Agents Métiers (Sprint 4)
    # ---------------------------------------------------------------------------
    def _mock_tracking_agent(self, language: str) -> str:
        if language == "wo":
            return (
                "🤖 [Agent Suivi Commande] Mangi lay won agent tracking bi. "
                "Bu fekke da nga bëgg topp sa commande, wax ma sa numéro de commande (ex: CMD12345)."
            )
        elif language == "en":
            return (
                "🤖 [Order Tracking Agent] I am the Order Tracking Agent. "
                "To track your order, please provide your order number (e.g., CMD12345)."
            )
        return (
            "🤖 [Agent Suivi de Commande] Je suis l'Agent Suivi de Commande. "
            "Pour suivre votre commande, veuillez me fournir votre numéro de commande (ex: CMD12345)."
        )

    def _mock_claim_agent(self, language: str) -> str:
        if language == "wo":
            return (
                "🤖 [Agent Réclamation] Mangi lay won agent réclamation bi. "
                "Lan mo xew ci sa commande ? (Produit bu yaaqu, commande bu tardé, etc.)"
            )
        elif language == "en":
            return (
                "🤖 [Claim Agent] I am the Claim Agent. "
                "What is the issue with your order? (Damaged product, late delivery, etc.)"
            )
        return (
            "🤖 [Agent Réclamation] Je suis l'Agent Réclamations. "
            "Quel est le problème rencontré avec votre commande (produit endommagé, retard de livraison, etc.) ?"
        )

    def _mock_faq_agent(self, language: str) -> str:
        if language == "wo":
            return (
                "🤖 [Agent FAQ / RAG] Mangi lay won agent FAQ (RAG). "
                "Mën naa la wax ci li ñuy jaayee, sunu politik de retour, ak saa yu ñuy liggéeyee."
            )
        elif language == "en":
            return (
                "🤖 [FAQ / RAG Agent] I am the FAQ Agent (RAG). "
                "I can answer questions about pricing, return policy, and our working hours."
            )
        return (
            "🤖 [Agent FAQ / RAG] Je suis l'Agent FAQ (RAG). "
            "Je peux répondre à vos questions sur nos tarifs, notre politique de retour ou nos horaires."
        )

    def _mock_satisfaction_agent(self, language: str) -> str:
        if language == "wo":
            return "🤖 [Agent Satisfaction] Jërëjëf ci sa wax ! Lii day baax ci liggéey bi."
        elif language == "en":
            return "🤖 [Satisfaction Agent] Thank you for your feedback! It helps us improve our services."
        return "🤖 [Agent Satisfaction] Merci pour votre retour ! Votre avis est précieux pour améliorer nos services."

    def _mock_human_agent(self, language: str) -> str:
        if language == "wo":
            return "🤖 [Escalade Humaine] Mangi lay wutal nit ku lay waxal ci cabinet bi. Xaral tuuti..."
        elif language == "en":
            return "🤖 [Human Escalation] I am transferring you to a human customer representative. Please wait..."
        return "🤖 [Escalade Humaine] Je vous mets en relation directe avec un conseiller humain. Veuillez patienter..."

    # ---------------------------------------------------------------------------
    # Agent Conversationnel Général (LLM)
    # ---------------------------------------------------------------------------
    def _run_general_agent(self, message: str, history: list[dict], language: str) -> str:
        if not self.client:
            return "Service IA indisponible (mode simulé)."

        # Instructions système orientant le comportement
        system_instruction = (
            "Tu es un assistant client bienveillant, professionnel et concis pour la plateforme de e-commerce 'assistant-ia'. "
            "Réponds poliment à l'utilisateur dans sa langue. "
            f"La langue détectée est : {language}. Si c'est le wolof (wo), réponds en Wolof poli et correct. "
            "Si tu ne maîtrises pas le wolof pour cette requête spécifique, excuse-toi poliment en wolof ou en français, "
            "et réponds en français."
        )

        messages = [{"role": "system", "content": system_instruction}]
        
        # Ajout de l'historique récent (limité à 8 messages)
        for msg in history[-8:]:
            messages.append({"role": msg["role"], "content": msg["content"]})
            
        # Message actuel
        messages.append({"role": "user", "content": message})

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.7,
            )
            return response.choices[0].message.content or ""
        except Exception as e:
            logger.error(f"Error in LLM general chat: {e}")
            if language == "wo":
                return "Am na jafe-jafe bu ndaw ci liggéey bi. Jéemalaat ko su weesoo."
            return "Une erreur technique s'est produite. Veuillez réessayer dans quelques instants."


# Instance globale du service
ai_service = AIService()
