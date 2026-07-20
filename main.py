"""
Raccourci de compatibilité.

La véritable application FastAPI est définie dans app/main.py. Ce fichier permet
simplement de lancer le serveur avec `uvicorn main:app` en plus de la forme
recommandée `uvicorn app.main:app`.
"""
from app.main import app  # noqa: F401
