"""
Point d'entrée principal de l'API assistant-ia-api.

Démarrage :
    uvicorn app.main:app --reload

Documentation interactive :
    http://127.0.0.1:8000/docs       (Swagger UI)
    http://127.0.0.1:8000/redoc      (ReDoc)
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.api.v1.router import api_router
from app.db.base import Base
from app.db.session import engine

# Importer tous les modèles pour que SQLAlchemy les détecte
import app.models.user  # noqa: F401
import app.models.chat  # noqa: F401


# ---------------------------------------------------------------------------
# Lifespan — code exécuté au démarrage / arrêt du serveur
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Crée les tables manquantes au démarrage (idempotent)."""
    Base.metadata.create_all(bind=engine)
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
