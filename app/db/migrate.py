"""
Synchronisations légères du schéma en développement et en production.

`create_all()` ne modifie pas les tables existantes. Les petites migrations
ci-dessous complètent donc les colonnes ajoutées après le premier démarrage.
Pour les évolutions structurelles importantes, il faudra préférer Alembic.
"""

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from app.db.base import Base


def sync_sqlite_schema(engine: Engine) -> None:
    """Ajoute les colonnes absentes sur SQLite (no-op pour PostgreSQL)."""
    if engine.dialect.name != "sqlite":
        return

    inspector = inspect(engine)

    with engine.begin() as conn:
        for table_name, table in Base.metadata.tables.items():
            if not inspector.has_table(table_name):
                continue

            existing = {col["name"] for col in inspector.get_columns(table_name)}

            for column in table.columns:
                if column.name in existing:
                    continue

                col_type = column.type.compile(dialect=engine.dialect)
                ddl = f"ALTER TABLE {table_name} ADD COLUMN {column.name} {col_type}"
                conn.execute(text(ddl))


def sync_postgresql_schema(engine: Engine) -> None:
    """Ajoute les colonnes de traitement manuel absentes dans PostgreSQL.

    Cette migration est idempotente : elle peut être exécutée à chaque
    démarrage sans modifier les conversations déjà enregistrées.
    """
    if engine.dialect.name != "postgresql":
        return

    inspector = inspect(engine)
    if not inspector.has_table("chat_messages"):
        return

    existing = {column["name"] for column in inspector.get_columns("chat_messages")}
    foreign_keys = inspector.get_foreign_keys("chat_messages")
    has_handler_foreign_key = any(
        foreign_key.get("constrained_columns") == ["handled_by_user_id"]
        for foreign_key in foreign_keys
    )
    statements: list[str] = []

    if "handled_at" not in existing:
        statements.append(
            "ALTER TABLE chat_messages ADD COLUMN handled_at TIMESTAMP WITH TIME ZONE"
        )
    if "handled_by_user_id" not in existing:
        statements.append(
            "ALTER TABLE chat_messages ADD COLUMN handled_by_user_id INTEGER"
        )
    if not has_handler_foreign_key:
        statements.append(
            "ALTER TABLE chat_messages "
            "ADD CONSTRAINT fk_chat_messages_handled_by_user "
            "FOREIGN KEY (handled_by_user_id) REFERENCES users (id) ON DELETE SET NULL"
        )

    if not statements:
        return

    with engine.begin() as conn:
        for statement in statements:
            conn.execute(text(statement))
