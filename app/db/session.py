"""
Gestion de la session de base de données.

- `engine` : connexion à la base (SQLite ou PostgreSQL selon .env)
- `SessionLocal` : fabrique de sessions
- `get_db` : dépendance FastAPI pour injecter une session dans les endpoints
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from typing import Generator

from app.core.config import settings

# ---------------------------------------------------------------------------
# Configuration du moteur
# ---------------------------------------------------------------------------
# SQLite nécessite connect_args pour le mode multi-thread (FastAPI)
connect_args = (
    {"check_same_thread": False}
    if settings.DATABASE_URL.startswith("sqlite")
    else {}
)

engine = create_engine(
    settings.DATABASE_URL,
    connect_args=connect_args,
    # Optimisations de connexion (pool non applicable à SQLite)
    pool_pre_ping=True,
)

# ---------------------------------------------------------------------------
# Fabrique de sessions
# ---------------------------------------------------------------------------
SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
)


# ---------------------------------------------------------------------------
# Dépendance FastAPI — injectée dans les endpoints via Depends(get_db)
# ---------------------------------------------------------------------------
def get_db() -> Generator[Session, None, None]:
    """
    Ouvre une session DB, la fournit à l'endpoint, puis la ferme
    automatiquement (même en cas d'erreur).

    Utilisation dans un endpoint :
        def my_endpoint(db: Session = Depends(get_db)):
            ...
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
