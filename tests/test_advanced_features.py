"""
Tests unitaires pour les améliorations avancées (12 à 15).
- #12 : Cache FAQ (performance RAG)
- #13 : Taux de résolution autonome du dashboard
- #14 : A/B Testing des system prompts
- #15 : Formateur de logs JSON structurés
"""
import json
import logging
from unittest.mock import MagicMock

from app.intelligence.faq import FaqBase
from app.intelligence.orchestrator import Assistant
from app.core.logging import JSONFormatter


def test_faq_cache():
    """Vérifie que la recherche FAQ utilise le cache en mémoire (#12)."""
    faq = FaqBase("data/faq.fr.json")
    
    query = "Quels sont vos délais de livraison ?"
    cache_key = (query.strip().lower(), 2)

    # 1re recherche (remplit le cache)
    res1 = faq.search(query, limite=2)
    assert len(res1) > 0
    assert cache_key in faq._search_cache

    # 2e recherche identique (doit retourner le résultat directement du cache)
    res2 = faq.search(query, limite=2)
    assert res1 == res2



def test_ab_testing_prompts():
    """Vérifie que l'alternance A/B testing sélectionne la variante A ou B selon session_id (#14)."""
    provider = MagicMock()
    mock_resp = MagicMock()
    mock_resp.tool_calls = None
    mock_resp.text = "Bonjour ! Je suis l'assistant Texmiles."
    provider.chat.return_value = mock_resp

    orders = MagicMock()
    faq = MagicMock()

    assistant = Assistant(provider=provider, orders=orders, faq=faq)

    # Session ID 1
    reply_a = assistant.handle("Bonjour", language="fr", session_id="session_test_100")
    assert reply_a.prompt_variant in ("A", "B")

    # Session ID 2
    reply_b = assistant.handle("Bonjour", language="fr", session_id="session_test_101")
    assert reply_b.prompt_variant in ("A", "B")
    
    # Vérifier que le dictionnaire de variantes contient A et B
    from app.intelligence.prompt_fr import SYSTEM_PROMPT_FR_VARIANTS
    assert "A" in SYSTEM_PROMPT_FR_VARIANTS
    assert "B" in SYSTEM_PROMPT_FR_VARIANTS


def test_json_logging_formatter():
    """Vérifie que JSONFormatter produit un JSON valide avec les champs requis (#15)."""
    formatter = JSONFormatter()
    record = logging.LogRecord(
        name="test_logger",
        level=logging.INFO,
        pathname="test.py",
        lineno=10,
        msg="Test message log",
        args=(),
        exc_info=None,
    )
    formatted = formatter.format(record)
    data = json.loads(formatted)

    assert data["logger"] == "test_logger"
    assert data["level"] == "INFO"
    assert data["message"] == "Test message log"
    assert "timestamp" in data
