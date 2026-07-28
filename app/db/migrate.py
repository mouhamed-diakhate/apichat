"""
Synchronisation légère du schéma SQLite en développement.

`create_all()` ne modifie pas les tables existantes. Cette fonction ajoute
les colonnes manquantes déclarées dans les modèles SQLAlchemy.
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
