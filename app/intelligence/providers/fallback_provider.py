"""
FallbackProvider — Routage multi-modèles avec basculement automatique.

Principe :
  Le FallbackProvider encapsule une LISTE ORDONNÉE de providers LLM.
  Pour chaque appel (chat / complete_text), il tente le provider primaire.
  En cas d'erreur récupérable (429, panne réseau, 5xx), il bascule
  AUTOMATIQUEMENT et SILENCIEUSEMENT vers le suivant dans la liste.

Erreurs qui déclenchent le basculement :
  - openai.RateLimitError         (429 — quota atteint)
  - openai.APIConnectionError     (réseau / timeout)
  - openai.APIStatusError code >= 500 (panne serveur)

Erreurs qui NE déclenchent PAS le basculement :
  - openai.BadRequestError        (requête mal formée → déjà gérée dans OpenAICompatibleProvider)
  - openai.AuthenticationError    (clé invalide → configuration à corriger)
  - Toute autre exception         (propagée telle quelle)

Exemple d'utilisation (voir app/intelligence/config.py) :
  chain = FallbackProvider([
      OpenAICompatibleProvider(groq_key, "llama-3.3-70b-versatile", groq_url),
      OpenAICompatibleProvider(groq_key, "qwen-qwq-32b",            groq_url),
      OpenAICompatibleProvider(gemini_key, "gemini-2.0-flash",      gemini_url),
      OpenAICompatibleProvider(openai_key, "gpt-4o-mini",           openai_url),
  ])
"""

import logging
import time

from openai import RateLimitError, APIConnectionError, APIStatusError, BadRequestError

from .base import LLMProvider, LLMResponse

logger = logging.getLogger(__name__)

# Erreurs qui justifient un basculement vers le provider suivant.
_FALLBACK_EXCEPTIONS = (RateLimitError, APIConnectionError)

# Codes d'erreur BadRequest (400) qui indiquent un modèle mort/indisponible
# et qui doivent aussi déclencher un basculement.
_MODEL_DEAD_CODES = {
    "model_decommissioned",   # Groq : modèle retiré définitivement
    "model_not_found",        # Groq/OpenAI : ID de modèle inconnu
    "model_not_active",       # variante possible
    "unsupported_model",      # variante possible
}


def _is_server_error(exc: Exception) -> bool:
    """Vrai si l'exception est une erreur serveur 5xx (panne temporaire)."""
    if isinstance(exc, APIStatusError):
        return exc.status_code >= 500
    return False


def _is_model_dead(exc: Exception) -> bool:
    """Vrai si l'erreur indique un modèle désactivé ou introuvable.

    Couvre :
      - BadRequestError (400) : model_decommissioned (Groq)
      - NotFoundError   (404) : model_not_found (Groq/OpenAI)
      - APIStatusError  (4xx) avec code modèle mort dans le corps
    """
    from openai import NotFoundError  # import local pour éviter la circularité
    # 404 direct : modèle introuvable
    if isinstance(exc, NotFoundError):
        return True
    if not isinstance(exc, BadRequestError):
        return False
    body = getattr(exc, "body", {}) or {}
    # body peut être un dict ou une chaîne JSON
    if isinstance(body, dict):
        code = body.get("error", {}).get("code", "")
        return code in _MODEL_DEAD_CODES
    # Chercher dans le message texte en dernier recours
    msg = str(exc).lower()
    return any(c in msg for c in _MODEL_DEAD_CODES)


