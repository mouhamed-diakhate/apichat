# Guide de test — Assistant IA TexMiles

Ce guide explique **comment installer, lancer et tester** le projet, du plus simple
(sans clé API) au plus complet (démonstration de soutenance). Voir
[DOCUMENTATION.md](DOCUMENTATION.md) pour l'architecture.

---

## 0. Résumé — trois façons de tester

| Méthode | Besoin d'une clé API ? | Ce que ça prouve |
|---------|------------------------|------------------|
| **A. Tests unitaires** (`pytest`) | ❌ Non (le modèle est simulé) | L'API, l'auth, la persistance et le flux de chat fonctionnent |
| **B. Harnais d'évaluation** (`run_eval`) | ✅ Oui | Le moteur IA se comporte correctement sur 12 scénarios réels |
| **C. Démonstration manuelle** (Swagger / CLI) | ✅ Oui | Le parcours utilisateur complet, en direct |

Commencez par **A** (rapide, sans configuration). Passez à **B** et **C** une fois une
clé configurée.

---

## 1. Installation

Depuis le dossier `apichat/`, sous Windows PowerShell :

```powershell
# 1. Environnement virtuel
py -m venv .venv
.\.venv\Scripts\Activate.ps1

# 2. Dépendances
py -m pip install -r requirements.txt
```

> **Note Windows / Python 3.14 :** si `psycopg2-binary` (pilote PostgreSQL) refuse de
> s'installer, ce n'est pas bloquant pour le développement : la base par défaut est
> **SQLite**. Vous pouvez commenter la ligne `psycopg2-binary` dans `requirements.txt`
> pour le dev local, et la remettre pour un déploiement PostgreSQL.

---

## 2. Configuration (`.env`)

```powershell
Copy-Item .env.example .env
```

Puis ouvrez `.env` et choisissez **un** fournisseur de modèle :

### Option 1 — Groq (cloud, gratuit) — recommandé pour la soutenance
```env
AI_PROVIDER=groq
GROQ_API_KEY=gsk_...        # clé depuis https://console.groq.com
MODEL=openai/gpt-oss-20b    # modèle fiable pour les appels d'outils
```

