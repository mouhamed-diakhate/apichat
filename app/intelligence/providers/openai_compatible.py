"""
Connecteur générique pour tout service dont l'API est "compatible OpenAI".

Beaucoup de fournisseurs exposent la même API que celle d'OpenAI (mêmes routes,
même format de messages et d'outils) : il suffit alors de changer l'adresse du
serveur (base_url) et la clé. C'est le cas de Groq, Google Gemini, Grok (x.ai),
OpenAI lui-même, etc.

Résultat : UNE seule classe couvre tous ces fournisseurs. On choisit lequel via
la configuration (voir app/config.py). C'est la mise en pratique de l'objectif du
cahier des charges : pouvoir changer / comparer les modèles sans réécrire le code.

Note : la logique de fallback inter-provider (429 → provider suivant) est désormais
gérée par FallbackProvider. Ce module se concentre sur UN seul provider/modèle.
"""

import ast
import json
import logging
import re

from openai import OpenAI, BadRequestError, RateLimitError

from .base import LLMProvider, LLMResponse, ToolCall

logger = logging.getLogger(__name__)


def _recuperer_appels_mal_formes(texte: str) -> list[ToolCall]:
    """
    Récupère un appel d'outil quand le modèle l'a écrit dans un format non standard.
    """
    appels: list[ToolCall] = []
    cleaned = (texte or "").replace('\\"', '"').replace("\\'", "'")

    for m in re.finditer(r"<function=([\w-]+)[^{]*(\{[^{}]*\})", cleaned, re.DOTALL):
        tool_name = m.group(1)
        json_str = m.group(2)
        args = {}
        try:
            args = json.loads(json_str)
        except Exception:
            try:
                eval_res = ast.literal_eval(json_str)
                if isinstance(eval_res, dict):
                    args = eval_res
            except Exception:
                args = {}
        appels.append(ToolCall(id=f"salvage_{len(appels)}", name=tool_name, arguments=args))
    return appels


class OpenAICompatibleProvider(LLMProvider):
    def __init__(self, api_key: str, model: str, base_url: str, name: str = ""):
        # Le client "OpenAI" pointe vers le serveur choisi (Groq, Gemini, x.ai...).
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.model = model
        # Nom lisible pour les logs (ex. "groq/llama-3.3-70b").
        self._name = name or model

    def complete_text(self, system: str, user: str) -> str:
        """
        Appel simple, sans outils : renvoie juste le texte du modèle.

        Utilisé par exemple pour la détection d'intention (analytics), qui n'a besoin
        que d'une classification courte. Réutilise la même connexion que `chat`.
        """
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.0,
        )
        return resp.choices[0].message.content or ""

    def chat(self, system, messages, tools=None) -> LLMResponse:
        # 1) Traduire nos messages "neutres" vers le format attendu par l'API.
        api_messages: list[dict] = [{"role": "system", "content": system}]
        for m in messages:
            if m["role"] == "assistant" and m.get("tool_calls"):
                api_messages.append({
                    "role": "assistant",
                    "content": m.get("content") or "",
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.name,
                                "arguments": json.dumps(tc.arguments, ensure_ascii=False),
                            },
                        }
                        for tc in m["tool_calls"]
                    ],
                })
            elif m["role"] == "tool":
                api_messages.append({
                    "role": "tool",
                    "tool_call_id": m["tool_call_id"],
                    "content": m["content"],
                })
            else:
                api_messages.append({"role": m["role"], "content": m["content"]})

        # 2) Appeler le modèle.
        kwargs: dict = {"model": self.model, "messages": api_messages}
        if tools:
            kwargs["tools"] = tools

        # Certains modèles (ex. Llama sur Groq) produisent parfois un appel d'outil
        # mal formaté → erreur "tool_use_failed". Deux parades combinées :
        #   1) on tente de RÉCUPÉRER l'appel depuis le texte rejeté (failed_generation) ;
        #   2) sinon on RÉESSAIE (un nouvel échantillonnage corrige souvent le format).
        completion = None
        derniere_erreur = None
        for _essai in range(3):
            try:
                completion = self.client.chat.completions.create(**kwargs)
                break
            except RateLimitError:
                # Relancer directement : FallbackProvider gère le basculement.
                raise
            except BadRequestError as e:
                if "tool_use_failed" not in str(e):
                    raise
                derniere_erreur = e
                # Parade 1 : récupérer l'appel mal formaté dans le corps ou la chaîne de l'erreur.
                corps = getattr(e, "body", None) or {}
                brut = ""
                if isinstance(corps, dict):
                    brut = corps.get("error", {}).get("failed_generation", "") or ""
                if not brut:
                    brut = str(e)
                appels = _recuperer_appels_mal_formes(brut)
                if not appels and brut != str(e):
                    appels = _recuperer_appels_mal_formes(str(e))
                if appels:
                    return LLMResponse(text="", tool_calls=appels, provider_used=self._name)
                # Parade 2 : réessayer.
                continue

        if completion is None:
            raise derniere_erreur

        msg = completion.choices[0].message

        # 3) Retraduire la réponse vers notre format "neutre".
        tool_calls: list[ToolCall] = []
        for tc in (msg.tool_calls or []):
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            tool_calls.append(ToolCall(id=tc.id, name=tc.function.name, arguments=args))

        # Parade 3 : certains modèles (petits LLMs) écrivent l'appel d'outil sous forme
        # de texte brut `<function=nom>{...}</function>` dans le contenu, au lieu d'utiliser
        # le mécanisme officiel tool_calls. On les intercepte ici pour ne pas afficher
        # ce texte technique au client.
        texte = msg.content or ""
        if not tool_calls and "<function=" in texte:
            appels_dans_texte = _recuperer_appels_mal_formes(texte)
            if appels_dans_texte:
                return LLMResponse(text="", tool_calls=appels_dans_texte, provider_used=self._name)

        return LLMResponse(text=texte, tool_calls=tool_calls, provider_used=self._name)
