"""
Assemblage de l'assistant à partir de la configuration (app.core.config).

C'est le SEUL endroit qui décide quel modèle utiliser. Tous les fournisseurs listés
ci-dessous parlent une API "compatible OpenAI" : on les gère donc avec la MÊME classe
(OpenAICompatibleProvider), en changeant seulement l'adresse du serveur et la clé.
Ajouter un fournisseur = ajouter une ligne dans le dictionnaire FOURNISSEURS.
"""

from pathlib import Path

from app.core.config import settings
from app.db.session import SessionLocal
from .providers.openai_compatible import OpenAICompatibleProvider
from .orders import DatabaseOrderSource, MockOrderSource
from .faq import FaqBase
from .orchestrator import Assistant

# Dossier "apichat/" (le parent de "app/"), pour retrouver data/
RACINE = Path(__file__).resolve().parent.parent.parent
DOSSIER_DATA = RACINE / "data"

# Catalogue des fournisseurs compatibles OpenAI.
FOURNISSEURS = {
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "cle_env": "GROQ_API_KEY",
        "modele_defaut": "llama-3.1-8b-instant",
    },
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "cle_env": "GEMINI_API_KEY",
        "modele_defaut": "gemini-2.0-flash",
    },
    "grok": {
        "base_url": "https://api.x.ai/v1",
        "cle_env": "XAI_API_KEY",
        "modele_defaut": "grok-3",
    },
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "cle_env": "OPENAI_API_KEY",
        "modele_defaut": "gpt-4o-mini",
    },
    "ollama": {
        "base_url": settings.OLLAMA_BASE_URL,
        "cle_env": None,
        "modele_defaut": settings.OLLAMA_MODEL,
    },
}

def _construire_provider():
    nom = settings.AI_PROVIDER.lower()
    conf = FOURNISSEURS.get(nom)
    if conf is None:
        dispo = ", ".join(FOURNISSEURS)
        raise RuntimeError(f"Fournisseur LLM inconnu : '{nom}'. Valeurs supportées : {dispo}.")

    if conf["cle_env"]:
        cle = getattr(settings, conf["cle_env"], "")
        if not cle or cle.startswith("votre_"):
            raise RuntimeError(
                f"Clé API manquante pour '{nom}'. Renseignez {conf['cle_env']} dans le fichier .env."
            )
    else:
        cle = "ollama" # fallback key for local

    modele = settings.MODEL or conf["modele_defaut"]
    return OpenAICompatibleProvider(api_key=cle, model=modele, base_url=conf["base_url"])


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

    faq = FaqBase(str(faq_file))
    return Assistant(provider=provider, orders=orders, faq=faq)

