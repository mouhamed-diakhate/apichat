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
                "session_id": m.session_id,
                "user_email": m.user.email if m.user else "inconnu",
                "user_name": (m.user.full_name if m.user else None) or "Client Invité",
                "intent": m.intent,
                "language": m.language or "fr",
                "escalade": m.escalade,
                "raison_escalade": m.raison_escalade,
                "ticket_id": m.ticket_id,
                "outils_utilises": m.outils_utilises,
                "created_at": m.created_at.isoformat(),
                "message_preview": (m.content or "")[:120],
            }
            for m in messages
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get(
    "/conversations/{msg_id}",
    summary="Détails complets d'une conversation et historique du fil",
)
def get_conversation_detail(
    msg_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Retourne le détail d'un échange et la liste complète des messages du fil (session).
    """
    target_msg = (
        db.query(ChatMessage)
        .options(joinedload(ChatMessage.user))
        .filter(ChatMessage.id == msg_id)
        .first()
    )
    if not target_msg:
        return {"error": "Conversation non trouvée"}

    # Récupérer l'ensemble de la discussion (fil de la session ou même utilisateur)
    if target_msg.session_id:
        thread_messages = (
            db.query(ChatMessage)
            .filter(ChatMessage.session_id == target_msg.session_id)
            .order_by(ChatMessage.created_at.asc())
            .all()
        )
    else:
        thread_messages = (
            db.query(ChatMessage)
            .filter(ChatMessage.user_id == target_msg.user_id)
            .order_by(ChatMessage.created_at.asc())
            .limit(30)
            .all()
        )

    client_info = {
        "email": target_msg.user.email if target_msg.user else "inconnu",
        "full_name": (target_msg.user.full_name if target_msg.user else None) or "Visiteur / Client TexMiles",
        "status": "Membre" if target_msg.user and target_msg.user.email != "invite@texmiles.sn" else "Visiteur Web / WhatsApp",
    }

    return {
        "id": target_msg.id,
        "session_id": target_msg.session_id,
        "client": client_info,
        "intent": target_msg.intent,
        "language": target_msg.language or "fr",
        "escalade": target_msg.escalade,
        "raison_escalade": target_msg.raison_escalade,
        "ticket_id": target_msg.ticket_id,
        "outils_utilises": target_msg.outils_utilises,
        "created_at": target_msg.created_at.isoformat(),
        "messages": [
            {
                "id": msg.id,
                "role": msg.role,
                "content": msg.content,
                "created_at": msg.created_at.isoformat(),
                "intent": msg.intent,
                "escalade": msg.escalade,
                "ticket_id": msg.ticket_id,
                "outils_utilises": msg.outils_utilises,
            }
            for msg in thread_messages
        ],
    }

