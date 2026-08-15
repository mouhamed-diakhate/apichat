"""Tests des composants WhatsApp natifs : Démarrer, boutons et listes."""
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.services.evolution_service import EvolutionService
from app.services.whatsapp_service import WhatsAppService


def _service_rows() -> list[dict]:
    return [
        {"id": "service_tracking", "label": "Suivi de commande", "description": "Consulter votre colis"},
        {"id": "service_operation", "label": "Demande d'opération", "description": "Créer une expédition"},
        {"id": "service_quotation", "label": "Demande de cotation", "description": "Obtenir une estimation"},
        {"id": "service_faq", "label": "Questions fréquentes", "description": "Délais et tarifs"},
    ]


def test_evolution_sends_a_native_start_button():
    service = EvolutionService()
    with patch.object(service, "_send_request", return_value=True) as send_request:
        sent = service.send_button_message(
            "+221 77 123 45 67",
            "Bienvenue chez TexMiles",
            [{"id": "menu_start", "label": "Démarrer"}],
        )

    assert sent is True
    url, payload = send_request.call_args.args
    assert url.endswith("/message/sendButtons/TexMiles")
    assert payload["number"] == "221771234567"
    assert payload["buttons"] == [{
        "type": "reply",
        "title": "Démarrer",
        "displayText": "Démarrer",
        "id": "menu_start",
    }]


def test_evolution_sends_services_as_native_list():
    service = EvolutionService()
    with patch.object(service, "_send_request", return_value=True) as send_request:
        sent = service.send_list_message(
            "221771234567",
            "Choisissez un service.",
            _service_rows(),
            title="Services TexMiles",
            button_text="Voir les services",
        )

    assert sent is True
    url, payload = send_request.call_args.args
    assert url.endswith("/message/sendList/TexMiles")
    assert payload["buttonText"] == "Voir les services"
    assert [row["rowId"] for row in payload["sections"][0]["rows"]] == [
        "service_tracking",
        "service_operation",
        "service_quotation",
        "service_faq",
    ]


def test_evolution_uses_the_short_whatsapp_label_for_a_list_row():
    service = EvolutionService()
    rows = [{
        "id": "service_faq",
        "label": "Questions fréquentes (FAQ)",
        "whatsapp_label": "❓ FAQ",
        "description": "Délais et tarifs",
    }]
    with patch.object(service, "_send_request", return_value=True) as send_request:
        service.send_list_message("221771234567", "Choisissez un service.", rows)

    assert send_request.call_args.args[1]["sections"][0]["rows"][0]["title"] == "❓ FAQ"


def test_evolution_uses_a_reliable_text_menu_when_native_is_disabled(monkeypatch):
    monkeypatch.setattr(settings, "WHATSAPP_PROVIDER", "evolution")
    monkeypatch.setattr(settings, "EVOLUTION_INTERACTIVE_ENABLED", False)
    service = WhatsAppService()

    with patch(
        "app.services.evolution_service.evolution_service.send_text_options",
        return_value=True,
    ) as send_text_options:
        sent = service.send_options_message(
            "221771234567",
            "Choisissez un service.",
            _service_rows(),
            presentation="list",
        )

    assert sent is True
    assert send_text_options.call_args.args == (
        "221771234567",
        "Choisissez un service.",
        _service_rows(),
    )


def test_evolution_text_menu_contains_numbered_choices():
    service = EvolutionService()
    with patch.object(service, "_send_request", return_value=True) as send_request:
        sent = service.send_text_options(
            "221771234567",
            "Bienvenue chez TexMiles",
            [{"id": "menu_start", "label": "Démarrer"}],
        )

    assert sent is True
    url, payload = send_request.call_args.args
    assert url.endswith("/message/sendText/TexMiles")
    assert "*1.* Démarrer" in payload["text"]
    assert "Répondez avec le numéro de votre choix" in payload["text"]


def test_meta_uses_a_list_without_losing_the_faq(monkeypatch):
    monkeypatch.setattr(settings, "WHATSAPP_PROVIDER", "meta")
    monkeypatch.setattr(settings, "WHATSAPP_API_TOKEN", "test-token")
    monkeypatch.setattr(settings, "WHATSAPP_PHONE_NUMBER_ID", "test-phone-id")
    service = WhatsAppService()

    with patch.object(service, "_send_request", return_value=True) as send_request:
        sent = service.send_options_message(
            "221771234567",
            "Choisissez un service.",
            _service_rows(),
            presentation="list",
            title="Services TexMiles",
            button_text="Voir les services",
        )

    assert sent is True
    payload = send_request.call_args.args[0]
    assert payload["interactive"]["type"] == "list"
    assert payload["interactive"]["action"]["button"] == "Voir les services"
    assert [row["id"] for row in payload["interactive"]["action"]["sections"][0]["rows"]] == [
        "service_tracking",
        "service_operation",
        "service_quotation",
        "service_faq",
    ]


@patch("app.api.v1.endpoints.whatsapp._handle_inbound_message")
def test_meta_webhook_reads_native_list_reply(mock_handle_inbound):
    client = TestClient(app)
    payload = {
        "entry": [{
            "changes": [{
                "value": {
                    "messages": [{
                        "from": "221771234567",
                        "type": "interactive",
                        "interactive": {
                            "type": "list_reply",
                            "list_reply": {
                                "id": "service_faq",
                                "title": "Questions fréquentes",
                            },
                        },
                    }],
                },
            }],
        }],
    }

    response = client.post("/api/v1/whatsapp/webhook", json=payload)
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert mock_handle_inbound.call_args.kwargs == {
        "sender_phone": "221771234567",
        "user_text": "Questions fréquentes",
        "action_id": "service_faq",
    }
