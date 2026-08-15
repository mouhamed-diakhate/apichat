"""Endpoints privés de gestion de la FAQ sans édition JSON directe."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.v1.endpoints.auth import get_current_user
from app.models.user import User
from app.schemas.faq import FaqEntryCreate, FaqEntryListResponse, FaqEntryRead, FaqEntryUpdate
from app.services.ai_service import ai_service
from app.services.faq_management import (
    FaqEntryConflictError,
    FaqEntryNotFoundError,
    FaqManagementError,
    FaqManagementService,
)


router = APIRouter()
faq_management_service = FaqManagementService()


def require_faq_administrator(current_user: User = Depends(get_current_user)) -> User:
    """La FAQ modifie les réponses clients : accès réservé aux administrateurs actifs."""
    if not current_user.is_active or not current_user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Accès réservé aux administrateurs du tableau de bord.",
        )
    return current_user


def _raise_store_error(error: FaqManagementError) -> None:
    if isinstance(error, FaqEntryNotFoundError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Entrée FAQ introuvable.") from error
    if isinstance(error, FaqEntryConflictError):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Cet identifiant FAQ existe déjà.") from error
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="La FAQ est temporairement indisponible. Réessayez dans un instant.",
    ) from error


def _invalidate_knowledge_cache() -> None:
    """Les assistants reconstruiront FAQ + index RAG à leur prochain message."""
    ai_service.invalidate_knowledge_cache()


@router.get("", response_model=FaqEntryListResponse, summary="Lister ou rechercher les entrées FAQ")
def list_faq_entries(
    q: str | None = Query(default=None, max_length=200, description="Texte à rechercher"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
    _administrator: User = Depends(require_faq_administrator),
):
    try:
        items, total = faq_management_service.list_entries(query=q, page=page, page_size=page_size)
    except FaqManagementError as error:
        _raise_store_error(error)
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.post(
    "",
    response_model=FaqEntryRead,
    status_code=status.HTTP_201_CREATED,
    summary="Créer une entrée FAQ",
)
def create_faq_entry(
    payload: FaqEntryCreate,
    _administrator: User = Depends(require_faq_administrator),
):
    try:
        entry = faq_management_service.create_entry(
            question=payload.question,
            reponse=payload.reponse,
            mots_cles=payload.mots_cles,
            entry_id=payload.id,
        )
    except FaqManagementError as error:
        _raise_store_error(error)
    _invalidate_knowledge_cache()
    return entry


@router.put("/{entry_id}", response_model=FaqEntryRead, summary="Modifier une entrée FAQ")
def update_faq_entry(
    entry_id: str,
    payload: FaqEntryUpdate,
    _administrator: User = Depends(require_faq_administrator),
):
    try:
        entry = faq_management_service.update_entry(
            entry_id,
            payload.model_dump(exclude_unset=True),
        )
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)) from error
    except FaqManagementError as error:
        _raise_store_error(error)
    _invalidate_knowledge_cache()
    return entry


@router.delete("/{entry_id}", summary="Supprimer une entrée FAQ")
def delete_faq_entry(
    entry_id: str,
    _administrator: User = Depends(require_faq_administrator),
):
    try:
        faq_management_service.delete_entry(entry_id)
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)) from error
    except FaqManagementError as error:
        _raise_store_error(error)
    _invalidate_knowledge_cache()
    return {"id": entry_id, "deleted": True}
