"""
Modèle SQLAlchemy — Table `conversation_sessions`.

Stocke l'état de chaque session conversationnelle (langue, état,
historique, données du parcours guidé) pour qu'il survive aux
redémarrages du serveur.
"""
from datetime import datetime, timezone

from sqlalchemy import DateTime, String, Text, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ConversationSession(Base):
    """
    Représente une session conversationnelle persistée en base.

    Colonnes :
        session_id      - Identifiant unique de session (clé naturelle)
        state           - État courant de la machine à états (ex: AWAITING_MENU)
        language        - Langue choisie : 'fr', 'en', 'wo', 'ar'
        selected_mode   - Mode choisi : 'write' ou 'call'
        selected_service- Service sélectionné dans le menu
        history_json    - Historique des échanges sérialisé en JSON
        data_json       - Données du parcours guidé sérialisées en JSON
        created_at      - Date de création (UTC)
        updated_at      - Date de dernière mise à jour (UTC)
    """
    __tablename__ = "conversation_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    session_id: Mapped[str] = mapped_column(String(200), unique=True, nullable=False, index=True)
    state: Mapped[str] = mapped_column(String(50), nullable=False, default="AWAITING_LANG")
    language: Mapped[str | None] = mapped_column(String(10), nullable=True)
    selected_mode: Mapped[str | None] = mapped_column(String(20), nullable=True)
    selected_service: Mapped[str | None] = mapped_column(String(50), nullable=True)
    history_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    data_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    def __repr__(self) -> str:
        return f"<ConversationSession session_id={self.session_id!r} state={self.state!r} lang={self.language!r}>"
