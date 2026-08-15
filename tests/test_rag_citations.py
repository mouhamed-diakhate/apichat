"""Tests de la propagation déterministe des citations RAG."""

from unittest.mock import MagicMock

from app.intelligence.orchestrator import Assistant
from app.intelligence.providers.base import LLMResponse, ToolCall


def test_assistant_appends_only_retrieved_rag_source() -> None:
    """Une citation est ajoutée par le serveur, même si le LLM l'oublie."""
    provider = MagicMock()
    provider.chat.side_effect = [
        LLMResponse(
            tool_calls=[
                ToolCall(
                    id="tool-rag-1",
                    name="search_faq",
                    arguments={"requete": "Quel est le délai de réclamation ?"},
                )
            ]
        ),
        LLMResponse(text="Vous pouvez émettre votre réclamation dans les 48 heures."),
    ]
    faq = MagicMock()
    faq.search.return_value = [
        {
            "id": "cgv_p006_c001",
            "score": 0.92,
            "reponse": "Le client peut émettre une plainte dans les 48 heures qui suivent la fin de l'opération.",
            "citation": "Conditions générales de vente — Article 11 — p. 6",
            "source": {
                "title": "Conditions générales de vente",
                "filename": "conditions_Generales_de_vente.pdf",
                "page": 6,
                "section": "Article 11",
                "source_type": "document",
            },
        }
    ]

    assistant = Assistant(provider=provider, orders=MagicMock(), faq=faq)
    reply = assistant.handle("Quel est le délai de réclamation ?")

    faq.search.assert_called_once_with("Quel est le délai de réclamation ?", limite=1)
    assert reply.outils_utilises == ["search_faq"]
    assert reply.sources == [
        {
            "id": "cgv_p006_c001",
            "marker": "S1",
            "citation": "Conditions générales de vente — Article 11 — p. 6",
            "document": "Conditions générales de vente",
            "filename": "conditions_Generales_de_vente.pdf",
            "page": 6,
            "section": "Article 11",
            "score": 0.92,
        }
    ]
    assert "Sources vérifiées :" in reply.texte
    assert "[S1] Conditions générales de vente — Article 11 — p. 6" in reply.texte


def test_assistant_does_not_add_citation_when_no_source_exists() -> None:
    """L'absence de résultat documentaire ne peut pas créer une citation fictive."""
    provider = MagicMock()
    provider.chat.side_effect = [
        LLMResponse(
            tool_calls=[
                ToolCall(
                    id="tool-rag-empty",
                    name="search_faq",
                    arguments={"requete": "Information inexistante"},
                )
            ]
        ),
        LLMResponse(text="Je ne dispose pas d'une source fiable pour répondre à cette question."),
    ]
    faq = MagicMock()
    faq.search.return_value = []

    reply = Assistant(provider=provider, orders=MagicMock(), faq=faq).handle("Information inexistante")

    assert reply.sources == []
    assert "Sources vérifiées" not in reply.texte
