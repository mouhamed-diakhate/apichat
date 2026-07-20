"""
Endpoints pour le chat avec IA et le routage Multi-Agents.
"""
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
    Envoie un message à l'assistant IA (Ollama/Qwen).
    
    L'assistant va :
    1. Détecter la langue et l'intention du message.
    2. Router le message vers l'agent adéquat (Superviseur).
    3. Persister le message de l'utilisateur et la réponse de l'assistant en base de données.
    4. Retourner la réponse générée.
    """
    # 1. Détection d'intention et de langue
    analysis = ai_service.detect_intent_and_language(message_data.content)
    intent = analysis.get("intent", "general")
    language = analysis.get("language", "fr")

    # 2. Récupérer l'historique récent de l'utilisateur pour le contexte
    history_db = (
        db.query(ChatMessage)
        .filter(ChatMessage.user_id == current_user.id)
        .order_by(ChatMessage.created_at.asc())
        .limit(20)
        .all()
    )
    history_list = [{"role": msg.role, "content": msg.content} for msg in history_db]

    # 3. Enregistrer le message de l'utilisateur en base de données
    user_msg = ChatMessage(
        user_id=current_user.id,
        role="user",
        content=message_data.content,
        intent=intent,
        language=language
    )
    db.add(user_msg)

    # 4. Obtenir la réponse de l'Agent Superviseur
    assistant_reply = ai_service.supervisor_route(
        intent=intent,
        message=message_data.content,
        history=history_list,
        language=language
    )

    # 5. Enregistrer le message de l'assistant en base de données
    assistant_msg = ChatMessage(
        user_id=current_user.id,
        role="assistant",
        content=assistant_reply,
        intent=intent,
        language=language
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