class FallbackProvider(LLMProvider):
    """
    Provider composite qui cascade automatiquement vers les suivants
    en cas d'erreur récupérable.
    """

    def __init__(self, providers: list[LLMProvider], provider_names: list[str] | None = None):
        """
        Args:
            providers:      Liste ordonnée de providers (du plus prioritaire au moins prioritaire).
            provider_names: Noms lisibles pour les logs (ex. ["groq/llama", "groq/qwen", ...]).
                            Si None, les noms sont générés automatiquement.
        """
        if not providers:
            raise ValueError("FallbackProvider nécessite au moins un provider.")
        self._providers = providers
        self._names = provider_names or [
            f"provider_{i}" for i in range(len(providers))
        ]
        # Indique le dernier provider qui a répondu avec succès (pour monitoring).
        self.active_provider_name: str = self._names[0]

    # ------------------------------------------------------------------
    # Interface LLMProvider
    # ------------------------------------------------------------------

    def chat(self, system: str, messages: list[dict], tools=None) -> LLMResponse:
        """Tente chat() sur chaque provider dans l'ordre, avec fallback automatique."""
        return self._call_with_fallback("chat", system=system, messages=messages, tools=tools)

    def complete_text(self, system: str, user: str) -> str:
        """Tente complete_text() sur chaque provider dans l'ordre, avec fallback automatique."""
        result = self._call_with_fallback("complete_text", system=system, user=user)
        # complete_text retourne str, pas LLMResponse
        if isinstance(result, str):
            return result
        return result.text if isinstance(result, LLMResponse) else str(result)

    # ------------------------------------------------------------------
    # Logique de cascade interne
    # ------------------------------------------------------------------

    def _call_with_fallback(self, method: str, **kwargs):
        """
        Appelle `method` sur chaque provider en séquence.
        Lève l'exception du dernier provider si tous échouent.
        """
        last_exc: Exception | None = None

        for idx, provider in enumerate(self._providers):
            name = self._names[idx]
            try:
                if method == "chat":
                    result = provider.chat(
                        system=kwargs["system"],
                        messages=kwargs["messages"],
                        tools=kwargs.get("tools"),
                    )
                    # Annoter la réponse avec le nom du provider actif.
                    if isinstance(result, LLMResponse):
                        result.provider_used = name
                    self.active_provider_name = name
                    if idx > 0:
                        logger.info(
                            f"[FallbackProvider] ✅ Succès sur '{name}' "
                            f"(après {idx} basculement(s))."
                        )
                    return result

                elif method == "complete_text":
                    result = provider.complete_text(
                        system=kwargs["system"],
                        user=kwargs["user"],
                    )
                    self.active_provider_name = name
                    if idx > 0:
                        logger.info(
                            f"[FallbackProvider] ✅ Succès sur '{name}' "
                            f"(après {idx} basculement(s))."
                        )
                    return result

            except _FALLBACK_EXCEPTIONS as exc:
                last_exc = exc
                retry_after = _parse_retry_after(exc)
                next_name = self._names[idx + 1] if idx + 1 < len(self._providers) else None

                if next_name:
                    logger.warning(
                        f"[FallbackProvider] ⚠️  '{name}' → {type(exc).__name__} "
                        f"(429/réseau). Basculement vers '{next_name}'..."
                        + (f" (Retry-After: {retry_after}s ignoré)" if retry_after else "")
                    )
                    # Court délai avant de tenter le provider suivant (évite les bursts).
                    time.sleep(0.3)
                    continue
                else:
                    logger.error(
                        f"[FallbackProvider] ❌ Tous les providers ont échoué. "
                        f"Dernière erreur sur '{name}' : {exc}"
                    )
                    raise

            except Exception as exc:
                if _is_server_error(exc):
                    last_exc = exc
                    next_name = self._names[idx + 1] if idx + 1 < len(self._providers) else None
                    if next_name:
                        logger.warning(
                            f"[FallbackProvider] ⚠️  '{name}' → erreur serveur {getattr(exc, 'status_code', '?')}. "
                            f"Basculement vers '{next_name}'..."
                        )
                        time.sleep(0.5)
                        continue
                if _is_model_dead(exc):
                    last_exc = exc
                    next_name = self._names[idx + 1] if idx + 1 < len(self._providers) else None
                    if next_name:
                        logger.warning(
                            f"[FallbackProvider] ⚠️  '{name}' → modèle désactivé/introuvable. "
                            f"Basculement vers '{next_name}'..."
                        )
                        continue
                    else:
                        logger.error(
                            f"[FallbackProvider] ❌ Modèle '{name}' désactivé et aucun fallback disponible."
                        )
                        raise
                # Erreur non récupérable : on la propage immédiatement.
                raise

        # Ne devrait pas être atteint mais par sécurité.
        if last_exc:
            raise last_exc
        raise RuntimeError("FallbackProvider : aucun provider disponible.")


def _parse_retry_after(exc: Exception) -> float | None:
    """Extrait la valeur Retry-After de l'en-tête si disponible."""
    resp = getattr(exc, "response", None)
    headers = getattr(resp, "headers", {}) or {}
    val = headers.get("retry-after") or headers.get("Retry-After")
    if val:
        try:
            return float(val)
        except (ValueError, TypeError):
            pass
    return None
