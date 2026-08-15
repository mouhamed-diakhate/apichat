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
from app.models.chat import ChatMessage
from app.models.user import User

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


@patch("app.api.v1.endpoints.chat.ai_service.process_message_with_intent")
def test_send_message_success(mock_process_intent, client, auth_headers):
    """Vérifie l'envoi de message, le routage et le stockage en base."""
    from app.intelligence.orchestrator import AssistantReply
    
    mock_process_intent.return_value = (
        AssistantReply(
            texte="Je simule la réponse de suivi.",
            escalade=False,
            raison_escalade=None,
            ticket_id=None,
            outils_utilises=[]
        ),
        "tracking"
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
    assert data["session_id"].startswith("web_")

    mock_process_intent.assert_called_once()


@patch("app.api.v1.endpoints.chat.ai_service.process_message_with_intent")
def test_chat_history_retrieval(mock_process_intent, client, auth_headers):
    """Vérifie que l'historique contient bien les messages dans le bon ordre."""
    from app.intelligence.orchestrator import AssistantReply

    mock_process_intent.return_value = (
        AssistantReply(
            texte="Bonjour ! Comment puis-je vous aider ?",
            escalade=False,
            raison_escalade=None,
            ticket_id=None,
            outils_utilises=[]
        ),
        "general"
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


@patch("app.api.v1.endpoints.chat.ai_service.process_message_with_intent")
def test_chat_persists_and_exposes_rag_sources(mock_process_intent, client, auth_headers):
    """Les sources citées survivent à la réponse HTTP et à l'historique."""
    from app.intelligence.orchestrator import AssistantReply

    source = {
        "id": "cgv_p006_c001",
        "marker": "S1",
        "citation": "Conditions générales de vente — Article 11 — p. 6",
        "document": "Conditions générales de vente",
        "filename": "conditions_Generales_de_vente.pdf",
        "page": 6,
        "section": "Article 11",
        "score": 0.92,
    }
    mock_process_intent.return_value = (
        AssistantReply(
            texte="Vous disposez de 48 heures.\n\nSources vérifiées :\n- [S1] Conditions générales de vente — Article 11 — p. 6",
            outils_utilises=["search_faq"],
            sources=[source],
        ),
        "faq",
    )

    response = client.post(
        "/api/v1/chat/message",
        json={"content": "Quel est le délai de réclamation ?"},
        headers=auth_headers,
    )

    assert response.status_code == 201
    assert response.json()["sources"] == [source]

    history = client.get("/api/v1/chat/history", headers=auth_headers)
    assert history.status_code == 200
    assert history.json()[-1]["sources"] == [source]


@patch("app.api.v1.endpoints.chat.ai_service.process_message_with_intent")
def test_client_message_is_kept_when_ai_fails(mock_process_intent, client, auth_headers):
    """Une panne IA ne doit pas annuler le message client deja capture."""
    mock_process_intent.side_effect = RuntimeError("provider indisponible")

    with pytest.raises(RuntimeError):
        client.post(
            "/api/v1/chat/message",
            json={"content": "Je n'ai toujours pas recu mon colis.", "session_id": "failure_case"},
            headers=auth_headers,
        )

    db = TestingSessionLocal()
    try:
        user = db.query(User).filter(User.email == "user@example.com").first()
        messages = (
            db.query(ChatMessage)
            .filter(ChatMessage.user_id == user.id)
            .order_by(ChatMessage.id.asc())
            .all()
        )
    finally:
        db.close()

    assert len(messages) == 1
    assert messages[0].role == "user"
    assert messages[0].content == "Je n'ai toujours pas recu mon colis."
    assert messages[0].session_id == "failure_case"


@patch("app.api.v1.endpoints.chat.ai_service.process_message")
def test_interactive_message_is_kept_before_ai_response(mock_process, client):
    """Le widget interactif capture aussi le texte avant son appel IA."""
    from app.services.session_manager import SessionState, get_or_create_session

    session_id = "interactive_failure_case"
    session = get_or_create_session(session_id)
    session.reset()
    session.language = "fr"
    session.state = SessionState.AGENT_ACTIVE
    mock_process.side_effect = RuntimeError("provider indisponible")

    with pytest.raises(RuntimeError):
        client.post(
            "/api/v1/chat/interactive",
            json={"session_id": session_id, "message": "Pouvez-vous suivre mon colis ?"},
        )

    db = TestingSessionLocal()
    try:
        guest = db.query(User).filter(User.email == "invite@texmiles.sn").first()
        messages = (
            db.query(ChatMessage)
            .filter(ChatMessage.user_id == guest.id, ChatMessage.session_id == session_id)
            .order_by(ChatMessage.id.asc())
            .all()
        )
    finally:
        db.close()

    assert len(messages) == 1
    assert messages[0].role == "user"
    assert messages[0].content == "Pouvez-vous suivre mon colis ?"
