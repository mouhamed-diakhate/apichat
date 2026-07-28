"""
Source des commandes + vérification d'identité (garde-fou obligatoire).

Deux implémentations disponibles :
- MockOrderSource : lit un fichier JSON (pour démo / hors-ligne).
- DatabaseOrderSource : lit directement la table `orders` dans PostgreSQL.

Règle métier importante (cahier des charges §4.2 et §5) :
l'assistant ne doit JAMAIS divulguer les détails d'une commande sans une
identification minimale, et doit rester prudent en cas d'incohérence.
"""

import json
from abc import ABC, abstractmethod
from pathlib import Path


def _normaliser_numero(valeur: str) -> str:
    """
    Normalise un numéro de commande pour la recherche :
    Supprime tirets (-), espaces ( ), points (.) et passe en majuscules.
    Exemple: 'CMD-1002' -> 'CMD1002', 'cmd 1002' -> 'CMD1002'
    """
    if not valeur:
        return ""
    return valeur.replace("-", "").replace(".", "").replace(" ", "").strip().upper()


def _normaliser_tel(valeur: str) -> str:
    """
    Normalise un numéro de téléphone sénégalais pour la comparaison :
    - Supprime espaces, tirets, points, parenthèses
    - Supprime le préfixe international (+221 ou 00221) pour harmoniser
      avec les saisies locales (ex: 770001122 == +221770001122).
    """
    if not valeur:
        return ""
    tel = (
        valeur.replace(" ", "")
        .replace(".", "")
        .replace("-", "")
        .replace("(", "")
        .replace(")", "")
        .strip()
    )
    # Normaliser vers le format local (9 chiffres) sans indicatif
    if tel.startswith("+221"):
        tel = tel[4:]
    elif tel.startswith("00221"):
        tel = tel[5:]
    elif tel.startswith("221") and len(tel) == 12:
        tel = tel[3:]
    return tel


class OrderSource(ABC):
    """Contrat d'une source de commandes."""

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
        num_norm = _normaliser_numero(numero)
        for c in self.commandes:
            if _normaliser_numero(c["numero"]) == num_norm:
                return c
        return None

    def find(self, numero=None, telephone=None, email=None) -> dict:
        numero_brut = numero
        numero = _normaliser_numero(numero or "")
        telephone = _normaliser_tel(telephone or "")
        email = (email or "").strip().lower()

        if not numero and not telephone and not email:
            return {"resultat": "identite_manquante"}

        if numero:
            commande = self._par_numero(numero)
            if commande is None:
                return {"resultat": "introuvable"}
            if not telephone and not email:
                return {
                    "resultat": "confirmation_identite_requise",
                    "consigne": "Un numéro de commande seul ne suffit pas. Demandez au client son téléphone ou son email de confirmation avant de donner le statut."
                }
            if telephone and _normaliser_tel(commande["telephone"]) != telephone:
                return {"resultat": "incoherence"}
            if email and commande["email"].lower() != email:
                return {"resultat": "incoherence"}
            return {"resultat": "ok", "commande": commande}

        for c in self.commandes:
            if telephone and _normaliser_tel(c["telephone"]) == telephone:
                return {"resultat": "ok", "commande": c}
            if email and c["email"].lower() == email:
                return {"resultat": "ok", "commande": c}

        return {"resultat": "introuvable"}


class DatabaseOrderSource(OrderSource):
    """Implémentation réelle : lit les commandes directement dans PostgreSQL."""

    def __init__(self, session_factory):
        self.session_factory = session_factory

    def find(self, numero=None, telephone=None, email=None) -> dict:
        from app.models.order import Order

        numero_norm = _normaliser_numero(numero or "")
        telephone = _normaliser_tel(telephone or "")
        email = (email or "").strip().lower()

        if not numero_norm and not telephone and not email:
            return {"resultat": "identite_manquante"}

        db = self.session_factory()
        try:
            if numero_norm:
                commandes = db.query(Order).all()
                commande = None
                for c in commandes:
                    if _normaliser_numero(c.numero or "") == numero_norm:
                        commande = c
                        break
                if not commande:
                    return {"resultat": "introuvable"}


                # Règle de sécurité / confidentialité : un numéro de commande seul ne suffit pas.
                # Il faut AU MOINS un téléphone ou un email pour valider l'identité.
                if not telephone and not email:
                    return {
                        "resultat": "confirmation_identite_requise",
                        "consigne": "Un numéro de commande seul ne suffit pas. Demandez au client son téléphone ou son email de confirmation avant de donner le statut."
                    }

                if telephone and _normaliser_tel(commande.telephone or "") != telephone:
                    return {"resultat": "incoherence"}
                if email and (commande.email or "").lower() != email:
                    return {"resultat": "incoherence"}

                return {
                    "resultat": "ok",
                    "commande": {
                        "numero": commande.numero,
                        "client": commande.client,
                        "telephone": commande.telephone,
                        "email": commande.email,
                        "statut": commande.statut,
                        "date_estimee": commande.date_estimee,
                        "articles": json.loads(commande.articles) if commande.articles and commande.articles.startswith("[") else commande.articles,
                    }
                }

            commandes = db.query(Order).all()
            for c in commandes:
                match_tel = telephone and _normaliser_tel(c.telephone or "") == telephone
                match_email = email and (c.email or "").lower() == email
                if match_tel or match_email:
                    return {
                        "resultat": "ok",
                        "commande": {
                            "numero": c.numero,
                            "client": c.client,
                            "telephone": c.telephone,
                            "email": c.email,
                            "statut": c.statut,
                            "date_estimee": c.date_estimee,
                            "articles": json.loads(c.articles) if c.articles and c.articles.startswith("[") else c.articles,
                        }
                    }

            return {"resultat": "introuvable"}
        finally:
            db.close()
