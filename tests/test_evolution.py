"""
Tests unitaires pour l'intégration Evolution API.
"""
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from app.main import app
from app.services.session_manager import get_or_create_session

client = TestClient(app)


def test_evolution_webhook_ignores_from_me():
    """Vérifie que les messages de l'instance elle-même (fromMe: true) sont ignorés."""
    payload = {
        "event": "messages.upsert",
        "instance": "TexMiles",
        "data": {
            "key": {
                "remoteJid": "221770001122@s.whatsapp.net",
                "fromMe": True,
                "id": "123"
            },
            "message": {"conversation": "Message sortant"}
        }
    }
    response = client.post("/api/v1/evolution/webhook", json=payload)
    assert response.status_code == 200
    assert response.json().get("ignored") == "from_me"


def test_evolution_webhook_ignores_groups():
    """Vérifie que les messages de groupes (@g.us) sont ignorés."""
    payload = {
        "event": "messages.upsert",
        "instance": "TexMiles",
        "data": {
            "key": {
                "remoteJid": "123456789@g.us",
                "fromMe": False,
                "id": "123"
            },
            "message": {"conversation": "Hello groupe"}
        }
    }
    response = client.post("/api/v1/evolution/webhook", json=payload)
    assert response.status_code == 200
    assert response.json().get("ignored") == "group"


@patch("app.api.v1.endpoints.evolution._handle_inbound_message")
def test_evolution_webhook_uses_phone_alternative_for_lid(mock_handle_inbound):
    """Un LID WhatsApp doit etre resolu via remoteJidAlt avant tout envoi."""
    payload = {
        "event": "messages.upsert",
        "data": {
            "key": {
                "remoteJid": "257144087683295@lid",
                "remoteJidAlt": "221771234567@s.whatsapp.net",
                "fromMe": False,
                "id": "LID1",
            },
            "message": {"conversation": "Bonjour"},
        },
    }
    response = client.post("/api/v1/evolution/webhook", json=payload)
    assert response.status_code == 200
    assert mock_handle_inbound.call_args.kwargs == {
        "sender_phone": "221771234567",
        "user_text": "Bonjour",
        "action_id": None,
    }


@patch("app.api.v1.endpoints.evolution._handle_inbound_message")
def test_evolution_webhook_uses_sender_pn_when_lid_has_no_alt(mock_handle_inbound):
    """Certaines versions Evolution exposent le téléphone via senderPn."""
    payload = {
        "event": "messages.upsert",
        "data": {
            "key": {
                "remoteJid": "257144087683295@lid",
                "senderPn": "221761234567@s.whatsapp.net",
                "fromMe": False,
                "id": "LID2",
            },
            "message": {"conversation": "Bonjour"},
        },
    }
    response = client.post("/api/v1/evolution/webhook", json=payload)
    assert response.status_code == 200
    assert mock_handle_inbound.call_args.kwargs == {
        "sender_phone": "221761234567",
        "user_text": "Bonjour",
        "action_id": None,
    }


@patch("app.api.v1.endpoints.evolution._handle_inbound_message")
def test_evolution_webhook_keeps_direct_phone_before_alternative(mock_handle_inbound):
    """Un JID téléphone normal est prioritaire sur tout champ secondaire."""
    payload = {
        "event": "messages.upsert",
        "data": {
            "key": {
                "remoteJid": "221771234567:12@s.whatsapp.net",
                "remoteJidAlt": "221700000000@s.whatsapp.net",
                "fromMe": False,
                "id": "PN1",
            },
            "message": {"conversation": "Bonjour"},
        },
    }
    response = client.post("/api/v1/evolution/webhook", json=payload)
    assert response.status_code == 200
    assert mock_handle_inbound.call_args.kwargs["sender_phone"] == "221771234567"


