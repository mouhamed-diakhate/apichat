"""Notifications internes destinees aux agents de supervision."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class AgentNotification(Base):
    """Une alerte persistante adressee a un agent pour une escalation client.

    Une contrainte d'unicite garantit qu'un meme message client escalade ne
    genere qu'une seule alerte par agent, meme si ses metadonnees sont
    enrichies plusieurs fois.
    """

    __tablename__ = "agent_notifications"
    __table_args__ = (
        UniqueConstraint(
            "recipient_user_id",
            "source_message_id",
            "type",
            name="uq_agent_notification_recipient_source_type",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    recipient_user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_message_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("chat_messages.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    type: Mapped[str] = mapped_column(String(40), nullable=False, default="escalation")
    title: Mapped[str] = mapped_column(String(180), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    ticket_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    is_read: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
    )

    recipient: Mapped["User"] = relationship("User", foreign_keys=[recipient_user_id])
    source_message: Mapped["ChatMessage"] = relationship(
        "ChatMessage",
        foreign_keys=[source_message_id],
    )

    def __repr__(self) -> str:
        return (
            "<AgentNotification "
            f"id={self.id} recipient={self.recipient_user_id} source={self.source_message_id}>"
        )
