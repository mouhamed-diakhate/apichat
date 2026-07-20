# assistant-ia-api

> API backend professionnelle construite avec **FastAPI** — architecture progressive par étapes.

## Stack technique

| Composant | Technologie |
|-----------|-------------|
| Framework | FastAPI |
| Serveur ASGI | Uvicorn |
| Configuration | Pydantic Settings |
| Base de données | SQLAlchemy + SQLite/PostgreSQL |
| Authentification | JWT (python-jose) |
| IA | Gemini / OpenAI |

## Démarrage rapide

```bash
# 1. Cloner et entrer dans le projet
git clone <url>
cd assistant-ia-api

# 2. Créer et activer l'environnement virtuel
python -m venv .venv
.venv\Scripts\activate      # Windows
source .venv/bin/activate   # Linux / macOS

# 3. Installer les dépendances
pip install -r requirements.txt

# 4. Configurer les variables d'environnement
copy .env.example .env      # Windows
cp .env.example .env        # Linux / macOS
# Éditez .env avec vos valeurs

# 5. Démarrer le serveur de développement
uvicorn app.main:app --reload
```

L'API est disponible sur **http://127.0.0.1:8000**

## Documentation

| URL | Description |
|-----|-------------|
| `GET /` | Informations de l'API |
| `GET /health` | Vérification de l'état (health check) |
| `GET /docs` | Documentation interactive (Swagger UI) |
| `GET /redoc` | Documentation ReDoc |

## Architecture du projet

```
app/
├── main.py              # Point d'entrée FastAPI
├── core/
│   └── config.py        # Configuration centralisée
├── api/
│   └── v1/
│       ├── router.py    # Agrégateur de routes
│       └── endpoints/   # Endpoints par fonctionnalité
├── models/              # Modèles SQLAlchemy
├── schemas/             # Schémas Pydantic
├── services/            # Logique métier
└── db/                  # Session et base de données
```
