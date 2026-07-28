"""
Module centralisé pour le Rate Limiter (slowapi).
Isolé ici pour éviter les imports circulaires entre app.main et les endpoints.
"""
from slowapi import Limiter
from slowapi.util import get_remote_address

# Limiter global, identifie les clients par adresse IP
limiter = Limiter(key_func=get_remote_address, default_limits=["200/minute"])