@patch("app.api.v1.endpoints.evolution._handle_inbound_message")
def test_evolution_webhook_ignores_lid_without_phone_mapping(mock_handle_inbound):
    """Ne jamais tenter d'envoyer une réponse vers un identifiant LID brut."""
    payload = {
        "event": "messages.upsert",
        "data": {
            "key": {
                "remoteJid": "257144087683295@lid",
                "fromMe": False,
                "id": "LID3",
            },
            "message": {"conversation": "Bonjour"},
        },
    }
    response = client.post("/api/v1/evolution/webhook", json=payload)
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "ignored": "unresolved_lid"}
    mock_handle_inbound.assert_not_called()


@patch("app.api.v1.endpoints.evolution._handle_inbound_message")
def test_evolution_webhook_ignores_non_phone_jid(mock_handle_inbound):
    """Un JID de diffusion ne doit jamais être transformé en téléphone."""
    payload = {
        "event": "messages.upsert",
        "data": {
            "key": {
                "remoteJid": "1781870949@broadcast",
                "fromMe": False,
                "id": "BROADCAST1",
            },
            "message": {"conversation": "Bonjour"},
        },
    }
    response = client.post("/api/v1/evolution/webhook", json=payload)
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "ignored": "no_phone"}
    mock_handle_inbound.assert_not_called()


@patch("app.api.v1.endpoints.evolution.whatsapp_service.send_options_message")
def test_evolution_webhook_valid_message(mock_send_options):
    """Vérifie le traitement d'un message entrant valide via Evolution API."""
    mock_send_options.return_value = True
    # Ce module partage le cache de sessions avec les autres tests : repartir
    # explicitement de l'accueil évite qu'un ancien état AGENT_ACTIVE invoque
    # le fournisseur IA au lieu du menu WhatsApp.
    get_or_create_session("221770001122").reset()
    payload = {
        "event": "messages.upsert",
        "instance": "TexMiles",
        "data": {
            "key": {
                "remoteJid": "221770001122@s.whatsapp.net",
                "fromMe": False,
                "id": "MSG1"
            },
            "pushName": "Mamadou",
            "message": {"conversation": "Bonjour"}
        }
    }
    response = client.post("/api/v1/evolution/webhook", json=payload)
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    mock_send_options.assert_called_once()


@patch("app.api.v1.endpoints.evolution._handle_inbound_message")
def test_evolution_webhook_reads_native_list_reply(mock_handle_inbound):
    """Une ligne selectionnee dans une liste conserve son ID de service."""
    payload = {
        "event": "messages.upsert",
        "data": {
            "key": {
                "remoteJid": "221770001122@s.whatsapp.net",
                "fromMe": False,
                "id": "LIST1",
            },
            "message": {
                "listResponseMessage": {
                    "singleSelectReply": {
                        "selectedRowId": "service_faq",
                        "title": "Questions frequentes",
                    }
                }
            },
        },
    }
    response = client.post("/api/v1/evolution/webhook", json=payload)
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert mock_handle_inbound.call_args.kwargs == {
        "sender_phone": "221770001122",
        "user_text": "Questions frequentes",
        "action_id": "service_faq",
    }


@patch("app.api.v1.endpoints.evolution._handle_inbound_message")
def test_evolution_webhook_reads_native_flow_list_reply(mock_handle_inbound):
    """Les clients recents peuvent encapsuler la selection dans un native flow."""
    payload = {
        "event": "messages.upsert",
        "data": {
            "key": {
                "remoteJid": "221770001122@s.whatsapp.net",
                "fromMe": False,
                "id": "FLOW1",
            },
            "message": {
                "interactiveResponseMessage": {
                    "nativeFlowResponseMessage": {
                        "paramsJson": '{"selectedRowId":"service_faq","title":"FAQ"}',
                    }
                }
            },
        },
    }
    response = client.post("/api/v1/evolution/webhook", json=payload)
    assert response.status_code == 200
    assert mock_handle_inbound.call_args.kwargs == {
        "sender_phone": "221770001122",
        "user_text": "FAQ",
        "action_id": "service_faq",
    }
