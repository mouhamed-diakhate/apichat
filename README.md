# Assistant IA — Service Client TexMiles (groupe Logidoo)

> Assistant conversationnel multi-canal : **API FastAPI** (authentification JWT + base de
> données) **+ moteur d'IA** (orchestrateur, outils, RAG FAQ, garde-fous). Branche de
> fusion réunissant l'infrastructure backend et le moteur d'intelligence.

## Ce que fait l'assistant
- Suivi de commande **avec vérification d'identité** obligatoire.
- Réponses **FAQ** depuis un fichier éditable (sans toucher au code).
- **Réclamations** avec ticket de suivi.
- **Escalade vers un humain** (colère, demande explicite, hors périmètre, incohérence).
- **Tableau de bord** de statistiques d'usage.
- Ne se fait jamais passer pour un humain, **n'invente jamais** une information.

Périmètre actuel : **français, texte, un modèle**. Vocal, wolof, WhatsApp, messages
proactifs = milestones suivants (architecture prévue pour les accueillir).

## Stack

| Composant | Technologie |
|-----------|-------------|
| API | FastAPI + Uvicorn |
| Auth | JWT (python-jose) |
| Base de données | SQLAlchemy (SQLite en dev, PostgreSQL en prod) |
| Configuration | pydantic-settings (`.env`) |
| Modèle IA | Interchangeable : Groq / Gemini / Grok / OpenAI / Ollama (Qwen) |

## Démarrage rapide

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
py -m pip install -r requirements.txt
Copy-Item .env.example .env      # puis renseignez AI_PROVIDER + la clé

uvicorn app.main:app --reload    # API + Swagger sur http://127.0.0.1:8000/docs
py cli.py                        # OU chat en ligne de commande
```

## Documentation

- 📘 **[DOCUMENTATION.md](DOCUMENTATION.md)** — architecture, rôle de chaque partie, « qui a
  construit quoi », correspondance avec le cahier des charges.
- 🧪 **[GUIDE_DE_TEST.md](GUIDE_DE_TEST.md)** — installer, lancer et tester (tests unitaires,
  harnais d'évaluation, démonstration Swagger/CLI, dépannage).

## Tests en un coup d'œil

```powershell
py -m pytest tests/ -q     # 10 tests (API/auth/chat), SANS clé API
py -m eval.run_eval        # 12 scénarios de recette, AVEC clé API
```
