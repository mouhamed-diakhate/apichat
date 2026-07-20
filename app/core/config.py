from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


class Settings(BaseSettings):
    """Configuration centrale de l'application via variables d'environnement."""

    # Application
    APP_NAME: str = "assistant-ia-api"
    APP_VERSION: str = "1.0.0"
    APP_DESCRIPTION: str = "API backend pour assistant IA — chat web, WhatsApp, tableau de bord"
    DEBUG: bool = False

    # Serveur
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # CORS — origines autorisées (séparées par des virgules dans .env)
    ALLOWED_ORIGINS: list[str] = [
        "http://localhost",
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1:8000",
    ]

    # Sécurité (utilisé à partir de l'Étape 2)
    SECRET_KEY: str = "changez-cette-cle-en-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    # Base de données (Étape 2)
    DATABASE_URL: str = "sqlite:///./assistant_ia.db"

    # IA (Étape 3)
    AI_PROVIDER: str = "ollama"  # gemini | openai | ollama
    GEMINI_API_KEY: str = ""
    OPENAI_API_KEY: str = ""
    OLLAMA_BASE_URL: str = "http://localhost:11434/v1"
    OLLAMA_MODEL: str = "qwen2.5"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
    )


@lru_cache()
def get_settings() -> Settings:
    """Retourne les settings mis en cache (singleton)."""
    return Settings()


# Instance globale accessible partout
settings = get_settings()
