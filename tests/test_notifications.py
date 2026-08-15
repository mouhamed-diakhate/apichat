"""Tests des notifications d'escalade destinees aux agents de supervision."""
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.security import hash_password
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.chat import ChatMessage
from app.models.notification import AgentNotification
from app.models.user import User
from app.services.conversation_capture import enrich_inbound_message


TEST_DATABASE_URL = "sqlite:///./test_assistant_ia.db"
engine_test = create_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(bind=engine_test, autocommit=False, autoflush=False)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.drop_all(bind=engine_test)
    Base.metadata.create_all(bind=engine_test)
    app.dependency_overrides[get_db] = override_get_db
    yield
    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine_test)


@pytest.fixture
def client():
    return TestClient(app)


def _create_user(db, email: str, *, superuser: bool = False, active: bool = True) -> User:
    user = User(
        email=email,
        hashed_password=hash_password("motdepasse123"),
        full_name=email.split("@")[0],
        is_active=active,
        is_superuser=superuser,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _headers_for(client: TestClient, email: str) -> dict:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "motdepasse123"},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_escalation_creates_one_notification_per_active_agent_and_is_idempotent():
    db = TestingSessionLocal()
    try:
        active_agent = _create_user(db, "agent-actif@texmiles.sn", superuser=True)
        _create_user(db, "agent-inactif@texmiles.sn", superuser=True, active=False)
        _create_user(db, "client@texmiles.sn")
        customer = db.query(User).filter(User.email == "client@texmiles.sn").first()
        message = ChatMessage(
            user_id=customer.id,
            role="user",
            content="Je veux parler a un responsable, mon colis est perdu.",
            session_id="notification_session",
        )
        db.add(message)
        db.commit()
        db.refresh(message)

        enrich_inbound_message(
            db,
            message,
            intent="claim",
            language="fr",
            escalade=True,
            raison_escalade="Demande explicite d'un agent humain",
            ticket_id="REC-1234",
        )
        # Une seconde mise a jour du meme evenement ne recree pas d'alerte.
        enrich_inbound_message(
            db,
            message,
            intent="claim",
            language="fr",
            escalade=True,
            raison_escalade="Demande explicite d'un agent humain",
            ticket_id="REC-1234",
        )

        notifications = db.query(AgentNotification).all()
        active_agent_id = active_agent.id
        message_id = message.id
    finally:
        db.close()

    assert len(notifications) == 1
    notification = notifications[0]
    assert notification.recipient_user_id == active_agent_id
    assert notification.source_message_id == message_id
    assert notification.ticket_id == "REC-1234"
    assert notification.is_read is False
    assert "Demande explicite" in notification.body


@patch("app.api.v1.endpoints.chat.ai_service.process_message_with_intent")
def test_escalated_web_chat_notifies_a_supervisor(mock_process_intent, client):
    from app.intelligence.orchestrator import AssistantReply

    db = TestingSessionLocal()
    try:
        _create_user(db, "superviseur@texmiles.sn", superuser=True)
    finally:
        db.close()

    client.post(
        "/api/v1/auth/register",
        json={
            "email": "client-web@texmiles.sn",
            "password": "motdepasse123",
            "full_name": "Client Web",
        },
    )
    customer_headers = _headers_for(client, "client-web@texmiles.sn")
    mock_process_intent.return_value = (
        AssistantReply(
            texte="Je transmets votre demande a un agent.",
            escalade=True,
            raison_escalade="Reclamation urgente",
            ticket_id="REC-9999",
            outils_utilises=[],
        ),
        "claim",
    )

    response = client.post(
        "/api/v1/chat/message",
        json={"content": "Mon colis est perdu, je veux un humain.", "session_id": "web_escalade"},
        headers=customer_headers,
    )

    assert response.status_code == 201
    db = TestingSessionLocal()
    try:
        notification = db.query(AgentNotification).one()
        source = db.query(ChatMessage).filter(ChatMessage.id == notification.source_message_id).one()
    finally:
        db.close()

    assert source.role == "user"
    assert source.escalade is True
    assert notification.ticket_id == "REC-9999"
    assert "Reclamation urgente" in notification.body


def test_notification_endpoints_are_isolated_and_mark_read(client):
    db = TestingSessionLocal()
    try:
        first_agent = _create_user(db, "agent-un@texmiles.sn", superuser=True)
        second_agent = _create_user(db, "agent-deux@texmiles.sn", superuser=True)
        customer = _create_user(db, "client-notification@texmiles.sn")
        message = ChatMessage(
            user_id=customer.id,
            role="user",
            content="Besoin d'aide humaine",
            escalade=True,
            raison_escalade="Client vulnerable",
            session_id="notification_api",
        )
        db.add(message)
        db.commit()
        db.refresh(message)
        enrich_inbound_message(db, message, escalade=True, raison_escalade="Client vulnerable")
        message_id = message.id
    finally:
        db.close()

    first_headers = _headers_for(client, "agent-un@texmiles.sn")
    second_headers = _headers_for(client, "agent-deux@texmiles.sn")
    assert client.get("/api/v1/dashboard/notifications").status_code in (401, 403)

    first_listing = client.get(
        "/api/v1/dashboard/notifications?unread_only=true",
        headers=first_headers,
    )
    assert first_listing.status_code == 200
    first_data = first_listing.json()
    assert first_data["unread_count"] == 1
    assert first_data["items"][0]["conversation_id"] == message_id
    first_notification_id = first_data["items"][0]["id"]

    # Un agent ne peut pas accuser lecture de l'alerte adressee a un autre.
    assert client.post(
        f"/api/v1/dashboard/notifications/{first_notification_id}/read",
        headers=second_headers,
    ).status_code == 404

    marked = client.post(
        f"/api/v1/dashboard/notifications/{first_notification_id}/read",
        headers=first_headers,
    )
    assert marked.status_code == 200
    assert marked.json()["is_read"] is True

    after_read = client.get(
        "/api/v1/dashboard/notifications?unread_only=true",
        headers=first_headers,
    ).json()
    assert after_read == {"items": [], "unread_count": 0}

    # L'autre agent conserve sa propre alerte non lue.
    second_listing = client.get(
        "/api/v1/dashboard/notifications?unread_only=true",
        headers=second_headers,
    ).json()
    assert second_listing["unread_count"] == 1
    assert second_listing["items"][0]["id"] != first_notification_id
    assert "recipient_user_id" not in second_listing["items"][0]


@patch(
    "app.services.notification_service.create_escalation_notifications",
    side_effect=RuntimeError("service de notification indisponible"),
)
def test_notification_failure_does_not_undo_the_escalation(mock_notify):
    db = TestingSessionLocal()
    try:
        customer = _create_user(db, "client-sans-alerte@texmiles.sn")
        message = ChatMessage(
            user_id=customer.id,
            role="user",
            content="Je veux une escalade",
            session_id="notification_failure",
        )
        db.add(message)
        db.commit()
        db.refresh(message)

        enrich_inbound_message(
            db,
            message,
            escalade=True,
            raison_escalade="Verification manuelle requise",
        )
        db.refresh(message)
    finally:
        db.close()

    mock_notify.assert_called_once()
    assert message.escalade is True
    assert message.raison_escalade == "Verification manuelle requise"
