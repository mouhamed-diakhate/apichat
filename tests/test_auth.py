"""
Tests d'intégration — Étape 2 : Authentification JWT

Lance avec : .venv\\Scripts\\pytest tests/ -v
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.main import app
from app.db.base import Base
from app.db.session import get_db

# ---------------------------------------------------------------------------
# Base de données de test (SQLite en mémoire — indépendante de dev)
# ---------------------------------------------------------------------------
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
    """Repart de zéro avant chaque test, nettoie après."""
    Base.metadata.drop_all(bind=engine_test)   # Nettoie les données résiduelles
    Base.metadata.create_all(bind=engine_test)
    app.dependency_overrides[get_db] = override_get_db
    yield
    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine_test)


@pytest.fixture
def client():
    return TestClient(app)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_register_success(client):
    r = client.post("/api/v1/auth/register", json={
        "email": "alice@example.com",
        "password": "motdepasse123",
        "full_name": "Alice Dupont"
    })
    assert r.status_code == 201
    data = r.json()
    assert data["email"] == "alice@example.com"
    assert data["full_name"] == "Alice Dupont"
    assert "hashed_password" not in data  # jamais exposé


def test_register_duplicate_email(client):
    payload = {"email": "bob@example.com", "password": "motdepasse123"}
    client.post("/api/v1/auth/register", json=payload)
    r = client.post("/api/v1/auth/register", json=payload)
    assert r.status_code == 409


def test_login_success(client):
    client.post("/api/v1/auth/register", json={
        "email": "charlie@example.com",
        "password": "motdepasse123"
    })
    r = client.post("/api/v1/auth/login", json={
        "email": "charlie@example.com",
        "password": "motdepasse123"
    })
    assert r.status_code == 200
    data = r.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert data["expires_in"] > 0


def test_login_wrong_password(client):
    client.post("/api/v1/auth/register", json={
        "email": "diana@example.com",
        "password": "motdepasse123"
    })
    r = client.post("/api/v1/auth/login", json={
        "email": "diana@example.com",
        "password": "mauvais_mdp"
    })
    assert r.status_code == 401


def test_get_me_authenticated(client):
    client.post("/api/v1/auth/register", json={
        "email": "eve@example.com",
        "password": "motdepasse123"
    })
    login = client.post("/api/v1/auth/login", json={
        "email": "eve@example.com",
        "password": "motdepasse123"
    })
    token = login.json()["access_token"]
    r = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert r.json()["email"] == "eve@example.com"


def test_get_me_without_token(client):
    r = client.get("/api/v1/auth/me")
    assert r.status_code in (401, 403)  # HTTPBearer : non authentifié
