"""
Source des commandes + vérification d'identité (garde-fou obligatoire).

Aujourd'hui les données sont FICTIVES (MockOrderSource lit un fichier JSON).
Demain, une vraie API commandes remplacera MockOrderSource : il suffira d'écrire
une nouvelle classe qui hérite de OrderSource et implémente find(). Le reste du
code (orchestrateur, outils) ne changera pas.

Règle métier importante (cahier des charges §4.2 et §5) :
l'assistant ne doit JAMAIS divulguer les détails d'une commande sans une
identification minimale, et doit rester prudent en cas d'incohérence. Cette règle
est appliquée ICI, dans le code — pas seulement dans le prompt — pour qu'elle ne
puisse pas être contournée par une formulation habile du client.
"""

import json
from abc import ABC, abstractmethod
from pathlib import Path


def _normaliser_tel(valeur: str) -> str:
    """Enlève espaces, points et tirets pour comparer les numéros de façon fiable."""
    if not valeur:
        return ""
    return (
        valeur.replace(" ", "")
        .replace(".", "")
        .replace("-", "")
        .strip()
    )


class OrderSource(ABC):
    """Contrat d'une source de commandes (mock aujourd'hui, vraie API demain)."""

    @abstractmethod
    def find(self, numero=None, telephone=None, email=None) -> dict:
        """
        Renvoie un dict avec une clé "resultat" parmi :
        - "ok"                -> + "commande": {...}
        - "introuvable"       -> aucune commande ne correspond
        - "incoherence"       -> les infos fournies ne correspondent pas (suspect)
        - "identite_manquante"-> aucun identifiant fourni
        """
        raise NotImplementedError


class MockOrderSource(OrderSource):
    """Implémentation fictive : lit les commandes depuis un fichier JSON."""

    def __init__(self, chemin_fichier: str):
        donnees = json.loads(Path(chemin_fichier).read_text(encoding="utf-8"))
        self.commandes = donnees["commandes"]

    def _par_numero(self, numero: str):
        numero = (numero or "").strip().upper()
        for c in self.commandes:
            if c["numero"].upper() == numero:
                return c
        return None

    def find(self, numero=None, telephone=None, email=None) -> dict:
        numero = (numero or "").strip()
        telephone = _normaliser_tel(telephone or "")
        email = (email or "").strip().lower()

        # Cas 0 : le client n'a fourni aucun identifiant -> on ne peut rien faire.
        if not numero and not telephone and not email:
            return {"resultat": "identite_manquante"}

        # Cas 1 : un numéro de commande est fourni (identifiant le plus précis).
        if numero:
            commande = self._par_numero(numero)
            if commande is None:
                return {"resultat": "introuvable"}
            # Si le client donne AUSSI un téléphone/email, ils doivent correspondre.
            # Une incohérence est suspecte -> on ne divulgue rien (prudence).
            if telephone and _normaliser_tel(commande["telephone"]) != telephone:
                return {"resultat": "incoherence"}
            if email and commande["email"].lower() != email:
                return {"resultat": "incoherence"}
            return {"resultat": "ok", "commande": commande}

        # Cas 2 : pas de numéro, mais un téléphone ou un email (identité minimale).
        for c in self.commandes:
            if telephone and _normaliser_tel(c["telephone"]) == telephone:
                return {"resultat": "ok", "commande": c}
            if email and c["email"].lower() == email:
                return {"resultat": "ok", "commande": c}

        return {"resultat": "introuvable"}
