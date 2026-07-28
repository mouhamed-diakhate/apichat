"""
Tests d'intégration pour le tableau de bord.
"""
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
    user_data = {
        "email": "dashboard@example.com",
        "password": "motdepasse123",
        "full_name": "Dashboard User"
    }
    client.post("/api/v1/auth/register", json=user_data)
    login = client.post("/api/v1/auth/login", json={
        "email": user_data["email"],
        "password": user_data["password"],
    })
    token = login.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_dashboard_page_loads(client):
    response = client.get("/dashboard")
    assert response.status_code == 200
    assert "TexMiles Assistant — Tableau de bord" in response.text


def test_dashboard_stats_requires_authentication(client):
    response = client.get("/api/v1/dashboard/stats")
    assert response.status_code in (401, 403)


def test_dashboard_conversations_requires_authentication(client):
    response = client.get("/api/v1/dashboard/conversations")
    assert response.status_code in (401, 403)


def test_dashboard_stats_and_conversations_return_expected_data(client, auth_headers):
    # Crée des messages pour un utilisateur authentifié.
    db = TestingSessionLocal()
    try:
        user = db.query(User).filter(User.email == "dashboard@example.com").first()
        assert user is not None

        # Nettoyer tous les messages pour isoler les statistiques du test
        db.query(ChatMessage).delete()
        db.commit()

        db.add_all([
            ChatMessage(
                user_id=user.id,
                role="user",
                content="Où est ma commande CMD1001 ?",
                intent="tracking",
                language="fr",
                escalade=False,
                ticket_id=None,
            ),
            ChatMessage(
                user_id=user.id,
                role="user",
                content="Mon colis est endommagé.",
                intent="claim",
                language="fr",
                escalade=True,
                raison_escalade="Produit abîmé",
                ticket_id="TCKT-1001",
            ),
            ChatMessage(
                user_id=user.id,
                role="assistant",
                content="Votre commande sera livrée demain.",
                intent="tracking",
                language="fr",
                escalade=False,
                ticket_id=None,
            ),
            ChatMessage(
                user_id=user.id,
                role="assistant",
                content="Je transfère votre demande au support.",
                intent="claim",
                language="fr",
                escalade=True,
                raison_escalade="Réclamation client",
                ticket_id="TCKT-1001",
            ),
        ])
        db.commit()
    finally:
        db.close()

    stats_response = client.get("/api/v1/dashboard/stats", headers=auth_headers)
    assert stats_response.status_code == 200
    stats_data = stats_response.json()
    assert stats_data["total_messages_recus"] == 2
    assert stats_data["tickets_created"] == 1
    assert stats_data["top_intents"]["tracking"] == 1
    assert stats_data["top_intents"]["claim"] == 1
    assert stats_data["escalation_rate"] == 0.5

    conv_response = client.get("/api/v1/dashboard/conversations", headers=auth_headers)
    assert conv_response.status_code == 200
    conv_data = conv_response.json()
    assert conv_data["total"] == 2
    assert len(conv_data["items"]) == 2
    assert any(item["intent"] == "tracking" for item in conv_data["items"])
    assert any(item["ticket_id"] == "TCKT-1001" for item in conv_data["items"])
