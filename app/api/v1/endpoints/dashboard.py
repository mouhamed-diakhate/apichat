"""
Endpoint Dashboard - Statistiques d'usage (CDC §4.8)
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.db.session import get_db
from app.models.chat import ChatMessage
from app.api.v1.endpoints.auth import get_current_user

router = APIRouter()

@router.get("/stats", summary="Tableau de bord de suivi (usage interne)")
def get_stats(db: Session = Depends(get_db)):
    """
    Retourne les statistiques d'usage globales de l'assistant (CDC 4.8).
    - Nombre de conversations/messages traités
    - Taux d'escalade vers un humain
    - Répartition par langue et intention
    - Tickets créés
    """
    total_messages = db.query(ChatMessage).filter(ChatMessage.role == "user").count()
    total_escalades = db.query(ChatMessage).filter(ChatMessage.escalade == True).count()
    tickets_created = db.query(ChatMessage).filter(ChatMessage.ticket_id != None).count()
    
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
