"""
Endpoints pour le chat avec IA et le routage Multi-Agents.
"""
import json

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.v1.endpoints.auth import get_current_user
from app.db.session import get_db
from app.models.chat import ChatMessage
from app.models.user import User
from app.schemas.chat import ChatMessageCreate, ChatMessageResponse
from app.services.ai_service import ai_service

router = APIRouter()


@router.post(
    "/message",
    response_model=ChatMessageResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Envoyer un message à l'assistant IA",
)
def send_message(
    message_data: ChatMessageCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> ChatMessage:
    """
    Envoie un message à l'assistant IA.
    
    L'assistant va :
    1. Détecter l'intention du message (Analytics).
    2. Récupérer l'historique et router vers l'Orchestrateur IA.
    3. Persister le message de l'utilisateur et la réponse de l'assistant (avec outils/escalade).
    4. Retourner la réponse enrichie.
    """
    # 1. Détection d'intention (Analytics - French only for now)
    intent = ai_service.detect_intent(message_data.content)
    language = "fr"

    # 2. Récupérer l'historique récent de l'utilisateur pour le contexte.
    #    On prend les 20 messages LES PLUS RÉCENTS (tri décroissant + limite),
    #    puis on les remet dans l'ordre chronologique pour l'orchestrateur.
    recents_desc = (
        db.query(ChatMessage)
        .filter(ChatMessage.user_id == current_user.id)
        .order_by(ChatMessage.created_at.desc())
        .limit(20)
        .all()
    )
    history_list = [{"role": m.role, "content": m.content} for m in reversed(recents_desc)]

    # 3. Enregistrer le message de l'utilisateur en base de données
    user_msg = ChatMessage(
        user_id=current_user.id,
        role="user",
        content=message_data.content,
        intent=intent,
        language=language
    )
    db.add(user_msg)

    # 4. Obtenir la réponse de l'Orchestrateur IA
    reply = ai_service.process_message(
        message=message_data.content,
        history=history_list
    )

    outils_json = json.dumps(reply.outils_utilises) if reply.outils_utilises else None

    # 5. Enregistrer le message de l'assistant en base de données
    #    (reply.texte = le texte de la réponse produite par l'orchestrateur)
    assistant_msg = ChatMessage(
        user_id=current_user.id,
        role="assistant",
        content=reply.texte,
        intent=intent,
        language=language,
        escalade=reply.escalade,
        raison_escalade=reply.raison_escalade,
        ticket_id=reply.ticket_id,
        outils_utilises=outils_json
    )
    db.add(assistant_msg)

    try:
        db.commit()
        db.refresh(assistant_msg)
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur d'enregistrement en base de données : {str(e)}"
        )

    return assistant_msg


@router.get(
    "/history",
    response_model=list[ChatMessageResponse],
    summary="Récupérer l'historique des conversations",
)
def get_chat_history(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> list[ChatMessage]:
    """
    Retourne la liste chronologique complète de tous les messages
    échangés par l'utilisateur connecté avec l'assistant IA.
    """
    messages = (
        db.query(ChatMessage)
        .filter(ChatMessage.user_id == current_user.id)
        .order_by(ChatMessage.created_at.asc())
        .all()
    )
    return messages
