"""Tests d'intégration du CRUD FAQ réservé aux administrateurs."""

from __future__ import annotations

import json
import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.v1.endpoints import faq_admin
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.user import User
from app.services.faq_management import FaqManagementService


# Ce module est parfois exécuté pendant les tests du dashboard. Une base dédiée
# évite que leurs fixtures respectives (drop_all/create_all) se perturbent.
TEST_DATABASE_URL = "sqlite:///./test_faq_admin.db"
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


@pytest.fixture
def faq_file(tmp_path, monkeypatch):
    path = tmp_path / "faq.fr.json"
    path.write_text(
        json.dumps(
            {
                "_commentaire": "FAQ de test",
                "entrees": [
                    {
                        "id": "horaires",
                        "question": "Quels sont vos horaires ?",
                        "mots_cles": ["horaires", "ouverture"],
                        "reponse": "Du lundi au samedi.",
                    },
                    {
                        "id": "livraison",
                        "question": "Quels sont les délais de livraison ?",
                        "mots_cles": ["délai", "expédition"],
                        "reponse": "Entre deux et cinq jours.",
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(faq_admin, "faq_management_service", FaqManagementService(path))
    return path


def _headers_for(client: TestClient, *, email: str, superuser: bool) -> dict[str, str]:
    password = "motdepasse123"
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "full_name": "Agent FAQ"},
    )
    assert response.status_code == 201
    if superuser:
        db = TestingSessionLocal()
        try:
            user = db.query(User).filter(User.email == email).one()
            user.is_superuser = True
            db.commit()
        finally:
            db.close()
    login = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def test_faq_management_requires_an_active_superuser(client, faq_file):
    assert client.get("/api/v1/dashboard/faq").status_code in (401, 403)

    user_headers = _headers_for(client, email="member@example.com", superuser=False)
    assert client.get("/api/v1/dashboard/faq", headers=user_headers).status_code == 403
    assert (
        client.post(
            "/api/v1/dashboard/faq",
            headers=user_headers,
            json={"question": "Question", "reponse": "Réponse", "mots_cles": []},
        ).status_code
        == 403
    )


def test_admin_can_list_and_search_faq_entries(client, faq_file):
    headers = _headers_for(client, email="faq-admin@example.com", superuser=True)

    listing = client.get("/api/v1/dashboard/faq?page=1&page_size=1", headers=headers)
    assert listing.status_code == 200
    assert listing.json()["total"] == 2
    assert len(listing.json()["items"]) == 1
    assert listing.json()["items"][0]["id"] == "horaires"

    search = client.get("/api/v1/dashboard/faq?q=expedition", headers=headers)
    assert search.status_code == 200
    assert search.json()["total"] == 1
    assert search.json()["items"][0]["id"] == "livraison"


def test_admin_can_create_update_and_delete_faq_entries_atomically(client, faq_file, monkeypatch):
    headers = _headers_for(client, email="faq-editor@example.com", superuser=True)
    invalidations: list[bool] = []
    monkeypatch.setattr(
        faq_admin.ai_service,
        "invalidate_knowledge_cache",
        lambda: invalidations.append(True),
    )

    created = client.post(
        "/api/v1/dashboard/faq",
        headers=headers,
        json={
            "question": "Comment suivre ma commande ?",
            "reponse": "Utilisez votre numéro de suivi dans le menu Suivi.",
            "mots_cles": ["suivi", "commande", "Suivi"],
        },
    )
    assert created.status_code == 201
    entry = created.json()
    assert re.fullmatch(r"[a-z][a-z0-9_]{0,79}", entry["id"])
    assert entry["mots_cles"] == ["suivi", "commande"]
    assert invalidations == [True]

    updated = client.put(
        f"/api/v1/dashboard/faq/{entry['id']}",
        headers=headers,
        json={"reponse": "Saisissez le numéro de suivi depuis le menu Suivi."},
    )
    assert updated.status_code == 200
    assert updated.json()["question"] == "Comment suivre ma commande ?"
    assert updated.json()["reponse"] == "Saisissez le numéro de suivi depuis le menu Suivi."
    assert invalidations == [True, True]

    removed = client.delete(f"/api/v1/dashboard/faq/{entry['id']}", headers=headers)
    assert removed.status_code == 200
    assert removed.json() == {"id": entry["id"], "deleted": True}
    assert invalidations == [True, True, True]

    # Le fichier final reste un JSON UTF-8 lisible et aucun brouillon n'est laissé.
    stored = json.loads(faq_file.read_text(encoding="utf-8"))
    assert [item["id"] for item in stored["entrees"]] == ["horaires", "livraison"]
    assert list(faq_file.parent.glob(".faq.fr.json.*.tmp")) == []


def test_faq_management_rejects_duplicate_or_unsafe_ids_and_empty_updates(client, faq_file):
    headers = _headers_for(client, email="faq-validation@example.com", superuser=True)

    duplicate = client.post(
        "/api/v1/dashboard/faq",
        headers=headers,
        json={
            "id": "horaires",
            "question": "Nouvelle question",
            "reponse": "Nouvelle réponse",
            "mots_cles": [],
        },
    )
    assert duplicate.status_code == 409

    unsafe = client.post(
        "/api/v1/dashboard/faq",
        headers=headers,
        json={
            "id": "../hors_faq",
            "question": "Nouvelle question",
            "reponse": "Nouvelle réponse",
            "mots_cles": [],
        },
    )
    assert unsafe.status_code == 422

    empty_update = client.put("/api/v1/dashboard/faq/horaires", headers=headers, json={})
    assert empty_update.status_code == 422
    null_update = client.put(
        "/api/v1/dashboard/faq/horaires",
        headers=headers,
        json={"question": None},
    )
    assert null_update.status_code == 422
