"""
Tests d'intÃ©gration pour le tableau de bord.
"""
import csv
from io import StringIO

import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
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
    # CrÃ©e des messages pour un utilisateur authentifiÃ©.
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
                content="OÃ¹ est ma commande CMD1001 ?",
                intent="tracking",
                language="fr",
                escalade=False,
                ticket_id=None,
                session_id="dash_tracking",
            ),
            ChatMessage(
                user_id=user.id,
                role="user",
                content="Mon colis est endommagÃ©.",
                intent="claim",
                language="fr",
                escalade=True,
                raison_escalade="Produit abÃ®mÃ©",
                ticket_id="TCKT-1001",
                session_id="dash_claim",
            ),
            ChatMessage(
                user_id=user.id,
                role="assistant",
                content="Votre commande sera livrÃ©e demain.",
                intent="tracking",
                language="fr",
                escalade=False,
                ticket_id=None,
                session_id="dash_tracking",
            ),
            ChatMessage(
                user_id=user.id,
                role="assistant",
                content="Je transfÃ¨re votre demande au support.",
                intent="claim",
                language="fr",
                escalade=True,
                raison_escalade="RÃ©clamation client",
                ticket_id="TCKT-1001",
                session_id="dash_claim",
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


def test_dashboard_stats_use_assistant_escalations_and_distinct_conversations(
    client,
    auth_headers,
):
    """Les taux ne doivent ni compter les doublons, ni lire l'escalade client."""
    db = TestingSessionLocal()
    try:
        user = db.query(User).filter(User.email == "dashboard@example.com").first()
        assert user is not None
        base = datetime(2026, 8, 10, 9, 0, tzinfo=timezone.utc)
        db.add_all([
            # Deux messages client dans le meme fil : une seule conversation.
            ChatMessage(
                user_id=user.id,
                role="user",
                content="Suivi initial",
                intent="tracking",
                language="fr",
                session_id="metrics_tracking",
                created_at=base,
            ),
            ChatMessage(
                user_id=user.id,
                role="assistant",
                content="Je transfere le suivi.",
                intent="tracking",
                language="fr",
                escalade=True,
                ticket_id="MET-TRACK",
                session_id="metrics_tracking",
                created_at=base + timedelta(minutes=1),
            ),
            ChatMessage(
                user_id=user.id,
                role="user",
                content="Avez-vous une nouvelle ?",
                intent="tracking",
                language="fr",
                # L'escalade reste exclusivement sur le message assistant.
                escalade=False,
                session_id="metrics_tracking",
                created_at=base + timedelta(minutes=2),
            ),
            ChatMessage(
                user_id=user.id,
                role="assistant",
                content="Nous relancons le transporteur.",
                intent="tracking",
                language="fr",
                escalade=False,
                session_id="metrics_tracking",
                created_at=base + timedelta(minutes=3),
            ),
            # Une escalade traitee : 30 min entre la reponse IA et l'action humaine.
            ChatMessage(
                user_id=user.id,
                role="user",
                content="Je dois faire une reclamation.",
                intent="claim",
                language="fr",
                session_id="metrics_claim",
                handled_at=base + timedelta(minutes=40),
                created_at=base + timedelta(minutes=4),
            ),
            ChatMessage(
                user_id=user.id,
                role="assistant",
                content="Je transmets votre reclamation.",
                intent="claim",
                language="fr",
                escalade=True,
                ticket_id="MET-CLAIM",
                session_id="metrics_claim",
                created_at=base + timedelta(minutes=10),
            ),
            # Une conversation autonome, sans escalade.
            ChatMessage(
                user_id=user.id,
                role="user",
                content="Quels sont vos horaires ?",
                intent="faq",
                language="fr",
                session_id="metrics_faq",
                created_at=base + timedelta(minutes=12),
            ),
            ChatMessage(
                user_id=user.id,
                role="assistant",
                content="Nous sommes ouverts du lundi au samedi.",
                intent="faq",
                language="fr",
                escalade=False,
                session_id="metrics_faq",
                created_at=base + timedelta(minutes=13),
            ),
            # Hors periode : ne doit affecter aucun indicateur.
            ChatMessage(
                user_id=user.id,
                role="user",
                content="Ancienne reclamation",
                intent="claim",
                language="fr",
                session_id="metrics_old",
                created_at=base - timedelta(days=1),
            ),
            ChatMessage(
                user_id=user.id,
                role="assistant",
                content="Ancienne escalade",
                intent="claim",
                language="fr",
                escalade=True,
                ticket_id="MET-OLD",
                session_id="metrics_old",
                created_at=base - timedelta(days=1) + timedelta(minutes=1),
            ),
        ])
        db.commit()
    finally:
        db.close()

    response = client.get(
        "/api/v1/dashboard/stats?start_date=2026-08-10&end_date=2026-08-10",
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["period"]["anchor"] == "latest_user_message"
    assert data["total_messages_recus"] == 4
    assert data["total_conversations"] == 3
    assert data["escalated_conversations"] == 2
    assert data["assistant_escalation_count"] == 2
    assert data["resolved_conversations"] == 2
    assert data["autonomously_resolved_conversations"] == 1
    assert data["human_resolved_conversations"] == 1
    assert data["tickets_created"] == 2
    assert data["escalation_rate"] == pytest.approx(2 / 3, abs=0.0001)
    assert data["autonomous_resolution_rate"] == pytest.approx(1 / 3, abs=0.0001)
    assert data["escalation_resolution_rate"] == 0.5
    assert data["resolution_rate_by_intent"] == {
        "tracking": 0.0,
        "claim": 1.0,
        "faq": 1.0,
    }
    assert data["average_human_response_minutes"] == 30.0
    assert data["average_human_response_seconds"] == 1800.0


def test_dashboard_stats_rejects_an_invalid_period(client, auth_headers):
    response = client.get(
        "/api/v1/dashboard/stats?start_date=2026-08-11&end_date=2026-08-10",
        headers=auth_headers,
    )
    assert response.status_code == 422
    assert "debut" in response.json()["detail"]


def test_dashboard_exports_tickets_and_assistant_escalations_as_safe_csv(
    client,
    auth_headers,
):
    """L'export est filtrable, dedoublonne par fil et protege Excel."""
    db = TestingSessionLocal()
    try:
        client_user = User(
            email="csv-client@example.com",
            hashed_password="client",
            full_name="=FORMULE_CLIENT",
            is_active=True,
        )
        db.add(client_user)
        db.commit()
        db.refresh(client_user)
        base = datetime(2026, 8, 12, 9, 0, tzinfo=timezone.utc)
        db.add_all(
            [
                ChatMessage(
                    user_id=client_user.id,
                    role="user",
                    content="Ma livraison a un probleme.",
                    intent="claim",
                    language="fr",
                    session_id="csv_escalation",
                    handled_at=base + timedelta(minutes=20),
                    created_at=base,
                ),
                ChatMessage(
                    user_id=client_user.id,
                    role="assistant",
                    content="Je transmets au support.",
                    intent="claim",
                    language="fr",
                    escalade=True,
                    raison_escalade="Support humain requis",
                    ticket_id="CSV-100",
                    session_id="csv_escalation",
                    created_at=base + timedelta(minutes=2),
                ),
                ChatMessage(
                    user_id=client_user.id,
                    role="user",
                    content="Ancien echange hors periode.",
                    intent="claim",
                    language="fr",
                    session_id="csv_old",
                    created_at=base - timedelta(days=2),
                ),
                ChatMessage(
                    user_id=client_user.id,
                    role="assistant",
                    content="Ancienne escalade.",
                    intent="claim",
                    language="fr",
                    escalade=True,
                    ticket_id="CSV-OLD",
                    session_id="csv_old",
                    created_at=base - timedelta(days=2) + timedelta(minutes=1),
                ),
            ]
        )
        db.commit()
    finally:
        db.close()

    response = client.get(
        "/api/v1/dashboard/exports/tickets-escalades.csv"
        "?start_date=2026-08-12&end_date=2026-08-12",
        headers=auth_headers,
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert response.headers["content-disposition"].startswith("attachment;")
    assert response.content.startswith(b"\xef\xbb\xbf")

    rows = list(csv.reader(StringIO(response.content.decode("utf-8-sig")), delimiter=";"))
    assert len(rows) == 2
    assert rows[0][0] == "Dernier message client (UTC)"
    assert rows[1][1] == "'=FORMULE_CLIENT"
    assert rows[1][6] == "Oui"
    assert rows[1][9] == "CSV-100"
    assert rows[1][12] == "18.00"
    assert "CSV-OLD" not in response.content.decode("utf-8-sig")


def test_dashboard_shows_client_message_without_assistant_response(client, auth_headers):
    """Le fil est visible des que le client ecrit, avant toute reponse IA."""
    db = TestingSessionLocal()
    try:
        user = db.query(User).filter(User.email == "dashboard@example.com").first()
        assert user is not None
        db.add(
            ChatMessage(
                user_id=user.id,
                role="user",
                content="Je souhaite connaitre le statut de mon colis.",
                intent="tracking",
                language="fr",
                session_id="waiting_session",
            )
        )
        db.commit()
    finally:
        db.close()

    response = client.get("/api/v1/dashboard/conversations", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    item = data["items"][0]
    assert item["message_preview"] == "Je souhaite connaitre le statut de mon colis."
    assert item["status"] == "en_attente"
    assert item["has_response"] is False


def test_dashboard_detail_keeps_guest_sessions_isolated(client, auth_headers):
    """Deux sessions du compte invite ne doivent jamais etre fusionnees."""
    db = TestingSessionLocal()
    try:
        guest = User(
            email="invite@texmiles.sn",
            hashed_password="guest",
            full_name="Visiteur Invite",
            is_active=True,
        )
        db.add(guest)
        db.commit()
        db.refresh(guest)

        first = ChatMessage(
            user_id=guest.id,
            role="user",
            content="Message de la session A",
            intent="faq",
            language="fr",
            session_id="guest_session_A",
        )
        second = ChatMessage(
            user_id=guest.id,
            role="user",
            content="Message de la session B",
            intent="tracking",
            language="fr",
            session_id="guest_session_B",
        )
        db.add_all([first, second])
        db.commit()
        db.refresh(first)
    finally:
        db.close()

    response = client.get(
        f"/api/v1/dashboard/conversations/{first.id}",
        headers=auth_headers,
    )
    assert response.status_code == 200
    contents = [message["content"] for message in response.json()["messages"]]
    assert contents == ["Message de la session A"]


def test_dashboard_exposes_the_real_whatsapp_number_for_contact(client, auth_headers):
    """Le bouton de contact recoit le numero du client, jamais une valeur demo."""
    db = TestingSessionLocal()
    try:
        wa_user = User(
            email="wa_221771234567@texmiles.sn",
            hashed_password="whatsapp",
            full_name="Client WhatsApp +221771234567",
            is_active=True,
        )
        db.add(wa_user)
        db.commit()
        db.refresh(wa_user)
        message = ChatMessage(
            user_id=wa_user.id,
            role="user",
            content="Bonjour, je souhaite suivre mon colis.",
            intent="tracking",
            language="fr",
            session_id="221771234567",
        )
        db.add(message)
        db.commit()
        db.refresh(message)
    finally:
        db.close()

    listing = client.get("/api/v1/dashboard/conversations", headers=auth_headers)
    assert listing.status_code == 200
    assert listing.json()["items"][0]["raw_phone"] == "221771234567"

    detail = client.get(
        f"/api/v1/dashboard/conversations/{message.id}",
        headers=auth_headers,
    )
    assert detail.status_code == 200
    assert detail.json()["client"]["raw_phone"] == "221771234567"


def test_dashboard_marks_an_escalation_as_treated(client, auth_headers):
    """Le bouton de cloture persiste l'etat sans perdre l'audit d'escalade."""
    db = TestingSessionLocal()
    try:
        agent = db.query(User).filter(User.email == "dashboard@example.com").first()
        assert agent is not None
        client_user = User(
            email="client-escalade@texmiles.sn",
            hashed_password="client",
            full_name="Client Escalade",
            is_active=True,
        )
        db.add(client_user)
        db.commit()
        db.refresh(client_user)
        incoming = ChatMessage(
            user_id=client_user.id,
            role="user",
            content="Je veux parler a un agent humain.",
            intent="claim",
            language="fr",
            # L'escalade est la propriete de la reponse assistant.
            escalade=False,
            raison_escalade="Demande humaine",
            ticket_id="REC-4567",
            session_id="resolve_session",
        )
        response = ChatMessage(
            user_id=client_user.id,
            role="assistant",
            content="Je transfere votre demande.",
            intent="claim",
            language="fr",
            escalade=True,
            raison_escalade="Demande humaine",
            ticket_id="REC-4567",
            session_id="resolve_session",
        )
        db.add_all([incoming, response])
        db.commit()
        db.refresh(incoming)
        incoming_id = incoming.id
        agent_id = agent.id
    finally:
        db.close()

    assert client.post(f"/api/v1/dashboard/conversations/{incoming_id}/resolve").status_code in (401, 403)

    first = client.post(
        f"/api/v1/dashboard/conversations/{incoming_id}/resolve",
        headers=auth_headers,
    )
    assert first.status_code == 200
    assert first.json()["status"] == "traite"
    assert first.json()["handled_at"] is not None
    assert first.json()["handled_by_user_id"] == agent_id

    # L'action est idempotente : un second clic conserve le statut traite.
    second = client.post(
        f"/api/v1/dashboard/conversations/{incoming_id}/resolve",
        headers=auth_headers,
    )
    assert second.status_code == 200
    assert second.json()["status"] == "traite"

    detail = client.get(
        f"/api/v1/dashboard/conversations/{incoming_id}",
        headers=auth_headers,
    ).json()
    assert detail["status"] == "traite"
    assert detail["escalade"] is True
    assert detail["raison_escalade"] == "Demande humaine"
    assert detail["ticket_id"] == "REC-4567"

    filtered = client.get(
        "/api/v1/dashboard/conversations?status=traite",
        headers=auth_headers,
    ).json()
    assert filtered["total"] == 1
    assert filtered["items"][0]["id"] == incoming_id


def test_dashboard_does_not_resolve_an_old_message_after_a_new_client_message(client, auth_headers):
    """Un agent ne peut pas cloturer une escalation deja depassee dans le fil."""
    db = TestingSessionLocal()
    try:
        user = db.query(User).filter(User.email == "dashboard@example.com").first()
        assert user is not None
        old_escalation = ChatMessage(
            user_id=user.id,
            role="user",
            content="Ancienne escalation",
            escalade=True,
            session_id="newer_message_session",
        )
        newer_message = ChatMessage(
            user_id=user.id,
            role="user",
            content="Nouveau message client",
            escalade=False,
            session_id="newer_message_session",
        )
        db.add_all([old_escalation, newer_message])
        db.commit()
        db.refresh(old_escalation)
        old_id = old_escalation.id
    finally:
        db.close()

    response = client.post(
        f"/api/v1/dashboard/conversations/{old_id}/resolve",
        headers=auth_headers,
    )
    assert response.status_code == 409
