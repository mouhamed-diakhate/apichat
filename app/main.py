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
from app.db.migrate import sync_postgresql_schema, sync_sqlite_schema
from app.db.session import engine

# Importer tous les modèles pour que SQLAlchemy les détecte
import app.models.user  # noqa: F401
import app.models.chat  # noqa: F401
import app.models.order  # noqa: F401
import app.models.session  # noqa: F401
import app.models.csat  # noqa: F401
import app.models.notification  # noqa: F401


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
            # Sources de connaissance RAG utilisées pour produire la réponse.
            conn.execute(text("ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS sources_utilisees TEXT;"))
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
    # `create_all()` ne modifie pas une table existante. Synchroniser les
    # colonnes ajoutées après le premier démarrage, notamment celles utilisées
    # pour marquer une conversation comme traitée.
    sync_sqlite_schema(engine)
    sync_postgresql_schema(engine)
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


from fastapi.responses import HTMLResponse

@app.get(
    "/chat-demo",
    tags=["Interactive Chat"],
    summary="Interface de test local interactive (Langue -> Menu -> Agent IA)",
)
async def chat_demo_page(request: Request):
    return templates.TemplateResponse(request, "chat_test.html")


@app.get(
    "/qr",
    tags=["WhatsApp"],
    summary="Affichage dynamique du QR Code WhatsApp",
)
async def qr_page():
    """Génère et affiche le QR Code WhatsApp directement dans le navigateur sans erreur 401."""
    import urllib.request, json
    b64 = ""
    try:
        url = f"{settings.EVOLUTION_API_URL.rstrip('/')}/instance/connect/{settings.EVOLUTION_INSTANCE_NAME}"
        req = urllib.request.Request(url, headers={"apikey": settings.EVOLUTION_API_KEY})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            b64 = data.get("base64", "")
    except Exception:
        b64 = ""

    html_content = f"""<!DOCTYPE html>
<html lang="fr">
<head>
    <meta charset="UTF-8">
    <meta http-equiv="refresh" content="12">
    <title>Scanner WhatsApp — TexMiles</title>
    <style>
        body {{ font-family: 'Segoe UI', system-ui, sans-serif; display: flex; align-items: center; justify-content: center; min-height: 100vh; background: #0f172a; color: white; margin: 0; }}
        .card {{ background: #1e293b; padding: 2.5rem; border-radius: 20px; box-shadow: 0 15px 35px rgba(0,0,0,0.5); text-align: center; max-width: 420px; }}
        h1 {{ margin-top: 0; color: #22c55e; font-size: 1.6rem; }}
        p {{ color: #94a3b8; font-size: 0.95rem; line-height: 1.5; }}
        img {{ width: 270px; height: 270px; border-radius: 12px; background: white; padding: 10px; border: 4px solid #22c55e; margin: 1rem 0; }}
        .badge {{ background: #22c55e22; color: #22c55e; padding: 4px 12px; border-radius: 20px; font-weight: 600; font-size: 0.85rem; }}
        .refresh {{ margin-top: 1rem; font-size: 0.8rem; color: #64748b; }}
    </style>
</head>
<body>
    <div class="card">
        <span class="badge">Assistant IA TexMiles</span>
        <h1>📱 Connecter WhatsApp</h1>
        <p>Ouvrez <b>WhatsApp</b> sur votre téléphone → <b>Appareils connectés</b> → <b>Connecter un appareil</b> puis scannez :</p>
        {"<img src='" + b64 + "' alt='QR Code WhatsApp'>" if b64 else "<p style='color:#ef4444; margin: 2rem 0;'>⚠️ Impossible de charger le QR Code.<br>L'appareil est peut-être déjà connecté !</p>"}
        <p class="refresh">⚡ S'actualise automatiquement toutes les 12 secondes.</p>
    </div>
</body>
</html>"""
    return HTMLResponse(content=html_content)


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
