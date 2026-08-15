"""
Modèle SQLAlchemy — Table `csat_ratings`.

Stocke les notes de satisfaction client (1 à 5 étoiles).
Indépendant de la table chat_messages pour survivre aux purges.
"""
from datetime import datetime, timezone
from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class CsatRating(Base):
    """
    Note de satisfaction client en fin de conversation.

    Colonnes :
        id         - Clé primaire auto-incrémentée
        session_id - Identifiant de la session (téléphone WhatsApp ou session web)
        score      - Note de 1 à 5 (⭐)
        language   - Langue de la conversation
        channel    - Canal (whatsapp, web)
        created_at - Date de création (UTC)
    """
    __tablename__ = "csat_ratings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    session_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    language: Mapped[str | None] = mapped_column(String(10), nullable=True)
    channel: Mapped[str | None] = mapped_column(String(20), nullable=True, default="web")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    def __repr__(self) -> str:
        return f"<CsatRating id={self.id} session={self.session_id} score={self.score}>"
