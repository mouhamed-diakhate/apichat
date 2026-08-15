"""
Tests unitaires pour FallbackProvider.

Vérifie :
  1. Succès sur le provider primaire — retourne la réponse immédiatement.
  2. Basculement sur 429 (RateLimitError) — le provider secondaire est utilisé.
  3. Basculement sur APIConnectionError — le provider secondaire est utilisé.
  4. Basculement sur erreur 5xx (APIStatusError) — le provider secondaire est utilisé.
  5. Tous les providers échouent — l'exception est propagée.
  6. provider_used est correctement renseigné dans LLMResponse.
  7. complete_text bascule également en cas de 429.
"""
from unittest.mock import MagicMock, patch

import pytest
from openai import RateLimitError, APIConnectionError, APIStatusError

from app.intelligence.providers.base import LLMProvider, LLMResponse, ToolCall
from app.intelligence.providers.fallback_provider import FallbackProvider


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _make_provider(name: str, response: LLMResponse | Exception) -> LLMProvider:
    """Crée un provider mock qui retourne `response` ou lève une exception."""
    provider = MagicMock(spec=LLMProvider)
    provider._name = name
    if isinstance(response, Exception):
        provider.chat.side_effect = response
        provider.complete_text.side_effect = response
    else:
        provider.chat.return_value = response
        provider.complete_text.return_value = response.text
    return provider


def _rate_limit_error() -> RateLimitError:
    """Crée un RateLimitError minimal."""
    response_mock = MagicMock()
    response_mock.headers = {}
    response_mock.status_code = 429
    return RateLimitError(
        message="Rate limit exceeded",
        response=response_mock,
        body={"error": {"message": "Rate limit exceeded"}},
    )


def _connection_error() -> APIConnectionError:
    """Crée un APIConnectionError minimal."""
    return APIConnectionError(request=MagicMock())


def _server_error() -> APIStatusError:
    """Crée un APIStatusError 503 minimal."""
    response_mock = MagicMock()
    response_mock.status_code = 503
    response_mock.headers = {}
    return APIStatusError(
        message="Service Unavailable",
        response=response_mock,
        body={"error": {"message": "Service Unavailable"}},
    )


_GOOD_RESPONSE = LLMResponse(text="Bonjour !", tool_calls=[], provider_used="")


# ─── Tests ────────────────────────────────────────────────────────────────────

@patch("app.intelligence.providers.fallback_provider.time.sleep")
def test_primary_success(mock_sleep):
    """Succès sur le provider primaire : pas de basculement."""
    p1 = _make_provider("groq/llama", _GOOD_RESPONSE)
    p2 = _make_provider("groq/qwen", _GOOD_RESPONSE)

    fp = FallbackProvider([p1, p2], ["groq/llama", "groq/qwen"])
    result = fp.chat("system", [{"role": "user", "content": "Salut"}])

    assert result.text == "Bonjour !"
    assert fp.active_provider_name == "groq/llama"
    p1.chat.assert_called_once()
    p2.chat.assert_not_called()
    mock_sleep.assert_not_called()


@patch("app.intelligence.providers.fallback_provider.time.sleep")
def test_fallback_on_rate_limit(mock_sleep):
    """429 sur le primaire → basculement vers le secondaire."""
    p1 = _make_provider("groq/llama", _rate_limit_error())
    p2 = _make_provider("groq/qwen", _GOOD_RESPONSE)

    fp = FallbackProvider([p1, p2], ["groq/llama", "groq/qwen"])
    result = fp.chat("system", [{"role": "user", "content": "Salut"}])

    assert result.text == "Bonjour !"
    assert result.provider_used == "groq/qwen"
    assert fp.active_provider_name == "groq/qwen"
    p1.chat.assert_called_once()
    p2.chat.assert_called_once()
    mock_sleep.assert_called()  # Un délai est ajouté entre les essais


@patch("app.intelligence.providers.fallback_provider.time.sleep")
def test_fallback_on_connection_error(mock_sleep):
    """APIConnectionError sur le primaire → basculement vers le secondaire."""
    p1 = _make_provider("groq/llama", _connection_error())
    p2 = _make_provider("groq/qwen", _GOOD_RESPONSE)

    fp = FallbackProvider([p1, p2], ["groq/llama", "groq/qwen"])
    result = fp.chat("system", [{"role": "user", "content": "Test connexion"}])

    assert result.text == "Bonjour !"
    assert fp.active_provider_name == "groq/qwen"


@patch("app.intelligence.providers.fallback_provider.time.sleep")
def test_fallback_on_server_error(mock_sleep):
    """Erreur 5xx sur le primaire → basculement vers le secondaire."""
    p1 = _make_provider("groq/llama", _server_error())
    p2 = _make_provider("groq/qwen", _GOOD_RESPONSE)

    fp = FallbackProvider([p1, p2], ["groq/llama", "groq/qwen"])
    result = fp.chat("system", [{"role": "user", "content": "Test serveur"}])

    assert result.text == "Bonjour !"
    assert fp.active_provider_name == "groq/qwen"


@patch("app.intelligence.providers.fallback_provider.time.sleep")
def test_all_providers_fail(mock_sleep):
    """Tous les providers échouent → l'exception du dernier est propagée."""
    p1 = _make_provider("groq/llama", _rate_limit_error())
    p2 = _make_provider("groq/qwen", _rate_limit_error())

    fp = FallbackProvider([p1, p2], ["groq/llama", "groq/qwen"])

    with pytest.raises(RateLimitError):
        fp.chat("system", [{"role": "user", "content": "Tous fails"}])

    p1.chat.assert_called_once()
    p2.chat.assert_called_once()


@patch("app.intelligence.providers.fallback_provider.time.sleep")
def test_three_provider_cascade(mock_sleep):
    """Cascade de 3 providers : les deux premiers échouent, le 3e réussit."""
    p1 = _make_provider("groq/llama", _rate_limit_error())
    p2 = _make_provider("groq/qwen", _connection_error())
    p3 = _make_provider("gemini/flash", _GOOD_RESPONSE)

    fp = FallbackProvider([p1, p2, p3], ["groq/llama", "groq/qwen", "gemini/flash"])
    result = fp.chat("system", [{"role": "user", "content": "Cascade"}])

    assert result.text == "Bonjour !"
    assert result.provider_used == "gemini/flash"
    assert fp.active_provider_name == "gemini/flash"
    assert mock_sleep.call_count == 2  # Deux délais ajoutés


@patch("app.intelligence.providers.fallback_provider.time.sleep")
def test_complete_text_fallback(mock_sleep):
    """complete_text bascule également sur 429."""
    p1 = _make_provider("groq/llama", _rate_limit_error())
    p2 = _make_provider("groq/qwen", _GOOD_RESPONSE)

    fp = FallbackProvider([p1, p2], ["groq/llama", "groq/qwen"])
    result = fp.complete_text("system", "Détecte l'intention")

    assert result == "Bonjour !"
    assert fp.active_provider_name == "groq/qwen"


def test_single_provider_no_fallback():
    """Un seul provider disponible : pas besoin de FallbackProvider (mais accepté)."""
    p1 = _make_provider("groq/llama", _GOOD_RESPONSE)
    fp = FallbackProvider([p1], ["groq/llama"])
    result = fp.chat("system", [{"role": "user", "content": "Single"}])
    assert result.text == "Bonjour !"


def test_empty_providers_raises():
    """FallbackProvider sans providers → ValueError à l'initialisation."""
    with pytest.raises(ValueError):
        FallbackProvider([])
