"""
Sécurité : hachage de mots de passe (bcrypt) et tokens JWT.
"""
from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import settings
from app.schemas.user import TokenData

# ---------------------------------------------------------------------------
# Hachage bcrypt
# ---------------------------------------------------------------------------
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain_password: str) -> str:
    """Hache un mot de passe en clair avec bcrypt."""
    return pwd_context.hash(plain_password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Compare un mot de passe en clair avec son hash bcrypt."""
    return pwd_context.verify(plain_password, hashed_password)


# ---------------------------------------------------------------------------
# JSON Web Tokens (JWT)
# ---------------------------------------------------------------------------
def create_access_token(data: dict) -> tuple[str, int]:
    """
    Crée un token JWT signé.

    Args:
        data: Données à encoder dans le payload (ex: {"sub": str(user_id), "email": "..."})

    Returns:
        (token encodé, durée de validité en secondes)
    """
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
    )
    payload = {**data, "exp": expire}
    token = jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    expires_in = settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
    return token, expires_in


def decode_access_token(token: str) -> TokenData | None:
    """
    Décode et valide un token JWT.

    Returns:
        TokenData si valide, None si expiré ou invalide.
    """
    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
        )
        user_id: str | None = payload.get("sub")
        email: str | None = payload.get("email")

        if user_id is None:
            return None

        return TokenData(user_id=int(user_id), email=email)

    except JWTError:
        return None
