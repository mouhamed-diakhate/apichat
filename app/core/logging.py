"""
Module de gestion centralisée des logs structurés (JSON / Standard).

Transforme les logs Python en objets JSON structurés et lisibles par les
systèmes de supervision modernes (ELK, Datadog, Sentry, CloudWatch).
"""

import json
import logging
import sys
from datetime import datetime, timezone


class JSONFormatter(logging.Formatter):
    """Formateur personnalisé sérialisant chaque log au format JSON."""

    def format(self, record: logging.LogRecord) -> str:
        log_object = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Ajouter l'exception si présente
        if record.exc_info:
            log_object["exception"] = self.formatException(record.exc_info)

        # Ajouter les métadonnées supplémentaires passées dans `extra={...}`
        for key, value in record.__dict__.items():
            if key not in (
                "args", "asctime", "created", "exc_info", "exc_text", "filename",
                "funcName", "levelname", "levelno", "lineno", "module", "msecs",
                "message", "msg", "name", "pathname", "process", "processName",
                "relativeCreated", "stack_info", "thread", "threadName"
            ):
                log_object[key] = value

        return json.dumps(log_object, ensure_ascii=False)


def setup_logging(log_level: str = "INFO", json_format: bool = True) -> None:
    """Configure le logger racine de l'application."""
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level.upper())

    # Supprimer les anciens handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    handler = logging.StreamHandler(sys.stdout)
    if json_format:
        handler.setFormatter(JSONFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s")
        )

    root_logger.addHandler(handler)
