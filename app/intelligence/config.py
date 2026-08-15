"""
Assemblage de l'assistant à partir de la configuration (app.core.config).

C'est le SEUL endroit qui décide quels modèles utiliser et dans quel ordre.
Il construit une chaîne FallbackProvider avec les providers disponibles
(= ceux dont la clé API est renseignée dans le .env).

Ordre de priorité des providers :
  1. Groq  — llama-3.3-70b-versatile  (rapide, generalist)
  2. Groq  — qwen-qwq-32b             (raisonnement, même provider)
  3. Gemini — gemini-2.0-flash         (si GEMINI_API_KEY renseignée)
  4. OpenAI — gpt-4o-mini              (si OPENAI_API_KEY renseignée)

En cas de 429 / panne sur un provider, le suivant prend le relais
automatiquement et silencieusement (géré par FallbackProvider).
"""

import logging
from pathlib import Path

from app.core.config import settings
from app.db.session import SessionLocal
from .providers.openai_compatible import OpenAICompatibleProvider
from .providers.fallback_provider import FallbackProvider
from .providers.base import LLMProvider
from .orders import DatabaseOrderSource
from .faq import FaqBase
from .orchestrator import Assistant

logger = logging.getLogger(__name__)

# Dossier "apichat/" (le parent de "app/"), pour retrouver data/
RACINE = Path(__file__).resolve().parent.parent.parent
DOSSIER_DATA = RACINE / "data"

# ─── Définition de TOUS les providers disponibles ────────────────────────────
# Chaque entrée = (nom_log, api_key_ou_None, modele, base_url)
# Les providers sans clé (ou clé vide / placeholder) sont ignorés automatiquement.

_GROQ_URL    = "https://api.groq.com/openai/v1"
_GEMINI_URL  = "https://generativelanguage.googleapis.com/v1beta/openai/"
_OPENAI_URL  = "https://api.openai.com/v1"

_PROVIDER_CHAIN_CONFIG = [
    # ① Groq — Llama 3.3 70B (principal, le plus capable)
    {
        "name":    "groq/llama-3.3-70b",
        "key_env": "GROQ_API_KEY",
        "model":   "llama-3.3-70b-versatile",
        "url":     _GROQ_URL,
    },
    # ② Groq — Qwen3.6 27B (fallback raisonnement)
    {
        "name":    "groq/qwen3.6-27b",
        "key_env": "GROQ_API_KEY",
        "model":   "qwen/qwen3.6-27b",
        "url":     _GROQ_URL,
    },
    # ③ Groq — Llama 3.1 8B (fallback ultra-rapide, même provider)
    {
        "name":    "groq/llama-3.1-8b",
        "key_env": "GROQ_API_KEY",
        "model":   "llama-3.1-8b-instant",
        "url":     _GROQ_URL,
    },
    # ④ Gemini (fallback inter-provider)
    {
        "name":    "gemini/gemini-2.0-flash",
        "key_env": "GEMINI_API_KEY",
        "model":   "gemini-2.0-flash",
        "url":     _GEMINI_URL,
    },
    # ⑤ OpenAI (dernier recours)
    {
        "name":    "openai/gpt-4o-mini",
        "key_env": "OPENAI_API_KEY",
        "model":   "gpt-4o-mini",
        "url":     _OPENAI_URL,
    },
]


def _get_key(key_env: str | None) -> str | None:
    """Retourne la clé API si elle est renseignée et non-vide/placeholder."""
    if not key_env:
        return None
    val = getattr(settings, key_env, "") or ""
    if not val or val.startswith("votre_") or val.startswith("sk-xxx"):
        return None
    return val


def _construire_provider() -> LLMProvider:
    """
    Construit la chaîne FallbackProvider en ne retenant que les providers
    dont la clé API est disponible dans le .env.

    Retourne un FallbackProvider si plusieurs providers sont disponibles,
    ou directement un OpenAICompatibleProvider si un seul est configuré.
    """
    providers: list[OpenAICompatibleProvider] = []
    names: list[str] = []
    skipped: list[str] = []

    for conf in _PROVIDER_CHAIN_CONFIG:
        key = _get_key(conf["key_env"])
        if key is None:
            skipped.append(conf["name"])
            continue
        providers.append(
            OpenAICompatibleProvider(
                api_key=key,
                model=conf["model"],
                base_url=conf["url"],
                name=conf["name"],
            )
        )
        names.append(conf["name"])

    if not providers:
        raise RuntimeError(
            "Aucun provider LLM disponible. Renseignez au moins GROQ_API_KEY, "
            "GEMINI_API_KEY ou OPENAI_API_KEY dans le fichier .env."
        )

    if skipped:
        logger.info(f"[FallbackProvider] Providers ignorés (clé manquante) : {', '.join(skipped)}")
    logger.info(f"[FallbackProvider] Chaîne active : {' → '.join(names)}")

    if len(providers) == 1:
        return providers[0]

    return FallbackProvider(providers=providers, provider_names=names)


def build_assistant(language: str = "fr") -> Assistant:
    """Charge la config, les données, et renvoie un Assistant prêt à l'emploi.

    Args:
        language: Code de langue ('fr', 'en', 'wo'). Détermine quelle base
                  FAQ est chargée. Fallback automatique sur FR si le fichier
                  de langue n'existe pas.
    """
    provider = _construire_provider()
    # Source des commandes issue de la base de données PostgreSQL
    orders = DatabaseOrderSource(SessionLocal)

    # Charger la FAQ dans la langue demandée, avec fallback sur FR
    faq_file = DOSSIER_DATA / f"faq.{language}.json"
    if not faq_file.exists():
        faq_file = DOSSIER_DATA / "faq.fr.json"

    faq = FaqBase(
        faq_file,
        data_dir=DOSSIER_DATA,
        index_dir=DOSSIER_DATA / ".rag" / f"knowledge_{language}",
        allow_remote_model_download=settings.RAG_ALLOW_REMOTE_MODEL_DOWNLOAD,
    )
    return Assistant(provider=provider, orders=orders, faq=faq)
