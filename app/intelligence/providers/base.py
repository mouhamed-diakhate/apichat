"""
Interface commune à TOUS les fournisseurs de modèle (LLM).

Pourquoi ce fichier existe :
Le cahier des charges demande de pouvoir COMPARER plusieurs modèles (Grok, GPT,
Claude...) sur le même pipeline. Pour ça, le reste du code ne doit jamais parler
directement à un modèle précis : il parle seulement à cette interface abstraite.
Changer de modèle = écrire une nouvelle classe qui hérite de LLMProvider, sans
toucher à l'orchestrateur.

Format d'échange "neutre" (indépendant du fournisseur) :
- Un message = un dict :
    {"role": "user",      "content": "texte du client"}
    {"role": "assistant", "content": "texte", "tool_calls": [ToolCall, ...]}
    {"role": "tool",      "tool_call_id": "...", "name": "...", "content": "résultat"}
Chaque provider traduit ce format neutre vers/depuis le format de son API.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolCall:
    """Une demande du modèle d'exécuter un outil (ex. rechercher une commande)."""
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class LLMResponse:
    """La réponse du modèle : soit du texte, soit une (des) demande(s) d'outil."""
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)


class LLMProvider(ABC):
    """Contrat que chaque connecteur de modèle doit respecter."""

    @abstractmethod
    def chat(
        self,
        system: str,
        messages: list[dict],
        tools: list[dict] | None = None,
    ) -> LLMResponse:
        """
        Envoie la conversation au modèle et renvoie sa réponse.

        - system : les consignes de comportement (le "system prompt").
        - messages : l'historique au format neutre décrit en haut de ce fichier.
        - tools : la liste des outils disponibles (schéma JSON style OpenAI), ou None.
        """
        raise NotImplementedError
