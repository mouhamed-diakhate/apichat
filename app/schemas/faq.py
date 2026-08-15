"""Schémas d'administration de la FAQ TexMiles."""

from __future__ import annotations

import re

from pydantic import BaseModel, Field, field_validator, model_validator


_SAFE_ID = re.compile(r"^[a-z][a-z0-9_]{0,79}$")


def _normalise_short_text(value: str, *, label: str, maximum: int) -> str:
    normalized = " ".join(value.split()).strip()
    if not normalized:
        raise ValueError(f"{label} est obligatoire.")
    if len(normalized) > maximum:
        raise ValueError(f"{label} ne doit pas dépasser {maximum} caractères.")
    return normalized


def _normalise_answer(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError("La réponse est obligatoire.")
    if len(normalized) > 10_000:
        raise ValueError("La réponse ne doit pas dépasser 10 000 caractères.")
    return normalized


def _normalise_keywords(values: list[str]) -> list[str]:
    if len(values) > 30:
        raise ValueError("Ajoutez au maximum 30 mots-clés.")

    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        keyword = _normalise_short_text(value, label="Un mot-clé", maximum=80)
        key = keyword.casefold()
        if key not in seen:
            normalized.append(keyword)
            seen.add(key)
    return normalized


class FaqEntryCreate(BaseModel):
    """Données saisies dans le formulaire de création d'une question."""

    id: str | None = Field(default=None, max_length=80)
    question: str = Field(min_length=2, max_length=500)
    reponse: str = Field(min_length=1, max_length=10_000)
    mots_cles: list[str] = Field(default_factory=list, max_length=30)

    model_config = {"extra": "forbid"}

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not _SAFE_ID.fullmatch(value):
            raise ValueError(
                "L'identifiant doit commencer par une lettre et contenir seulement "
                "des minuscules, chiffres et traits de soulignement."
            )
        return value

    @field_validator("question")
    @classmethod
    def validate_question(cls, value: str) -> str:
        return _normalise_short_text(value, label="La question", maximum=500)

    @field_validator("reponse")
    @classmethod
    def validate_response(cls, value: str) -> str:
        return _normalise_answer(value)

    @field_validator("mots_cles")
    @classmethod
    def validate_keywords(cls, value: list[str]) -> list[str]:
        return _normalise_keywords(value)


class FaqEntryUpdate(BaseModel):
    """Champs modifiables d'une entrée existante (identifiant immuable)."""

    question: str | None = Field(default=None, min_length=2, max_length=500)
    reponse: str | None = Field(default=None, min_length=1, max_length=10_000)
    mots_cles: list[str] | None = Field(default=None, max_length=30)

    model_config = {"extra": "forbid"}

    @field_validator("question")
    @classmethod
    def validate_question(cls, value: str | None) -> str | None:
        return _normalise_short_text(value, label="La question", maximum=500) if value is not None else value

    @field_validator("reponse")
    @classmethod
    def validate_response(cls, value: str | None) -> str | None:
        return _normalise_answer(value) if value is not None else value

    @field_validator("mots_cles")
    @classmethod
    def validate_keywords(cls, value: list[str] | None) -> list[str] | None:
        return _normalise_keywords(value) if value is not None else value

    @model_validator(mode="after")
    def require_a_change(self):
        if not self.model_fields_set:
            raise ValueError("Indiquez au moins un champ à modifier.")
        if any(getattr(self, field) is None for field in self.model_fields_set):
            raise ValueError("Un champ à modifier ne peut pas être vide.")
        return self


class FaqEntryRead(BaseModel):
    id: str
    question: str
    reponse: str
    mots_cles: list[str]
    article: str | None = None


class FaqEntryListResponse(BaseModel):
    items: list[FaqEntryRead]
    total: int
    page: int
    page_size: int
