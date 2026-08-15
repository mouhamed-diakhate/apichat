"""Export CSV des tickets et escalades visibles dans le tableau de bord."""

from __future__ import annotations

import csv
from datetime import date, datetime, timezone
from io import StringIO

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session, joinedload

from app.api.v1.endpoints.auth import get_current_user
from app.api.v1.endpoints.dashboard import (
    _conversation_item,
    _resolve_period_bounds,
    _serialize_datetime,
    _thread_metric,
    _threads_for_period,
)
from app.db.session import get_db
from app.models.chat import ChatMessage
from app.models.user import User


router = APIRouter()

_DANGEROUS_CSV_PREFIXES = ("=", "+", "-", "@")
_CONVERSATION_STATUSES = "^(en_attente|repondu|escalade|traite)$"


def _csv_cell(value: object | None) -> str:
    """Protège les cellules Excel contre l'exécution de formules injectées."""
    text = "" if value is None else str(value)
    return f"'{text}" if text.lstrip().startswith(_DANGEROUS_CSV_PREFIXES) else text


def _agent_labels(db: Session, handler_ids: set[int]) -> dict[int, str]:
    if not handler_ids:
        return {}
    users = db.query(User).filter(User.id.in_(handler_ids)).all()
    return {
        user.id: (user.full_name or user.email)
        for user in users
    }


@router.get(
    "/exports/tickets-escalades.csv",
    summary="Exporter les tickets et escalades au format CSV",
)
def export_tickets_and_escalations_csv(
    start_date: date | None = Query(None, description="Debut inclusif (YYYY-MM-DD, UTC)"),
    end_date: date | None = Query(None, description="Fin inclusive (YYYY-MM-DD, UTC)"),
    start_at: datetime | None = Query(None, description="Debut ISO-8601 inclusif"),
    end_at: datetime | None = Query(None, description="Fin ISO-8601 inclusive"),
    intent: str | None = Query(None, max_length=100),
    conversation_status: str | None = Query(None, alias="status", pattern=_CONVERSATION_STATUSES),
    db: Session = Depends(get_db),
    _current_user: User = Depends(get_current_user),
):
    """Télécharge une ligne par conversation ayant un ticket ou une escalade.

    La période est ancrée sur le dernier message client, comme les indicateurs
    du dashboard. Les informations d'escalade viennent de la réponse assistant
    afin de ne pas exporter de faux positifs issus de données client historiques.
    """
    period_start, period_end = _resolve_period_bounds(
        start_date=start_date,
        end_date=end_date,
        start_at=start_at,
        end_at=end_at,
    )
    messages = (
        db.query(ChatMessage)
        .options(joinedload(ChatMessage.user))
        .order_by(ChatMessage.created_at.asc(), ChatMessage.id.asc())
        .all()
    )

    rows: list[tuple[dict, dict]] = []
    for thread in _threads_for_period(messages, period_start, period_end):
        metric = _thread_metric(thread)
        if metric is None:
            continue
        summary = metric["summary"]
        if intent and metric["intent"] != intent:
            continue
        if conversation_status and summary["status"] != conversation_status:
            continue
        if not metric["is_escalated"] and not metric["ticket_ids"]:
            continue
        rows.append((metric, _conversation_item(summary)))

    handler_ids = {
        item["handled_by_user_id"]
        for _metric, item in rows
        if item["handled_by_user_id"] is not None
    }
    agents = _agent_labels(db, handler_ids)

    stream = StringIO(newline="")
    writer = csv.writer(stream, delimiter=";", lineterminator="\r\n")
    writer.writerow(
        [
            "Dernier message client (UTC)",
            "Client",
            "Telephone WhatsApp",
            "Session",
            "Intention",
            "Statut",
            "Escalade assistant",
            "Date escalation (UTC)",
            "Raison escalation",
            "Tickets",
            "Traite le (UTC)",
            "Agent responsable",
            "Delai humain (minutes)",
        ]
    )
    for metric, item in rows:
        handled_by_user_id = item["handled_by_user_id"]
        delay = metric["human_response_seconds"]
        writer.writerow(
            [
                _csv_cell(_serialize_datetime(metric["anchor_at"])),
                _csv_cell(item["client_display"]),
                _csv_cell(item["user_phone"] or item["raw_phone"]),
                _csv_cell(item["session_id"]),
                _csv_cell(metric["intent"]),
                _csv_cell(item["status"]),
                "Oui" if metric["is_escalated"] else "Non",
                _csv_cell(_serialize_datetime(metric["escalation_at"])),
                _csv_cell(metric["escalation_reason"]),
                _csv_cell(", ".join(sorted(metric["ticket_ids"]))),
                _csv_cell(_serialize_datetime(metric["resolution_at"])),
                _csv_cell(agents.get(handled_by_user_id)),
                "" if delay is None else f"{delay / 60:.2f}",
            ]
        )

    filename = "texmiles_tickets_escalades_" + datetime.now(timezone.utc).strftime("%Y%m%d") + ".csv"
    return Response(
        content="\ufeff" + stream.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
