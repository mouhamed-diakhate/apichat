"""
SessionStore : couche d'accès à la base de données pour les sessions conversationnelles.

Responsabilités :
- Charger une session depuis la BD et la reconstruire en objet UserSession
- Sauvegarder / mettre à jour l'état d'une session
- TTL automatique : supprimer les sessions inactives depuis > 24h

Utilisé par `get_or_create_session` dans session_manager.py comme backend
de persistence transparent derrière le cache en mémoire (_SESSIONS).
"""
import json
from datetime import datetime, timezone, timedelta

from sqlalchemy.orm import Session

from app.models.session import ConversationSession

# Durée de vie des sessions inactives (nettoyage automatique)
SESSION_TTL_HOURS = 24


class SessionStore:
    """Accès BD pour la table conversation_sessions."""

    @staticmethod
    def load(db: Session, session_id: str) -> dict | None:
        """
        Charge une session depuis la BD. Retourne un dict avec les champs
        de UserSession, ou None si la session n'existe pas / est expirée.
        """
        row = (
            db.query(ConversationSession)
            .filter(ConversationSession.session_id == session_id)
            .first()
        )
        if not row:
            return None

        # Expiration : supprimer les sessions trop vieilles
        age = datetime.now(timezone.utc) - row.updated_at.replace(tzinfo=timezone.utc)
        if age > timedelta(hours=SESSION_TTL_HOURS):
            db.delete(row)
            db.commit()
            return None

        return {
            "state": row.state,
            "language": row.language,
            "selected_mode": row.selected_mode,
            "selected_service": row.selected_service,
            "history": json.loads(row.history_json or "[]"),
            "data": json.loads(row.data_json or "{}"),
        }

    @staticmethod
    def save(db: Session, session_id: str, session_data: dict) -> None:
        """
        Sauvegarde ou met à jour une session en base.
        Ne lève pas d'exception — la persistence est best-effort.
        """
        try:
            row = (
                db.query(ConversationSession)
                .filter(ConversationSession.session_id == session_id)
                .first()
            )
            now = datetime.now(timezone.utc)
            if row:
                row.state = session_data.get("state", row.state)
                row.language = session_data.get("language")
                row.selected_mode = session_data.get("selected_mode")
                row.selected_service = session_data.get("selected_service")
                row.history_json = json.dumps(session_data.get("history", []), ensure_ascii=False)
                row.data_json = json.dumps(session_data.get("data", {}), ensure_ascii=False)
                row.updated_at = now
            else:
                row = ConversationSession(
                    session_id=session_id,
                    state=session_data.get("state", "AWAITING_LANG"),
                    language=session_data.get("language"),
                    selected_mode=session_data.get("selected_mode"),
                    selected_service=session_data.get("selected_service"),
                    history_json=json.dumps(session_data.get("history", []), ensure_ascii=False),
                    data_json=json.dumps(session_data.get("data", {}), ensure_ascii=False),
                    created_at=now,
                    updated_at=now,
                )
                db.add(row)
            db.commit()
        except Exception as e:
            db.rollback()
            # Log silencieux : on ne bloque pas la conversation si la BD est indisponible
            import logging
            logging.getLogger("session_store").warning(f"[SessionStore] Échec de sauvegarde : {e}")

    @staticmethod
    def delete(db: Session, session_id: str) -> None:
        """Supprime une session de la BD (utilisé lors d'un reset)."""
        try:
            db.query(ConversationSession).filter(
                ConversationSession.session_id == session_id
            ).delete()
            db.commit()
        except Exception:
            db.rollback()

    @staticmethod
    def cleanup_expired(db: Session) -> int:
        """Supprime toutes les sessions inactives depuis plus de SESSION_TTL_HOURS heures. Retourne le nombre supprimé."""
        try:
            cutoff = datetime.now(timezone.utc) - timedelta(hours=SESSION_TTL_HOURS)
            deleted = (
                db.query(ConversationSession)
                .filter(ConversationSession.updated_at < cutoff)
                .delete(synchronize_session=False)
            )
            db.commit()
            return deleted
        except Exception:
            db.rollback()
            return 0
