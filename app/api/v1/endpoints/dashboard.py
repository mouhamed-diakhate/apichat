"""API de supervision des conversations clients."""
from collections import defaultdict
from datetime import date, datetime, time, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload

from app.api.v1.endpoints.auth import get_current_user
from app.db.session import get_db
from app.models.chat import ChatMessage
from app.models.notification import AgentNotification
from app.models.user import User


router = APIRouter()


@router.get("/stats", summary="Tableau de bord de suivi (usage interne)")
def get_stats(
    start_date: date | None = Query(
        None,
        description="Debut de periode inclusif (YYYY-MM-DD, UTC)",
    ),
    end_date: date | None = Query(
        None,
        description="Fin de periode inclusive (YYYY-MM-DD, UTC)",
    ),
    start_at: datetime | None = Query(
        None,
        description="Debut de periode inclusif ISO-8601 (alternative a start_date)",
    ),
    end_at: datetime | None = Query(
        None,
        description="Fin de periode inclusive ISO-8601 (alternative a end_date)",
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Retourne des indicateurs calcules sur des conversations distinctes.

    Une conversation est incluse lorsque son dernier message client appartient a
    la periode demandee. Les escalades sont intentionnellement lues sur les
    reponses ``assistant`` : c'est la reponse IA qui demande le relais humain.
    """
    period_start, period_end = _resolve_period_bounds(
        start_date=start_date,
        end_date=end_date,
        start_at=start_at,
        end_at=end_at,
    )

    # Le chargement de l'historique complet permet de connaitre l'escalade et
    # la cloture d'un fil, meme si la reponse IA ou l'action humaine a eu lieu
    # juste avant/apres les bornes de la periode du message client.
    messages = (
        db.query(ChatMessage)
        .order_by(ChatMessage.created_at.asc(), ChatMessage.id.asc())
        .all()
    )
    threads = _threads_for_period(messages, period_start, period_end)
    metrics = _build_dashboard_metrics(
        threads,
        period_start=period_start,
        period_end=period_end,
    )
    return metrics


def _as_utc(value: datetime) -> datetime:
    """Normalise les dates SQL (SQLite peut perdre l'information de fuseau)."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _serialize_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    return _as_utc(value).isoformat().replace("+00:00", "Z")


def _resolve_period_bounds(
    *,
    start_date: date | None = None,
    end_date: date | None = None,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
) -> tuple[datetime | None, datetime | None]:
    """Construit des bornes UTC inclusives et refuse les requetes ambigues."""
    if start_date is not None and start_at is not None:
        raise HTTPException(
            status_code=422,
            detail="Utilisez start_date ou start_at, pas les deux",
        )
    if end_date is not None and end_at is not None:
        raise HTTPException(
            status_code=422,
            detail="Utilisez end_date ou end_at, pas les deux",
        )

    period_start = (
        _as_utc(start_at)
        if start_at is not None
        else (
            datetime.combine(start_date, time.min, tzinfo=timezone.utc)
            if start_date is not None
            else None
        )
    )
    # Une date seule inclut toute la journee demandee, jusqu'a 23:59:59.999999.
    period_end = (
        _as_utc(end_at)
        if end_at is not None
        else (
            datetime.combine(end_date, time.max, tzinfo=timezone.utc)
            if end_date is not None
            else None
        )
    )
    if period_start is not None and period_end is not None and period_start > period_end:
        raise HTTPException(
            status_code=422,
            detail="La date de debut doit etre anterieure ou egale a la date de fin",
        )
    return period_start, period_end


def _apply_period_filter(query, start_at: datetime | None, end_at: datetime | None):
    """Applique les bornes inclusives a une requete de messages reutilisable."""
    if start_at is not None:
        query = query.filter(ChatMessage.created_at >= start_at)
    if end_at is not None:
        query = query.filter(ChatMessage.created_at <= end_at)
    return query


def _is_within_period(
    value: datetime,
    start_at: datetime | None,
    end_at: datetime | None,
) -> bool:
    current = _as_utc(value)
    return (
        (start_at is None or current >= start_at)
        and (end_at is None or current <= end_at)
    )


def _group_conversation_messages(messages: list[ChatMessage]) -> list[list[ChatMessage]]:
    """Groupe les messages par client/session, sans melanger les invites."""
    grouped: dict[tuple[int, str], list[ChatMessage]] = defaultdict(list)
    for message in messages:
        grouped[_conversation_key(message)].append(message)
    return list(grouped.values())


def _threads_for_period(
    messages: list[ChatMessage],
    start_at: datetime | None,
    end_at: datetime | None,
) -> list[list[ChatMessage]]:
    """Retient les fils dont le dernier message client tombe dans la periode.

    Les fils sont ensuite conserves dans leur integralite. Ainsi, le calcul
    d'une escalade (reponse assistant) et du traitement humain reste correct
    quand ces evenements bordent la periode choisie.
    """
    result: list[list[ChatMessage]] = []
    for thread in _group_conversation_messages(messages):
        summary = _conversation_summary(thread)
        if summary is None:
            continue
        if _is_within_period(summary["latest_user"].created_at, start_at, end_at):
            result.append(thread)
    return result


def _thread_metric(thread: list[ChatMessage]) -> dict | None:
    """Calcule les informations de supervision d'un fil unique."""
    summary = _conversation_summary(thread)
    if summary is None:
        return None

    assistant_escalations = sorted(
        [
            message
            for message in thread
            if message.role == "assistant" and bool(message.escalade)
        ],
        key=lambda message: (_as_utc(message.created_at), message.id),
    )
    escalation_at = (
        _as_utc(assistant_escalations[0].created_at)
        if assistant_escalations
        else None
    )
    handling_times = sorted(
        [
            _as_utc(message.handled_at)
            for message in thread
            if message.role == "user" and message.handled_at is not None
        ]
    )
    # Une cloture est liee a une escalade seulement si elle intervient apres
    # sa reponse IA. Cela exclut les anciennes donnees cloturees avant le
    # nouvel evenement d'escalade.
    resolution_at = next(
        (
            handled_at
            for handled_at in handling_times
            if escalation_at is not None and handled_at >= escalation_at
        ),
        None,
    )
    human_response_seconds = (
        (resolution_at - escalation_at).total_seconds()
        if resolution_at is not None and escalation_at is not None
        else None
    )
    # Une conversation non escaladee n'est resolue de facon autonome que
    # lorsqu'une reponse IA a effectivement ete enregistree. Un simple message
    # entrant encore en attente ne doit pas gonfler ce taux.
    autonomous_resolution = (
        summary["latest_response"] is not None and not bool(assistant_escalations)
    )
    human_resolution = resolution_at is not None

    latest_user: ChatMessage = summary["latest_user"]
    return {
        "summary": summary,
        "intent": latest_user.intent or "general",
        "language": latest_user.language or "fr",
        "anchor_at": _as_utc(latest_user.created_at),
        "is_escalated": bool(assistant_escalations),
        "assistant_escalation_count": len(assistant_escalations),
        "escalation_at": escalation_at,
        "escalation_reason": (
            assistant_escalations[0].raison_escalade if assistant_escalations else None
        ),
        "is_autonomously_resolved": autonomous_resolution,
        "is_human_resolved": human_resolution,
        "is_resolved": autonomous_resolution or human_resolution,
        "resolution_at": resolution_at,
        "human_response_seconds": human_response_seconds,
        "ticket_ids": {message.ticket_id for message in thread if message.ticket_id},
    }


def _build_dashboard_metrics(
    threads: list[list[ChatMessage]],
    *,
    period_start: datetime | None,
    period_end: datetime | None,
) -> dict:
    """Produit le contrat des KPIs a partir de fils deja filtres par periode."""
    metric_threads: list[tuple[dict, list[ChatMessage]]] = []
    for thread in threads:
        metric = _thread_metric(thread)
        if metric is not None:
            metric_threads.append((metric, thread))

    metrics = [metric for metric, _thread in metric_threads]
    total_conversations = len(metrics)
    escalated = [metric for metric in metrics if metric["is_escalated"]]
    human_resolved = [metric for metric in escalated if metric["is_human_resolved"]]
    autonomous_resolved = [
        metric for metric in metrics if metric["is_autonomously_resolved"]
    ]
    resolved = [metric for metric in metrics if metric["is_resolved"]]

    intents: dict[str, int] = defaultdict(int)
    languages: dict[str, int] = defaultdict(int)
    resolution_details: dict[str, dict[str, int]] = defaultdict(
        lambda: {
            "total_conversations": 0,
            "escalated_conversations": 0,
            "resolved_conversations": 0,
            "autonomously_resolved_conversations": 0,
            "human_resolved_conversations": 0,
        }
    )
    tickets: set[str] = set()
    total_messages = 0
    for metric, thread in metric_threads:
        # Cette boucle conserve le nombre de messages entrants historique tout
        # en faisant des taux sur les conversations distinctes.
        intent = metric["intent"]
        language = metric["language"]
        intents[intent] += 1
        languages[language] += 1
        detail = resolution_details[intent]
        detail["total_conversations"] += 1
        if metric["is_escalated"]:
            detail["escalated_conversations"] += 1
        if metric["is_resolved"]:
            detail["resolved_conversations"] += 1
        if metric["is_autonomously_resolved"]:
            detail["autonomously_resolved_conversations"] += 1
        if metric["is_human_resolved"]:
            detail["human_resolved_conversations"] += 1
        tickets.update(metric["ticket_ids"])
        total_messages += sum(
            1
            for message in thread
            if message.role == "user"
            and _is_within_period(message.created_at, period_start, period_end)
        )

    escalation_rate = len(escalated) / total_conversations if total_conversations else 0.0
    autonomous_resolution_rate = (
        len(autonomous_resolved) / total_conversations if total_conversations else 0.0
    )
    escalation_resolution_rate = (
        len(human_resolved) / len(escalated) if escalated else 0.0
    )
    response_delays = [
        metric["human_response_seconds"]
        for metric in human_resolved
        if metric["human_response_seconds"] is not None
    ]
    average_response_seconds = (
        sum(response_delays) / len(response_delays) if response_delays else None
    )

    resolution_rate_by_intent = {
        intent: round(
            details["resolved_conversations"] / details["total_conversations"],
            4,
        )
        if details["total_conversations"]
        else 0.0
        for intent, details in resolution_details.items()
    }
    resolution_by_intent = {
        intent: {
            **details,
            "resolution_rate": resolution_rate_by_intent[intent],
        }
        for intent, details in resolution_details.items()
    }

    return {
        "period": {
            "start_at": _serialize_datetime(period_start),
            "end_at": _serialize_datetime(period_end),
            "anchor": "latest_user_message",
        },
        # Compatibilite avec le KPI historique, qui affiche toujours les
        # messages entrants. Les taux et les repartitions sont eux calcules
        # par conversation, ce qui evite de surponderer un client bavard.
        "total_messages_recus": total_messages,
        "total_conversations": total_conversations,
        "escalated_conversations": len(escalated),
        "resolved_conversations": len(resolved),
        "autonomously_resolved_conversations": len(autonomous_resolved),
        "human_resolved_conversations": len(human_resolved),
        "assistant_escalation_count": sum(
            metric["assistant_escalation_count"] for metric in metrics
        ),
        "escalation_rate": round(escalation_rate, 4),
        "autonomous_resolution_rate": round(autonomous_resolution_rate, 4),
        "escalation_resolution_rate": round(escalation_resolution_rate, 4),
        "resolution_rate_by_intent": resolution_rate_by_intent,
        "resolution_by_intent": resolution_by_intent,
        "average_human_response_seconds": (
            round(average_response_seconds, 2)
            if average_response_seconds is not None
            else None
        ),
        "average_human_response_minutes": (
            round(average_response_seconds / 60, 2)
            if average_response_seconds is not None
            else None
        ),
        "human_response_sample_size": len(response_delays),
        "top_intents": dict(intents),
        "languages": dict(languages),
        "tickets_created": len(tickets),
    }


def _notification_item(notification: AgentNotification) -> dict:
    """Serialise une alerte pour la cloche du tableau de bord."""
    source = notification.source_message
    source_user = source.user if source else None
    phone_info = _extract_phone(
        source_user.email if source_user else None,
        source.session_id if source else None,
        source_user.full_name if source_user else None,
    )
    return {
        "id": notification.id,
        "type": notification.type,
        "title": notification.title,
        "body": notification.body,
        "ticket_id": notification.ticket_id,
        "is_read": notification.is_read,
        "read_at": notification.read_at.isoformat() if notification.read_at else None,
        "created_at": notification.created_at.isoformat(),
        # L'identifiant du message client ouvre le fil deja connu du drawer.
        "conversation_id": notification.source_message_id,
        "client_display": phone_info["display"],
    }


@router.get("/notifications", summary="Notifications d'escalade de l'agent connecte")
def get_notifications(
    unread_only: bool = Query(False),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Retourne les alertes de l'agent, sans exposer celles des autres comptes."""
    query = (
        db.query(AgentNotification)
        .options(
            joinedload(AgentNotification.source_message).joinedload(ChatMessage.user),
        )
        .filter(AgentNotification.recipient_user_id == current_user.id)
    )
    unread_count = query.filter(AgentNotification.is_read.is_(False)).count()
    if unread_only:
        query = query.filter(AgentNotification.is_read.is_(False))

    notifications = query.order_by(AgentNotification.created_at.desc(), AgentNotification.id.desc()).limit(limit).all()
    return {
        "items": [_notification_item(notification) for notification in notifications],
        "unread_count": unread_count,
    }


@router.post(
    "/notifications/{notification_id}/read",
    summary="Marquer une notification d'escalade comme lue",
)
def mark_notification_as_read(
    notification_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Accuse lecture de l'alerte uniquement pour son destinataire."""
    notification = (
        db.query(AgentNotification)
        .filter(
            AgentNotification.id == notification_id,
            AgentNotification.recipient_user_id == current_user.id,
        )
        .first()
    )
    if notification is None:
        raise HTTPException(status_code=404, detail="Notification introuvable")

    if not notification.is_read:
        notification.is_read = True
        notification.read_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(notification)

    return {
        "id": notification.id,
        "is_read": notification.is_read,
        "read_at": notification.read_at.isoformat() if notification.read_at else None,
    }


def _extract_phone(email: str | None, session_id: str | None, full_name: str | None) -> dict:
    """Extrait un numero WhatsApp lorsqu'il est disponible."""
    raw = None
    if email and email.startswith("wa_"):
        raw = email.removeprefix("wa_").removesuffix("@texmiles.sn").strip()
    elif full_name and "WhatsApp" in full_name:
        raw = full_name.replace("Client WhatsApp ", "").replace("+", "").strip()

    if raw and len(raw) >= 8:
        clean_raw = raw.replace("+", "").replace(" ", "")
        formatted = (
            f"+221 {clean_raw[3:5]} {clean_raw[5:8]} {clean_raw[8:10]} {clean_raw[10:12]}"
            if len(clean_raw) == 12 and clean_raw.startswith("221")
            else f"+{clean_raw}"
        )
        return {"raw": clean_raw, "formatted": formatted, "display": f"WhatsApp {formatted}"}

    if email == "invite@texmiles.sn":
        suffix = f" ({session_id})" if session_id else ""
        return {"raw": None, "formatted": None, "display": f"Visiteur Web{suffix}"}

    return {"raw": None, "formatted": None, "display": full_name or email or "Client invite"}


def _conversation_key(message: ChatMessage) -> tuple[int, str]:
    """Isole un fil par client et session; les anciennes donnees restent lisibles."""
    return message.user_id, (message.session_id or "__legacy_without_session__")


def _conversation_summary(messages: list[ChatMessage]) -> dict | None:
    """Retourne l'etat d'un fil dont le message client est l'ancre."""
    user_messages = [message for message in messages if message.role == "user"]
    if not user_messages:
        return None

    first_user = min(user_messages, key=lambda message: message.id)
    latest_user = max(user_messages, key=lambda message: message.id)
    later_responses = [
        message
        for message in messages
        if message.role == "assistant" and message.id > latest_user.id
    ]
    latest_response = max(later_responses, key=lambda message: message.id, default=None)
    state_message = latest_response or latest_user
    escalade = bool(state_message.escalade)
    # La cloture est rattachee au dernier message client. Ainsi, un nouveau
    # message du client dans le meme fil rouvre naturellement le traitement.
    handled = bool(latest_user.handled_at)

    if handled:
        conversation_status = "traite"
    elif escalade:
        conversation_status = "escalade"
    elif latest_response is not None:
        conversation_status = "repondu"
    else:
        conversation_status = "en_attente"

    return {
        "first_user": first_user,
        "latest_user": latest_user,
        "latest_response": latest_response,
        "state_message": state_message,
        "status": conversation_status,
        "escalade": escalade,
        "handled": handled,
    }


def _conversation_item(summary: dict) -> dict:
    """Transforme un resume de fil en ligne consommee par le tableau de bord."""
    latest_user: ChatMessage = summary["latest_user"]
    first_user: ChatMessage = summary["first_user"]
    latest_response: ChatMessage | None = summary["latest_response"]
    state_message: ChatMessage = summary["state_message"]
    user = latest_user.user
    email = user.email if user else "inconnu"
    name = (user.full_name if user else None) or "Client invite"
    phone_info = _extract_phone(email, latest_user.session_id, name)

    return {
        # L'identifiant est celui du dernier message client pour ouvrir le bon fil.
        "id": latest_user.id,
        "session_id": latest_user.session_id,
        "user_email": email,
        "user_name": name,
        "user_phone": phone_info["formatted"],
        "raw_phone": phone_info["raw"],
        "client_display": phone_info["display"],
        "intent": latest_user.intent or state_message.intent or "general",
        "language": latest_user.language or state_message.language or "fr",
        "status": summary["status"],
        "has_response": latest_response is not None,
        "escalade": summary["escalade"],
        "handled_at": latest_user.handled_at.isoformat() if latest_user.handled_at else None,
        "handled_by_user_id": latest_user.handled_by_user_id,
        "raison_escalade": state_message.raison_escalade,
        "ticket_id": state_message.ticket_id,
        "outils_utilises": state_message.outils_utilises,
        "sources": state_message.sources,
        # La ligne est volontairement datee et previsualisee par le client,
        # jamais par la reponse IA.
        "created_at": latest_user.created_at.isoformat(),
        "started_at": first_user.created_at.isoformat(),
        "response_at": latest_response.created_at.isoformat() if latest_response else None,
        "message_preview": (latest_user.content or "")[:120],
        "response_preview": (latest_response.content or "")[:120] if latest_response else None,
    }


def _build_conversations(messages: list[ChatMessage]) -> list[dict]:
    items = []
    for thread in _group_conversation_messages(messages):
        summary = _conversation_summary(thread)
        if summary is not None:
            items.append(_conversation_item(summary))
    return items


def _thread_messages(db: Session, target_msg: ChatMessage) -> list[ChatMessage]:
    """Retourne uniquement le fil client/session du message cible."""
    query = db.query(ChatMessage).filter(ChatMessage.user_id == target_msg.user_id)
    if target_msg.session_id:
        query = query.filter(ChatMessage.session_id == target_msg.session_id)
    else:
        query = query.filter(ChatMessage.session_id.is_(None))
    return query.order_by(ChatMessage.id.asc()).all()


def _latest_thread_for_action(
    db: Session,
    msg_id: int,
) -> tuple[ChatMessage, list[ChatMessage], dict]:
    """Charge un fil et refuse de modifier un message client devenu obsolète."""
    target_msg = (
        db.query(ChatMessage)
        .options(joinedload(ChatMessage.user))
        .filter(ChatMessage.id == msg_id)
        .first()
    )
    if target_msg is None:
        raise HTTPException(status_code=404, detail="Conversation non trouvee")

    messages = _thread_messages(db, target_msg)
    summary = _conversation_summary(messages)
    if summary is None:
        raise HTTPException(status_code=404, detail="Conversation non trouvee")
    if target_msg.id != summary["latest_user"].id:
        raise HTTPException(
            status_code=409,
            detail="Cette conversation a recu un message plus recent. Ouvrez le dernier message client.",
        )
    return target_msg, messages, summary


def _mark_current_agent_notification_read(
    db: Session,
    *,
    user_id: int,
    source_message_id: int,
    now: datetime,
) -> None:
    """Accuse l'alerte de l'agent qui vient de prendre le fil."""
    (
        db.query(AgentNotification)
        .filter(
            AgentNotification.recipient_user_id == user_id,
            AgentNotification.source_message_id == source_message_id,
            AgentNotification.is_read.is_(False),
        )
        .update(
            {
                AgentNotification.is_read: True,
                AgentNotification.read_at: now,
            },
            synchronize_session=False,
        )
    )


def _action_state_response(summary: dict) -> dict:
    """Retour commun des actions de cloture."""
    latest_user: ChatMessage = summary["latest_user"]
    return {
        "id": latest_user.id,
        "status": summary["status"],
        "handled_at": latest_user.handled_at.isoformat() if latest_user.handled_at else None,
        "handled_by_user_id": latest_user.handled_by_user_id,
    }


@router.get(
    "/conversations",
    summary="Liste paginee des conversations captees des le message client",
)
def get_conversations(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    intent: str | None = Query(None),
    escalade: bool | None = Query(None, description="Filtre historique escalade/non escalade"),
    conversation_status: str | None = Query(
        None,
        alias="status",
        pattern="^(en_attente|repondu|escalade|traite)$",
    ),
    phone: str | None = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Liste un fil par session, meme si aucune reponse n'existe encore."""
    query = db.query(ChatMessage).options(joinedload(ChatMessage.user))
    if phone:
        phone_clean = phone.replace("+", "").replace(" ", "").strip()
        if phone_clean:
            query = query.join(ChatMessage.user).filter(
                User.email.ilike(f"%{phone_clean}%")
                | User.full_name.ilike(f"%{phone_clean}%")
                | ChatMessage.session_id.ilike(f"%{phone_clean}%")
            )

    messages = query.order_by(ChatMessage.id.desc()).all()
    items = _build_conversations(messages)
    if intent:
        items = [item for item in items if item["intent"] == intent]
    if escalade is not None:
        items = [item for item in items if item["escalade"] == escalade]
    if conversation_status:
        items = [item for item in items if item["status"] == conversation_status]

    items.sort(key=lambda item: item["id"], reverse=True)
    total = len(items)
    start = (page - 1) * page_size
    return {
        "items": items[start : start + page_size],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.post(
    "/conversations/{msg_id}/resolve",
    summary="Marquer une escalade comme traitee par un agent",
)
def resolve_conversation_escalation(
    msg_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Cloture l'escalade et enregistre l'agent qui l'a traitee."""
    _target_msg, _messages, summary = _latest_thread_for_action(db, msg_id)
    latest_user: ChatMessage = summary["latest_user"]
    # L'escalade est decidee et persistee sur la reponse de l'assistant. Les
    # anciennes captures pouvaient aussi la dupliquer sur le message client,
    # mais ce n'est pas une condition fiable pour les nouveaux fils.
    if not summary["escalade"]:
        raise HTTPException(status_code=409, detail="Cette conversation n'est pas en escalade")
    now = datetime.now(timezone.utc)
    changed = False
    if latest_user.handled_at is None:
        latest_user.handled_at = now
        latest_user.handled_by_user_id = current_user.id
        changed = True
    _mark_current_agent_notification_read(
        db,
        user_id=current_user.id,
        source_message_id=latest_user.id,
        now=now,
    )
    if changed:
        db.commit()
        db.refresh(latest_user)
    updated_summary = _conversation_summary(_thread_messages(db, _target_msg))
    return _action_state_response(updated_summary)


@router.get(
    "/conversations/{msg_id}",
    summary="Details complets d'une conversation et historique du fil",
)
def get_conversation_detail(
    msg_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Retourne exclusivement le fil de session concerne, sans melanger les invites."""
    target_msg = (
        db.query(ChatMessage)
        .options(joinedload(ChatMessage.user))
        .filter(ChatMessage.id == msg_id)
        .first()
    )
    if not target_msg:
        return {"error": "Conversation non trouvee"}

    thread_messages = _thread_messages(db, target_msg)
    summary = _conversation_summary(thread_messages)
    if summary is None:
        return {"error": "Conversation non trouvee"}

    latest_user: ChatMessage = summary["latest_user"]
    state_message: ChatMessage = summary["state_message"]
    user = target_msg.user
    email = user.email if user else "inconnu"
    name = (user.full_name if user else None) or "Visiteur / Client TexMiles"
    phone_info = _extract_phone(email, target_msg.session_id, name)
    client_info = {
        "email": email,
        "full_name": name,
        "phone_number": phone_info["formatted"],
        "raw_phone": phone_info["raw"],
        "display": phone_info["display"],
        "status": (
            "Client WhatsApp"
            if phone_info["raw"]
            else ("Membre" if user and user.email != "invite@texmiles.sn" else "Visiteur Web")
        ),
    }

    return {
        "id": latest_user.id,
        "session_id": latest_user.session_id,
        "client": client_info,
        "intent": latest_user.intent or state_message.intent or "general",
        "language": latest_user.language or state_message.language or "fr",
        "status": summary["status"],
        "has_response": summary["latest_response"] is not None,
        "escalade": summary["escalade"],
        "handled_at": latest_user.handled_at.isoformat() if latest_user.handled_at else None,
        "handled_by_user_id": latest_user.handled_by_user_id,
        "raison_escalade": state_message.raison_escalade,
        "ticket_id": state_message.ticket_id,
        "outils_utilises": state_message.outils_utilises,
        "sources": state_message.sources,
        "created_at": latest_user.created_at.isoformat(),
        "messages": [
            {
                "id": message.id,
                "role": message.role,
                "content": message.content,
                "created_at": message.created_at.isoformat(),
                "intent": message.intent,
                "escalade": message.escalade,
                "handled_at": message.handled_at.isoformat() if message.handled_at else None,
                "handled_by_user_id": message.handled_by_user_id,
                "ticket_id": message.ticket_id,
                "outils_utilises": message.outils_utilises,
                "sources": message.sources,
                "session_id": message.session_id,
            }
            for message in thread_messages
        ],
    }
