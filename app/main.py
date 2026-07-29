"""
Point d'entrée principal de l'API assistant-ia-api.

Démarrage :
    uvicorn app.main:app --reload

Documentation interactive :
    http://127.0.0.1:8000/docs       (Swagger UI)
    http://127.0.0.1:8000/redoc      (ReDoc)
"""
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.core.config import settings

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

from app.api.v1.router import api_router
from app.api.v1.endpoints.auth import get_current_user
from app.db.base import Base
from app.db.session import engine

# Importer tous les modèles pour que SQLAlchemy les détecte
import app.models.user  # noqa: F401
import app.models.chat  # noqa: F401
import app.models.order  # noqa: F401
import app.models.session  # noqa: F401


def ensure_db_schema_and_admin():
    """Effectue les migrations légères (ajout de session_id dans PostgreSQL/SQLite) et crée l'admin par défaut."""
    from app.db.session import SessionLocal
    from app.models.user import User
    from app.core.security import hash_password
    from sqlalchemy import text

    # 1. Migrations légères sans Alembic
    try:
        with engine.begin() as conn:
            # Colonne session_id dans chat_messages (ajoutée lors de la session précédente)
            conn.execute(text("ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS session_id VARCHAR(100);"))
            # Index sur conversation_sessions.updated_at pour les requêtes de cleanup TTL
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_conversation_sessions_updated_at "
                "ON conversation_sessions (updated_at);"
            ))
    except Exception:
        pass


    # 2. Créer l'administrateur par défaut s'il n'existe pas déjà
    db = SessionLocal()
    try:
        admin = db.query(User).filter(User.email == "admin@texmiles.sn").first()
        if not admin:
            admin = User(
                email="admin@texmiles.sn",
                hashed_password=hash_password("Admin1234!"),
                full_name="Administrateur TexMiles",
                is_active=True,
                is_superuser=True,
            )
            db.add(admin)
            db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Lifespan — code exécuté au démarrage / arrêt du serveur
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Crée les tables manquantes, migre le schéma et crée l'administrateur par défaut au démarrage (idempotent)."""
    from app.core.logging import setup_logging
    setup_logging(log_level="INFO", json_format=True)
    Base.metadata.create_all(bind=engine)
    ensure_db_schema_and_admin()
    yield
    # (nettoyage à l'arrêt si nécessaire)


# ---------------------------------------------------------------------------
# Création de l'application FastAPI
# ---------------------------------------------------------------------------
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description=settings.APP_DESCRIPTION,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

# ---------------------------------------------------------------------------
# Middleware CORS
# ---------------------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Fichiers statiques et templates Jinja2
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

# ---------------------------------------------------------------------------
# Inclusion des routes API versionnées
# ---------------------------------------------------------------------------
app.include_router(api_router, prefix="/api/v1")


# ---------------------------------------------------------------------------
# Routes de base
# ---------------------------------------------------------------------------
@app.get(
    "/",
    tags=["Root"],
    summary="Page d'accueil de l'API",
)
async def root():
    """Retourne les informations générales de l'API."""
    return {
        "name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "description": settings.APP_DESCRIPTION,
        "docs": "/docs",
        "health": "/health",
    }


@app.get(
    "/dashboard",
    tags=["Dashboard"],
    summary="Tableau de bord de supervision",
)
async def dashboard_page(request: Request):
    return templates.TemplateResponse(request, "dashboard.html")


@app.get(
    "/chat-demo",
    tags=["Interactive Chat"],
    summary="Interface de test local interactive (Langue -> Menu -> Agent IA)",
)
async def chat_demo_page(request: Request):
    return templates.TemplateResponse(request, "chat_test.html")


@app.get(
    "/health",
    tags=["Health"],
    summary="Vérification de l'état de l'API",
)
async def health_check():
    """
    Endpoint de santé — utilisé par les load balancers, monitoring, CI/CD.

    Retourne `status: ok` si l'API est opérationnelle.
    """
    return {
        "status": "ok",
        "api": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "debug": settings.DEBUG,
    }
