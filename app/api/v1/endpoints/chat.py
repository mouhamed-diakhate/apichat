"""Endpoints du chat IA et du parcours interactif."""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.v1.endpoints.auth import get_current_user, get_current_user_optional
from app.core.limiter import limiter
from app.db.session import get_db
from app.models.chat import ChatMessage
from app.models.user import User
from app.schemas.chat import ChatMessageCreate, ChatMessageResponse
from app.services.ai_service import ai_service
from app.services.conversation_capture import (
    capture_assistant_message,
    capture_inbound_message,
    enrich_inbound_message,
    get_or_create_guest_user,
    resolve_session_id,
)
from app.services.session_manager import _persist_session, process_interactive_step


logger = logging.getLogger(__name__)
router = APIRouter()


class InteractiveMessageRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=100)
    message: str = ""
    action_id: str | None = None


def _interactive_text(response: dict) -> str:
    """Ajoute les libelles de boutons au message conserve dans le transcript."""
    text = response.get("text") or ""
    buttons = response.get("buttons") or []
    labels = [button.get("label") for button in buttons if button.get("label")]
    if labels:
        return f"{text}\n\n" + "\n".join(f"- {label}" for label in labels)
    return text


def _safe_enrich_inbound(
    db: Session,
    message: ChatMessage | None,
    *,
    intent: str | None,
    language: str | None,
    escalade: bool | None = None,
    raison_escalade: str | None = None,
    ticket_id: str | None = None,
) -> None:
    """Enrichit sans jamais annuler le commit deja fait a la reception."""
    try:
        enrich_inbound_message(
            db,
            message,
            intent=intent,
            language=language,
            escalade=escalade,
            raison_escalade=raison_escalade,
            ticket_id=ticket_id,
        )
    except Exception:
        db.rollback()
        logger.exception("Impossible de mettre a jour les metadonnees du message entrant")


@router.post(
    "/message",
    response_model=ChatMessageResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Envoyer un message a l'assistant IA (mode public / authentifie)",
)
@limiter.limit("60/minute")
def send_message(
    request: Request,
    message_data: ChatMessageCreate,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
) -> ChatMessage | dict:
    """Capture le message client avant toute operation potentiellement lente."""
    try:
        if current_user is None:
            current_user = get_or_create_guest_user(db)
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur de creation du client visiteur : {exc}",
        ) from exc

    session_id = resolve_session_id(message_data.session_id, channel="web")

    # L'historique reste isole a la conversation, y compris pour le compte invite.
    recents_desc = (
        db.query(ChatMessage)
        .filter(
            ChatMessage.user_id == current_user.id,
            ChatMessage.session_id == session_id,
        )
        .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc())
        .limit(20)
        .all()
    )
    history_list = [{"role": item.role, "content": item.content} for item in reversed(recents_desc)]

    try:
        inbound = capture_inbound_message(
            db,
            user=current_user,
            content=message_data.content,
            session_id=session_id,
        )
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur de capture du message client : {exc}",
        ) from exc

    # Si l'IA leve une erreur, le message entrant ci-dessus reste deliberement
    # disponible dans le tableau de bord avec le statut "en attente".
    reply, intent = ai_service.process_message_with_intent(
        message=message_data.content,
        history=history_list,
    )
    language = "fr"

    _safe_enrich_inbound(
        db,
        inbound,
        intent=intent,
        language=language,
        escalade=reply.escalade,
        raison_escalade=reply.raison_escalade,
        ticket_id=reply.ticket_id,
    )

    try:
        return capture_assistant_message(
            db,
            user=current_user,
            content=reply.texte,
            session_id=session_id,
            intent=intent,
            language=language,
            escalade=reply.escalade,
            raison_escalade=reply.raison_escalade,
            ticket_id=reply.ticket_id,
            outils_utilises=reply.outils_utilises,
            sources=reply.sources,
        )
    except Exception as exc:
        db.rollback()
        # Le message client a deja ete capture et enrichi dans des transactions
        # precedentes : il ne doit pas etre perdu si la reponse ne peut etre ecrite.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur d'enregistrement de la reponse : {exc}",
        ) from exc


