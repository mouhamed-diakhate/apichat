"""
Base de connaissances FAQ (mini "RAG").

Le contenu vit dans data/faq.fr.json et se modifie SANS toucher au code
(exigence du cahier des charges §4.3). Ici, on fait une recherche très simple par
mots-clés : on compte combien de mots de la question du client apparaissent dans
chaque entrée, et on renvoie les meilleures. Suffisant pour le MVP ; on pourra
brancher une vraie recherche sémantique (embeddings) plus tard, derrière la même
méthode search().
"""

import json
import re
import unicodedata
from pathlib import Path


def _sans_accents(texte: str) -> str:
    """Passe en minuscules et retire les accents pour comparer plus souplement."""
    texte = texte.lower()
    texte = unicodedata.normalize("NFD", texte)
    return "".join(c for c in texte if unicodedata.category(c) != "Mn")


# Petits mots à ignorer : ils n'aident pas à distinguer les questions.
_MOTS_VIDES = {
    "le", "la", "les", "un", "une", "des", "de", "du", "et", "ou", "a", "au",
    "aux", "je", "tu", "il", "vous", "nous", "mon", "ma", "mes", "votre", "vos",
    "est", "quel", "quels", "quelle", "quelles", "que", "quoi", "comment",
    "pour", "avec", "sur", "en", "ce", "cette", "sont", "ai", "as", "svp",
}


def _mots_utiles(texte: str) -> set[str]:
    mots = re.findall(r"[a-z0-9]+", _sans_accents(texte))
    return {m for m in mots if m not in _MOTS_VIDES and len(m) > 1}


class FaqBase:
    def __init__(self, chemin_fichier: str):
        donnees = json.loads(Path(chemin_fichier).read_text(encoding="utf-8"))
        self.entrees = donnees["entrees"]

    def search(self, requete: str, limite: int = 2) -> list[dict]:
        """Renvoie les meilleures entrées (question + réponse) pour la requête."""
        mots_requete = _mots_utiles(requete)
        resultats = []
        for e in self.entrees:
            # On cherche les mots de la requête dans la question + les mots-clés.
            corpus = _sans_accents(e["question"] + " " + " ".join(e["mots_cles"]))
            mots_corpus = set(re.findall(r"[a-z0-9]+", corpus))
            score = len(mots_requete & mots_corpus)
            if score > 0:
                resultats.append({"score": score, "question": e["question"], "reponse": e["reponse"]})
        resultats.sort(key=lambda r: r["score"], reverse=True)
        return resultats[:limite]
