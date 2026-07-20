"""
Service d'authentification — logique métier.

Cette couche est séparée des endpoints pour :
- Faciliter les tests unitaires
- Éviter la duplication de code
- Permettre la réutilisation (ex: WhatsApp auth)
"""
from sqlalchemy.orm import Session

from app.core.security import hash_password, verify_password
from app.models.user import User
from app.schemas.user import UserCreate


class AuthService:
    """Service gérant l'inscription et l'authentification des utilisateurs."""

    # -----------------------------------------------------------------------
    # Requêtes DB
    # -----------------------------------------------------------------------
    @staticmethod
    def get_user_by_email(db: Session, email: str) -> User | None:
        """Retourne un utilisateur par son email, ou None s'il n'existe pas."""
        return db.query(User).filter(User.email == email.lower()).first()

    @staticmethod
    def get_user_by_id(db: Session, user_id: int) -> User | None:
        """Retourne un utilisateur par son id, ou None."""
        return db.query(User).filter(User.id == user_id).first()

    # -----------------------------------------------------------------------
    # Inscription
    # -----------------------------------------------------------------------
    @staticmethod
    def register(db: Session, user_data: UserCreate) -> User:
        """
        Crée un nouveau compte utilisateur.

        Raises:
            ValueError: Si l'email est déjà utilisé.
        """
        email_lower = user_data.email.lower()

        if AuthService.get_user_by_email(db, email_lower):
            raise ValueError(f"L'email '{email_lower}' est déjà utilisé.")

        new_user = User(
            email=email_lower,
            hashed_password=hash_password(user_data.password),
            full_name=user_data.full_name,
        )
        db.add(new_user)
        db.commit()
        db.refresh(new_user)
        return new_user

    # -----------------------------------------------------------------------
    # Authentification
    # -----------------------------------------------------------------------
    @staticmethod
    def authenticate(db: Session, email: str, password: str) -> User | None:
        """
        Vérifie les identifiants.

        Returns:
            L'utilisateur si les identifiants sont corrects,
            None sinon (email inconnu ou mauvais mot de passe).
        """
        user = AuthService.get_user_by_email(db, email.lower())
        if not user:
            return None
        if not verify_password(password, user.hashed_password):
            return None
        if not user.is_active:
            return None
        return user


# Instance singleton réutilisable
auth_service = AuthService()