@router.get(
    "/history",
    response_model=list[ChatMessageResponse],
    summary="Recuperer l'historique des conversations",
)
def get_chat_history(
    session_id: str | None = Query(None, max_length=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[ChatMessage]:
    """Retourne l'historique du client, eventuellement limite a un fil."""
    query = db.query(ChatMessage).filter(ChatMessage.user_id == current_user.id)
    if session_id:
        query = query.filter(ChatMessage.session_id == session_id)
    return query.order_by(ChatMessage.created_at.asc(), ChatMessage.id.asc()).all()


@router.post("/interactive", summary="Traiter un message interactif (Langue -> Menu -> Agent IA)")
@limiter.limit("30/minute")
def interactive_chat(
    request: Request,
    payload: InteractiveMessageRequest,
    db: Session = Depends(get_db),
):
    """Traite le parcours guide en conservant chaque entree des sa reception."""
    session_id = resolve_session_id(payload.session_id, channel="interactive")
    # Les clients WhatsApp envoient parfois uniquement l'action; dans ce cas la
    # valeur technique reste preferable a une absence complete de trace.
    display_message = (payload.message or "").strip() or (payload.action_id or "").strip()
    guest_user: User | None = None
    inbound: ChatMessage | None = None

    try:
        guest_user = get_or_create_guest_user(db)
        inbound = capture_inbound_message(
            db,
            user=guest_user,
            content=display_message,
            session_id=session_id,
            intent="menu",
        )
    except Exception:
        db.rollback()
        logger.exception("Impossible de capturer le message interactif entrant")

    # La machine a etat est executee seulement apres la capture durable.
    response, session = process_interactive_step(
        session_id=session_id,
        user_input=payload.message,
        action_id=payload.action_id,
        db=db,
    )
    _persist_session(session, db=db)
    language = session.language or "fr"

    if response is not None:
        intent = response.get("intent") or session.selected_service or "menu"
        ticket_id = response.get("ticket_id") or response.get("reference")
        escalade = bool(response.get("escalade", False))
        _safe_enrich_inbound(
            db,
            inbound,
            intent=intent,
            language=language,
            escalade=escalade,
            raison_escalade="Transmission a un agent humain" if escalade else None,
            ticket_id=ticket_id,
        )

        try:
            if guest_user is None:
                guest_user = get_or_create_guest_user(db)
            capture_assistant_message(
                db,
                user=guest_user,
                content=_interactive_text(response),
                session_id=session_id,
                intent=intent,
                language=language,
                escalade=escalade,
                raison_escalade="Transmission a un agent humain" if escalade else None,
                ticket_id=ticket_id,
            )
        except Exception:
            db.rollback()
            logger.exception("Impossible de sauvegarder la reponse interactive")
        return response

    # Etat AGENT_ACTIVE : la capture est deja engagee, puis seulement l'IA est
    # appelee. Un timeout IA laisse donc une conversation visible a l'equipe.
    history_list = session.history[-10:] if session.history else []
    reply = ai_service.process_message(
        message=payload.message,
        history=history_list,
        language=language,
        session_id=session_id,
    )

    session.history.append({"role": "user", "content": payload.message})
    session.history.append({"role": "assistant", "content": reply.texte})
    try:
        _persist_session(session, db=db)
    except Exception:
        logger.exception("Impossible de sauvegarder la session interactive")

    intent = session.selected_service or "general"
    if payload.message and len(payload.message.strip()) > 3:
        detected = ai_service.detect_intent(payload.message)
        if detected != "general" or not session.selected_service:
            intent = detected

    _safe_enrich_inbound(
        db,
        inbound,
        intent=intent,
        language=language,
        escalade=reply.escalade,
        raison_escalade=reply.raison_escalade,
        ticket_id=reply.ticket_id,
    )
    try:
        if guest_user is None:
            guest_user = get_or_create_guest_user(db)
        capture_assistant_message(
            db,
            user=guest_user,
            content=reply.texte,
            session_id=session_id,
            intent=intent,
            language=language,
            escalade=reply.escalade,
            raison_escalade=reply.raison_escalade,
            ticket_id=reply.ticket_id,
            outils_utilises=reply.outils_utilises,
            sources=reply.sources,
        )
    except Exception:
        db.rollback()
        logger.exception("Impossible de sauvegarder la reponse IA interactive")

    return {
        "text": reply.texte,
        "buttons": [{"id": "menu_reset", "label": "Retour au menu"}],
        "state": session.state,
        "language": session.language,
        "escalade": reply.escalade,
        "ticket_id": reply.ticket_id,
    }
