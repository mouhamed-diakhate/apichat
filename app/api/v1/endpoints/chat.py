"""
Endpoints pour le chat avec IA et le routage Multi-Agents.
"""
import json

from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.v1.endpoints.auth import get_current_user, get_current_user_optional
from app.db.session import get_db
from app.models.chat import ChatMessage
from app.models.user import User
from app.schemas.chat import ChatMessageCreate, ChatMessageResponse
from app.services.ai_service import ai_service
from app.services.session_manager import process_interactive_step

router = APIRouter()


class InteractiveMessageRequest(BaseModel):
    session_id: str
    message: str = ""
    action_id: str | None = None


@router.post(
    "/message",
    response_model=ChatMessageResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Envoyer un message à l'assistant IA (mode public / authentifié)",
)
def send_message(
    message_data: ChatMessageCreate,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional)
) -> ChatMessage:
    """
    Envoie un message à l'assistant IA. Accessible aux visiteurs anonymes et aux membres.
    
    L'assistant va :
    1. Détecter l'intention du message (Analytics).
    2. Récupérer l'historique et router vers l'Orchestrateur IA.
    3. Persister le message de l'utilisateur et la réponse de l'assistant (avec outils/escalade).
    4. Retourner la réponse enrichie.
    """
    # Si utilisateur invité (non connecté), associer à l'utilisateur système "Invité"
    if current_user is None:
        guest_user = db.query(User).filter(User.email == "invite@texmiles.sn").first()
        if not guest_user:
            guest_user = User(
                email="invite@texmiles.sn",
                hashed_password="guest_no_login",
                full_name="Visiteur Invité",
                is_active=True,
                is_superuser=False,
            )
            db.add(guest_user)
            db.commit()
            db.refresh(guest_user)
        current_user = guest_user
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


@router.post("/interactive", summary="Traiter un message interactif (Langue -> Menu -> Agent IA)")
def interactive_chat(
    payload: InteractiveMessageRequest,
    db: Session = Depends(get_db)
):
    """
    Endpoint de test local pour le parcours interactif :
    1. Choix de la langue (Français 🇫🇷 / Wolof 🇸🇳 / English 🇬🇧)
    2. Menu principal (1. Suivi colis, 2. Réclamation, 3. FAQ)
    3. Traitement par l'Agent IA (avec outils & prompts adaptés)
    4. Enregistrement en BD pour alimenter le Dashboard en temps réel.
    """
    response, session = process_interactive_step(
        session_id=payload.session_id,
        user_input=payload.message,
        action_id=payload.action_id
    )

    if response is not None:
        return response

    # Si session.state == AGENT_ACTIVE : appel au moteur d'intelligence IA
    history_list = session.history[-10:] if session.history else []
    language = session.language or "fr"
    
    reply = ai_service.process_message(
        message=payload.message,
        history=history_list,
        language=language
    )

    session.history.append({"role": "user", "content": payload.message})
    session.history.append({"role": "assistant", "content": reply.texte})

    # Persistance en base de données pour alimenter le Dashboard
    try:
        guest_user = db.query(User).filter(User.email == "invite@texmiles.sn").first()
        if not guest_user:
            guest_user = User(
                email="invite@texmiles.sn",
                hashed_password="guest_no_login",
                full_name="Visiteur Invité",
                is_active=True,
                is_superuser=False,
            )
            db.add(guest_user)
            db.commit()
            db.refresh(guest_user)

        intent = session.selected_service or "general"
        if payload.message and len(payload.message.strip()) > 3:
            try:
                intent = ai_service.detect_intent(payload.message)
            except Exception:
                pass

        user_msg = ChatMessage(
            user_id=guest_user.id,
            role="user",
            content=payload.message,
            intent=intent,
            language=language
        )
        db.add(user_msg)

        outils_json = json.dumps(reply.outils_utilises) if reply.outils_utilises else None
        assistant_msg = ChatMessage(
            user_id=guest_user.id,
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
        db.commit()
    except Exception as e:
        db.rollback()
        print(f"[interactive_chat] Erreur de persistance DB : {e}")

    return {
        "text": reply.texte,
        "buttons": [{"id": "menu_reset", "label": "🔄 Retour au Menu"}],
        "state": session.state,
        "language": session.language,
        "escalade": reply.escalade,
        "ticket_id": reply.ticket_id
    }

