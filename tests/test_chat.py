"""
Tests d'intégration — Étape 3 : Chat & Agent Superviseur
"""
from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.main import app
from app.db.base import Base
from app.db.session import get_db

TEST_DATABASE_URL = "sqlite:///./test_assistant_ia.db"

engine_test = create_engine(
    TEST_DATABASE_URL, connect_args={"check_same_thread": False}
)
TestingSessionLocal = sessionmaker(bind=engine_test, autocommit=False, autoflush=False)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(autouse=True)
def setup_db():
    """Initialise une base propre avant chaque test."""
    Base.metadata.drop_all(bind=engine_test)
    Base.metadata.create_all(bind=engine_test)
    app.dependency_overrides[get_db] = override_get_db
    yield
    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine_test)


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def auth_headers(client):
    """Crée un utilisateur de test et retourne le header d'authentification Bearer."""
    user_data = {
        "email": "user@example.com",
        "password": "securepassword123",
        "full_name": "Test User"
    }
    # Inscription
    client.post("/api/v1/auth/register", json=user_data)
    # Connexion
    response = client.post("/api/v1/auth/login", json={
        "email": user_data["email"],
        "password": user_data["password"]
    })
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Tests des routes de Chat
# ---------------------------------------------------------------------------

def test_chat_routes_require_authentication(client):
    """Vérifie que la route d'historique de chat renvoie 401 si non authentifié."""
    # GET history exige une authentification JWT
    r = client.get("/api/v1/chat/history")
    assert r.status_code == 401


@patch("app.api.v1.endpoints.chat.ai_service.detect_intent")
@patch("app.api.v1.endpoints.chat.ai_service.process_message")
def test_send_message_success(mock_process, mock_detect, client, auth_headers):
    """Vérifie l'envoi de message, le routage et le stockage en base."""
    from app.intelligence.orchestrator import AssistantReply
    
    # Configurer les mocks
    mock_detect.return_value = "tracking"
    mock_process.return_value = AssistantReply(
        texte="Je simule la réponse de suivi.",
        escalade=False,
        raison_escalade=None,
        ticket_id=None,
        outils_utilises=[]
    )

    payload = {"content": "Où est mon colis CMD12345 ?"}
    
    response = client.post(
        "/api/v1/chat/message",
        json=payload,
        headers=auth_headers
    )
    
    assert response.status_code == 201
    data = response.json()
    assert data["role"] == "assistant"
    assert "Je simule la réponse de suivi" in data["content"]
    assert data["intent"] == "tracking"
    assert data["language"] == "fr"
    assert data["escalade"] is False

    # Vérifier l'appel des mocks
    mock_detect.assert_called_once_with(payload["content"])
    mock_process.assert_called_once()


@patch("app.api.v1.endpoints.chat.ai_service.detect_intent")
@patch("app.api.v1.endpoints.chat.ai_service.process_message")
def test_chat_history_retrieval(mock_process, mock_detect, client, auth_headers):
    """Vérifie que l'historique contient bien les messages dans le bon ordre."""
    from app.intelligence.orchestrator import AssistantReply

    mock_detect.return_value = "general"
    mock_process.return_value = AssistantReply(
        texte="Bonjour ! Comment puis-je vous aider ?",
        escalade=False,
        raison_escalade=None,
        ticket_id=None,
        outils_utilises=[]
    )

    # Envoyer un message
    client.post(
        "/api/v1/chat/message",
        json={"content": "Salut"},
        headers=auth_headers
    )

    # Récupérer l'historique
    response = client.get("/api/v1/chat/history", headers=auth_headers)
    assert response.status_code == 200
    history = response.json()
    
    # Devrait y avoir 2 messages (l'utilisateur et la réponse de l'assistant)
    assert len(history) == 2
    assert history[0]["role"] == "user"
    assert history[0]["content"] == "Salut"
    assert history[1]["role"] == "assistant"
    assert history[1]["content"] == "Bonjour ! Comment puis-je vous aider ?"
