"""
Routeur principal v1 — agrège tous les endpoints de la version 1.
"""
from fastapi import APIRouter

from app.api.v1.endpoints import auth

api_router = APIRouter()

# Authentification
api_router.include_router(auth.router, prefix="/auth", tags=["Authentification"])

# Étape 3 : chat
from app.api.v1.endpoints import chat
api_router.include_router(chat.router, prefix="/chat", tags=["Chat IA"])

# Étape 4 : Dashboard
from app.api.v1.endpoints import dashboard
api_router.include_router(dashboard.router, prefix="/dashboard", tags=["Statistiques"])

