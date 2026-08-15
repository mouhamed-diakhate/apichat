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

from app.api.v1.endpoints import dashboard_export
api_router.include_router(
    dashboard_export.router,
    prefix="/dashboard",
    tags=["Statistiques"],
)

# Administration de la FAQ : routes distinctes, réservées aux super-utilisateurs.
from app.api.v1.endpoints import faq_admin
api_router.include_router(faq_admin.router, prefix="/dashboard/faq", tags=["Gestion FAQ"])

# Webhook WhatsApp Meta Cloud API
from app.api.v1.endpoints import whatsapp
api_router.include_router(whatsapp.router, prefix="/whatsapp", tags=["WhatsApp Meta Webhook"])

# Webhook Evolution API (WhatsApp alternative sans validation Meta)
from app.api.v1.endpoints import evolution
api_router.include_router(evolution.router, prefix="/evolution", tags=["WhatsApp Evolution API Webhook"])


