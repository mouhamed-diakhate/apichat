"""
Base déclarative SQLAlchemy partagée par tous les modèles.

Tous les modèles doivent hériter de cette Base pour être
détectés par SQLAlchemy et Alembic.
"""
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Classe de base pour tous les modèles SQLAlchemy."""
    pass
