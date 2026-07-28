"""
Schémas Pydantic pour le système de chat.
"""
from datetime import datetime
from pydantic import BaseModel, Field


class ChatMessageCreate(BaseModel):
    """Données pour envoyer un nouveau message dans le chat."""
    content: str = Field(..., min_length=1, description="Contenu textuel du message")

    model_config = {"str_strip_whitespace": True}


class ChatMessageResponse(BaseModel):
    """Représentation d'un message retourné au client."""
    id: int
    user_id: int
    role: str
    content: str
    intent: str | None = None
    language: str | None = None
    escalade: bool | None = None
    raison_escalade: str | None = None
    ticket_id: str | None = None
    outils_utilises: str | None = None
    session_id: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}
