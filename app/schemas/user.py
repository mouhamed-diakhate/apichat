"""
Schémas Pydantic pour l'authentification.

Séparation stricte :
    UserCreate   → données reçues à l'inscription (mot de passe en clair)
    UserRead     → données renvoyées au client (jamais de mot de passe)
    Token        → réponse après login (access_token + type)
    TokenData    → payload décodé du JWT
    UserLogin    → données reçues au login
"""
from datetime import datetime
from pydantic import BaseModel, EmailStr, Field


# ---------------------------------------------------------------------------
# Utilisateur — Entrée
# ---------------------------------------------------------------------------
class UserCreate(BaseModel):
    """Données pour créer un nouveau compte."""
    email: EmailStr
    password: str = Field(min_length=8, description="Minimum 8 caractères")
    full_name: str | None = Field(default=None, max_length=255)

    model_config = {"str_strip_whitespace": True}


class UserLogin(BaseModel):
    """Données pour se connecter."""
    email: EmailStr
    password: str


# ---------------------------------------------------------------------------
# Utilisateur — Sortie (jamais de mot de passe)
# ---------------------------------------------------------------------------
class UserRead(BaseModel):
    """Données renvoyées au client — sans mot de passe."""
    id: int
    email: EmailStr
    full_name: str | None
    is_active: bool
    is_superuser: bool
    created_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# JWT Token
# ---------------------------------------------------------------------------
class Token(BaseModel):
    """Réponse après une authentification réussie."""
    access_token: str
    token_type: str = "bearer"
    expires_in: int  # secondes avant expiration


class TokenData(BaseModel):
    """Payload extrait du token JWT."""
    user_id: int | None = None
    email: str | None = None
