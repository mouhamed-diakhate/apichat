"""
Modèle SQLAlchemy — Table `chat_messages`.
"""
import json
from datetime import datetime, timezone
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class ChatMessage(Base):
    """
    Représente un message de chat dans la base de données.

    Colonnes :
        id          - Clé primaire auto-incrémentée
        user_id     - Clé étrangère vers l'utilisateur auteur du message (ou lié à l'échange)
        role        - Rôle de l'expéditeur : 'user', 'assistant' ou 'system'
        content     - Contenu textuel du message
        intent      - Intention détectée (ex: 'faq', 'tracking', 'claim', 'general')
        language    - Langue détectée (ex: 'fr', 'wo', 'en')
        created_at  - Date de création (UTC)
    """
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    role: Mapped[str] = mapped_column(String(50), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    intent: Mapped[str | None] = mapped_column(String(100), nullable=True)
    language: Mapped[str | None] = mapped_column(String(10), nullable=True)
    escalade: Mapped[bool | None] = mapped_column(nullable=True, default=False)
    raison_escalade: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Cloture manuelle de l'escalade par un agent de supervision.
    handled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    handled_by_user_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    ticket_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    outils_utilises: Mapped[str | None] = mapped_column(Text, nullable=True)
    # JSON des passages réellement récupérés par le RAG (document, page, article,
    # score). On le stocke avec la réponse pour que l'historique reste auditable.
    sources_utilisees: Mapped[str | None] = mapped_column(Text, nullable=True)
    session_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relation vers l'utilisateur
    user: Mapped["User"] = relationship(
        "User",
        back_populates="chat_messages",
        foreign_keys=[user_id],
    )

    @property
    def sources(self) -> list[dict]:
        """Expose les sources RAG sous forme structurée dans les réponses API."""
        if not self.sources_utilisees:
            return []
        try:
            data = json.loads(self.sources_utilisees)
            return data if isinstance(data, list) else []
        except (TypeError, ValueError, json.JSONDecodeError):
            return []

    def __repr__(self) -> str:
        return f"<ChatMessage id={self.id} user_id={self.user_id} role={self.role!r} intent={self.intent!r}>"