### Option 2 — Qwen en local (gratuit, hors-ligne)
Nécessite [Ollama](https://ollama.com) installé, puis `ollama run qwen2.5`.
```env
AI_PROVIDER=ollama
OLLAMA_MODEL=qwen2.5
# aucune clé requise
```

> ⚠️ Ne committez jamais le fichier `.env` (il est ignoré par git).

---

## 3. Méthode A — Tests unitaires (sans clé API)

Le moteur IA est **simulé (mocké)** dans ces tests : ils vérifient l'API, l'authentification,
la base de données et le flux de chat, **sans appeler de vrai modèle**.

```powershell
py -m pytest tests/ -q
```

Résultat attendu : **10 tests passés** (auth + chat).

Ce que ça couvre :
- Les routes de chat exigent une authentification (401 sans token).
- Inscription + connexion + obtention du token JWT.
- Envoi d'un message → réponse enregistrée avec intention, escalade, etc.
- Récupération de l'historique dans le bon ordre.

---

## 4. Méthode B — Harnais d'évaluation (avec clé API)

Fait passer **12 scénarios de recette** (issus du CDC §10) dans le vrai moteur IA et
affiche un rapport `réussis / total`.

```powershell
py -m eval.run_eval
```

Scénarios couverts : numéro de commande valide / invalide, FAQ (délais, retour, paiement),
réclamation (colis endommagé), client en colère, demande explicite d'humain, échec
d'identité, identité de l'assistant (« es-tu un robot ? »), demande hors périmètre.

**Résultat attendu :** `12/12 cas réussis` (avec un modèle fiable comme
`openai/gpt-oss-20b` sur Groq).

> **Comparer deux modèles :** changez `MODEL` (ou `AI_PROVIDER`) dans `.env` et relancez.
> C'est ainsi qu'on compare objectivement, par exemple, Groq et Qwen local sur les mêmes cas.

---

## 5. Méthode C — Démonstration manuelle

### 5.1 Chat en ligne de commande (le plus simple)
```powershell
py cli.py
```
Tapez un message, lisez la réponse ; `quitter` pour sortir. Exemples à essayer :
- `où en est ma commande CMD1002 ?`
- `vous livrez en combien de temps ?`
- `j'ai reçu un colis endommagé, commande CMD1004`
- `je veux parler à un humain`

### 5.2 API web + Swagger (parcours complet, idéal soutenance)

1. Lancer le serveur :
   ```powershell
   uvicorn app.main:app --reload
   ```
2. Ouvrir **http://127.0.0.1:8000/docs** (Swagger UI).
3. **Créer un compte** : `POST /api/v1/auth/register`
   ```json
   { "email": "demo@texmiles.com", "password": "motdepasse123", "full_name": "Demo" }
   ```
4. **Se connecter** : `POST /api/v1/auth/login` (mêmes email/mot de passe) → copiez le
   `access_token` renvoyé.
5. Cliquer sur **« Authorize »** (en haut à droite de Swagger) et coller le token.
6. **Tester le chat** : `POST /api/v1/chat/message`
   - **FAQ** : `{ "content": "Quels sont vos délais de livraison ?" }`
     → utilise l'outil `search_faq`.
   - **Suivi** : `{ "content": "Où en est ma commande CMD1002 ?" }`
     → utilise `lookup_order`, renvoie le statut.
   - **Réclamation** : `{ "content": "Ma commande CMD1004 est arrivée endommagée" }`
     → ouvre un ticket, `escalade = true`.
   - **Escalade** : `{ "content": "C'est inadmissible, je veux un humain !" }`
     → `escalade = true` avec la raison.
   - **Identité** : `{ "content": "Statut de CMD1002, mon numéro est +221 76 000 00 00" }`
     → refuse de divulguer (incohérence) et reste prudent.
7. **Historique** : `GET /api/v1/chat/history` → tous les messages échangés.
8. **Statistiques** : `GET /api/v1/dashboard/stats` → nombre de messages, taux d'escalade,
   répartition par intention, tickets créés.

---

## 6. Commandes fictives disponibles (pour les tests)

Ces commandes viennent de `data/orders.mock.json` :

| Numéro | Téléphone | Statut |
|--------|-----------|--------|
| CMD1001 | +221771112233 | en préparation |
| CMD1002 | +221770001122 | expédiée |
| CMD1003 | +221769998877 | en livraison |
| CMD1004 | +221765554433 | livrée |
| CMD1005 | +221768887766 | retardée |
| CMD1006 | +221764443322 | en préparation |

---

## 7. Dépannage

| Symptôme | Cause | Solution |
|----------|-------|----------|
| `429 ... tokens per day` | Quota gratuit Groq épuisé pour ce modèle | Changez `MODEL` dans `.env` (chaque modèle a son propre quota), ou attendez la réinitialisation quotidienne |
| `Clé API manquante pour '...'` | `.env` mal renseigné | Vérifiez `AI_PROVIDER` et la clé correspondante |
| Erreur d'insertion en base après modification d'un modèle | La base SQLite existante n'a pas les nouvelles colonnes | Supprimez le fichier `assistant_ia.db` : il sera recréé au démarrage |
| `tool_use_failed` | Le modèle a mal formaté un appel d'outil | Déjà géré automatiquement (récupération + réessai) ; si récurrent, utilisez un modèle plus fiable comme `openai/gpt-oss-20b` |
| Réponses incohérentes en local (Ollama) | Ollama non démarré ou modèle non téléchargé | `ollama run qwen2.5` d'abord |
| Le serveur démarre mais `/chat` renvoie un message de repli | Moteur IA non configuré (clé absente) | Renseignez la clé dans `.env` ; le serveur, lui, démarre toujours |

---

## 8. Ce qui est vérifié à ce stade

- ✅ Tous les modules compilent et l'application démarre.
- ✅ **10/10 tests unitaires** passent (API, auth, chat, persistance — sans clé API).
- ✅ Le moteur IA passe **12/12 scénarios** de recette (avec une clé, modèle fiable).
- ✅ Les routes `/api/v1/auth`, `/api/v1/chat`, `/api/v1/dashboard` sont exposées.

*Bonne démonstration !*
