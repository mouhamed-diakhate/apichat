"""
Endpoint Dashboard - Statistiques d'usage (CDC §4.8)
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func

from app.db.session import get_db
from app.models.chat import ChatMessage
from app.models.user import User
from app.api.v1.endpoints.auth import get_current_user

router = APIRouter()

@router.get("/stats", summary="Tableau de bord de suivi (usage interne)")
def get_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Retourne les statistiques d'usage globales de l'assistant (CDC 4.8).
    - Nombre de conversations/messages traités
    - Taux d'escalade vers un humain
    - Répartition par langue et intention
    - Tickets créés
    """
    total_messages = db.query(ChatMessage).filter(ChatMessage.role == "user").count()
    total_escalades = db.query(ChatMessage).filter(ChatMessage.escalade == True, ChatMessage.role == "user").count()
    tickets_created = db.query(func.count(func.distinct(ChatMessage.ticket_id))).scalar() or 0
    
    # Intents
    intents_db = db.query(ChatMessage.intent, func.count(ChatMessage.id)).filter(ChatMessage.role == "user").group_by(ChatMessage.intent).all()
    top_intents = {k if k else "general": v for k, v in intents_db}

    # Languages
    languages_db = db.query(ChatMessage.language, func.count(ChatMessage.id)).filter(ChatMessage.role == "user").group_by(ChatMessage.language).all()
    languages = {k if k else "fr": v for k, v in languages_db}

    escalation_rate = round(total_escalades / total_messages, 2) if total_messages > 0 else 0.0

    return {
        "total_messages_recus": total_messages,
        "escalation_rate": escalation_rate,
        "top_intents": top_intents,
        "languages": languages,
        "tickets_created": tickets_created,
    }


@router.get(
    "/conversations",
    summary="Liste paginée des conversations récentes",
)
def get_conversations(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    intent: str | None = Query(None),
    escalade: bool | None = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Retourne les conversations récentes (messages assistant) paginées et filtrables.
    """
    query = (
        db.query(ChatMessage)
        .options(joinedload(ChatMessage.user))
        .filter(ChatMessage.role == "assistant")
    )

    if intent:
        query = query.filter(ChatMessage.intent == intent)
    if escalade is not None:
        query = query.filter(ChatMessage.escalade == escalade)

    total = query.count()
    messages = (
        query
        .order_by(ChatMessage.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    return {
        "items": [
            {
                "id": m.id,
                "user_email": m.user.email if m.user else "inconnu",
                "intent": m.intent,
                "escalade": m.escalade,
                "raison_escalade": m.raison_escalade,
                "ticket_id": m.ticket_id,
                "created_at": m.created_at.isoformat(),
                "message_preview": (m.content or "")[:120],
            }
            for m in messages
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }
