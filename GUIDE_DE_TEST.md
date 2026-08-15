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

### 5.3 WhatsApp via Evolution API (Test pas à pas autonome)

Pour tester la réception et l'envoi automatique de messages sur **WhatsApp** depuis votre propre téléphone, suivez ces étapes simples :

#### 📌 Étape 1 : Démarrer les services Docker (Evolution API)
Assurez-vous que Docker Desktop est ouvert, puis lancez les conteneurs :
```powershell
docker start evolution_api evolution_postgres evolution_redis
```
*(Ou `docker compose up -d` si vous utilisez docker-compose).*

#### 📌 Étape 2 : Lancer le serveur backend FastAPI
Dans votre terminal PowerShell :
```powershell
.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```
L'API tourne sur `http://localhost:8000`.

#### 📌 Étape 3 : Créer le tunnel public HTTPS pour le Webhook
Ouvrez une **deuxième fenêtre PowerShell** à la racine du projet et lancez `cloudflared` :
```powershell
.\cloudflared.exe tunnel --url http://localhost:8000
```
Dans les logs, repérez la ligne :
`https://<votre-sous-domaine>.trycloudflare.com`

#### 📌 Étape 4 : Configurer le Webhook dans Evolution API
Ouvrez une **troisième fenêtre PowerShell** et exécutez la commande suivante (en remplaçant l'URL par la vôtre) :
```powershell
$tunnelUrl = "https://<votre-sous-domaine>.trycloudflare.com/api/v1/evolution/webhook"
$body = @{
  url = $tunnelUrl
  webhook = @{
    enabled = $true
    url = $tunnelUrl
    webhookByEvents = $false
    webhookBase64 = $false
    events = @("MESSAGES_UPSERT")
  }
} | ConvertTo-Json -Depth 5

Invoke-RestMethod -Uri "http://localhost:8080/webhook/set/TexMiles" -Headers @{"apikey"="123456789"; "Content-Type"="application/json"} -Method POST -Body $body
```

#### 📌 Étape 5 : Connecter WhatsApp (Scanner le QR Code)
- Si l'instance est déjà connectée, vous n'avez rien à faire !
- Pour vérifier ou scanner le QR Code, ouvrez votre navigateur sur :
  👉 **http://localhost:8000/qr**
- Sur WhatsApp (sur votre téléphone) → **Appareils connectés** → **Connecter un appareil** → Scannez le QR Code affiché à l'écran.

#### 📌 Étape 6 : Tester sur WhatsApp !
- Depuis n'importe quel numéro de téléphone, envoyez un message au numéro WhatsApp connecté.
- Vous recevrez immédiatement les menus interactifs (Langue → Mode → Menu principal → Agent IA).

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
| `ECONNREFUSED` sur le webhook Evolution API | Webhook configuré sur `localhost:8000` au lieu du tunnel Cloudflare | Mettez à jour le Webhook avec l'URL HTTPS `trycloudflare.com` (Étape 4) |
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
- ✅ Les routes `/api/v1/auth`, `/api/v1/chat`, `/api/v1/dashboard`, `/api/v1/evolution` sont exposées.
- ✅ L'intégration complète **Evolution API WhatsApp** est opérationnelle avec tunnel Cloudflare.

*Bonne démonstration !*

