"""
Endpoints d'authentification.

Routes :
    POST /api/v1/auth/register  — Créer un compte
    POST /api/v1/auth/login     — Se connecter, obtenir un token JWT
    GET  /api/v1/auth/me        — Profil de l'utilisateur connecté
"""
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.security import create_access_token, decode_access_token
from app.db.session import get_db
from app.models.user import User
from app.schemas.user import Token, UserCreate, UserLogin, UserRead
from app.services.auth_service import auth_service

router = APIRouter()
bearer_scheme = HTTPBearer()


# ---------------------------------------------------------------------------
# Dépendance — utilisateur actuellement connecté
# ---------------------------------------------------------------------------
def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    """
    Dépendance FastAPI : extrait et valide le token JWT du header Authorization.

    Raises:
        401 si le token est absent, expiré ou invalide.
        401 si le compte est désactivé.
    """
    token_data = decode_access_token(credentials.credentials)

    if token_data is None or token_data.user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token invalide ou expiré.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = auth_service.get_user_by_id(db, token_data.user_id)
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Utilisateur introuvable ou compte désactivé.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


# ---------------------------------------------------------------------------
# POST /register
# ---------------------------------------------------------------------------
@router.post(
    "/register",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
    summary="Créer un nouveau compte",
)
def register(user_data: UserCreate, db: Session = Depends(get_db)) -> UserRead:
    """
    Inscrit un nouvel utilisateur.

    - **email** : doit être unique
    - **password** : minimum 8 caractères
    - **full_name** : optionnel
    """
    try:
        user = auth_service.register(db, user_data)
        return user
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e),
        )


# ---------------------------------------------------------------------------
# POST /login
# ---------------------------------------------------------------------------
@router.post(
    "/login",
    response_model=Token,
    summary="Se connecter et obtenir un token JWT",
)
def login(credentials: UserLogin, db: Session = Depends(get_db)) -> Token:
    """
    Authentifie un utilisateur et retourne un **token JWT Bearer**.

    Utilisez ce token dans le header `Authorization: Bearer <token>`
    pour accéder aux endpoints protégés.
    """
    user = auth_service.authenticate(db, credentials.email, credentials.password)

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email ou mot de passe incorrect.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token, expires_in = create_access_token(
        data={"sub": str(user.id), "email": user.email}
    )
    return Token(access_token=token, expires_in=expires_in)


# ---------------------------------------------------------------------------
# GET /me
# ---------------------------------------------------------------------------
@router.get(
    "/me",
    response_model=UserRead,
    summary="Profil de l'utilisateur connecté",
)
def get_me(current_user: User = Depends(get_current_user)) -> UserRead:
    """
    Retourne les informations du compte actuellement connecté.

    Nécessite un token JWT valide dans le header `Authorization`.
    """
    return current_user
