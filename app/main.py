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
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from slowapi.errors import RateLimitExceeded

from app.core.config import settings
from app.core.limiter import limiter

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

from app.api.v1.router import api_router
from app.api.v1.endpoints.auth import get_current_user
from app.db.base import Base
from app.db.migrate import sync_sqlite_schema
from app.db.session import engine

# Importer tous les modèles pour que SQLAlchemy les détecte
import app.models.user  # noqa: F401
import app.models.chat  # noqa: F401
import app.models.order  # noqa: F401


# ---------------------------------------------------------------------------
# Lifespan — code exécuté au démarrage / arrêt du serveur
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Crée les tables manquantes et synchronise le schéma SQLite au démarrage."""
    Base.metadata.create_all(bind=engine)
    sync_sqlite_schema(engine)
    yield
    # (nettoyage à l'arrêt si nécessaire)

# ---------------------------------------------------------------------------
# Rate Limiter (anti-spam / protection API LLM)
# ---------------------------------------------------------------------------
# Le limiter est défini dans app.core.limiter pour éviter les imports circulaires

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

# Enregistrer le limiter et son handler d'erreur 429
app.state.limiter = limiter
app.add_exception_handler(
    RateLimitExceeded,
    lambda request, exc: JSONResponse(
        status_code=429,
        content={
            "detail": "Trop de requêtes. Veuillez patienter quelques secondes avant de réessayer.",
            "retry_after": str(exc.retry_after) if hasattr(exc, 'retry_after') else "60",
        },
    ),
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
