"""
Modèle SQLAlchemy — Table `orders`.
"""
from sqlalchemy import Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Order(Base):
    """
    Représente une commande dans la base de données PostgreSQL.

    Colonnes :
        id            - Clé primaire auto-incrémentée
        numero        - Numéro unique de commande (ex: CMD1002)
        client        - Nom du client
        telephone     - Numéro de téléphone du client
        email         - Adresse email du client
        statut        - Statut actuel (ex: 'en préparation', 'expédiée', 'en livraison', 'livrée', 'retardée')
        date_estimee  - Date de livraison estimée (ex: '2026-07-24')
        articles      - Liste des articles (JSON string ou texte)
    """
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    numero: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
    client: Mapped[str] = mapped_column(String(255), nullable=False)
    telephone: Mapped[str | None] = mapped_column(String(50), index=True, nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), index=True, nullable=True)
    statut: Mapped[str] = mapped_column(String(100), nullable=False)
    date_estimee: Mapped[str | None] = mapped_column(String(50), nullable=True)
    articles: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"<Order numero={self.numero!r} client={self.client!r} statut={self.statut!r}>"
