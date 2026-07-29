"""
Base de connaissances FAQ avec recherche sémantique TF-IDF (RAG léger).

Le contenu vit dans data/faq.{fr,en,wo}.json et se modifie SANS toucher au code
(exigence du cahier des charges §4.3).

L'indexation utilise l'algorithme TF-IDF (Term Frequency - Inverse Document Frequency)
avec similarité cosinus. Cela permet de retrouver la bonne réponse même si le client
utilise des synonymes, des mots au pluriel ou une structure de phrase différente.
"""

import json
import math
import re
import unicodedata
from collections import Counter
from pathlib import Path


def _sans_accents(texte: str) -> str:
    """Passe en minuscules et retire les accents pour comparer plus souplement."""
    texte = (texte or "").lower()
    texte = unicodedata.normalize("NFD", texte)
    return "".join(c for c in texte if unicodedata.category(c) != "Mn")


# Petits mots vides (stop words) multilingues
_MOTS_VIDES = {
    # Français
    "le", "la", "les", "un", "une", "des", "de", "du", "et", "ou", "a", "au",
    "aux", "je", "tu", "il", "vous", "nous", "mon", "ma", "mes", "votre", "vos",
    "est", "quel", "quels", "quelle", "quelles", "que", "quoi", "comment",
    "pour", "avec", "sur", "en", "ce", "cette", "sont", "ai", "as", "svp",
    # English
    "the", "a", "an", "and", "or", "in", "on", "at", "to", "for", "with", "is",
    "are", "was", "were", "be", "been", "my", "your", "our", "what", "where",
    "when", "how", "can", "do", "does", "please",
    # Wolof
    "am", "bi", "yi", "ci", "bu", "la", "na", "ne", "ak", "te", "mooy", "ba",
}


def _tokeniser(texte: str) -> list[str]:
    """Extrait les mots significatifs (tokens) d'un texte."""
    mots = re.findall(r"[a-z0-9]+", _sans_accents(texte))
    return [m for m in mots if m not in _MOTS_VIDES and len(m) > 1]


class FaqBase:
    def __init__(self, chemin_fichier: str):
        donnees = json.loads(Path(chemin_fichier).read_text(encoding="utf-8"))
        self.entrees = donnees["entrees"]
        self._search_cache: dict[tuple[str, int], list[dict]] = {}
        self._indexer_tfidf()


    def _indexer_tfidf(self) -> None:
        """Construit la matrice TF-IDF et l'index documentaire à l'initialisation."""
        self.doc_vectors = []
        self.idf = {}
        num_docs = len(self.entrees)
        doc_freqs = Counter()

        # 1. Tokenisation de chaque entrée de la FAQ
        doc_tokens_list = []
        for entree in self.entrees:
            # On combine la question, les mots-clés (répétés pour plus de poids) et la réponse
            mots_cles = entree.get("mots_cles", [])
            texte_combini = (
                entree["question"] + " " +
                " ".join(mots_cles) * 2 + " " +
                entree.get("reponse", "")
            )
            tokens = _tokeniser(texte_combini)
            doc_tokens_list.append(tokens)
            doc_freqs.update(set(tokens))

        # 2. Calcul des poids IDF (Inverse Document Frequency)
        for token, df in doc_freqs.items():
            self.idf[token] = math.log((1 + num_docs) / (1 + df)) + 1.0

        # 3. Vectorisation TF-IDF de chaque document
        for tokens in doc_tokens_list:
            tf = Counter(tokens)
            total_tokens = len(tokens) or 1
            vec = {}
            norm_sq = 0.0
            for token, count in tf.items():
                val = (count / total_tokens) * self.idf.get(token, 1.0)
                vec[token] = val
                norm_sq += val * val

            norm = math.sqrt(norm_sq) or 1.0
            # Normalisation L2 du vecteur
            normalized_vec = {t: v / norm for t, v in vec.items()}
            self.doc_vectors.append(normalized_vec)

    def search(self, requete: str, limite: int = 2) -> list[dict]:
        """Renvoie les meilleures entrées (question + réponse) par similarité sémantique TF-IDF (avec cache)."""
        cache_key = (requete.strip().lower(), limite)
        if cache_key in self._search_cache:
            return self._search_cache[cache_key]

        tokens_req = _tokeniser(requete)
        if not tokens_req:
            return []

        # Vectoriser la requête
        tf_req = Counter(tokens_req)
        total_req = len(tokens_req)
        vec_req = {}
        norm_sq = 0.0
        for token, count in tf_req.items():
            val = (count / total_req) * self.idf.get(token, 1.0)
            vec_req[token] = val
            norm_sq += val * val

        norm = math.sqrt(norm_sq) or 1.0
        vec_req = {t: v / norm for t, v in vec_req.items()}

        # Calculer la similarité cosinus avec chaque document
        scores = []
        for idx, (entree, vec_doc) in enumerate(zip(self.entrees, self.doc_vectors)):
            similarity = sum(vec_req[t] * vec_doc[t] for t in vec_req if t in vec_doc)
            if similarity > 0.01:
                scores.append({
                    "score": round(similarity, 4),
                    "question": entree["question"],
                    "reponse": entree["reponse"],
                })

        # Trier par score de similarité cosinus décroissant
        scores.sort(key=lambda x: x["score"], reverse=True)
        res = scores[:limite]

        # Limite du cache à 256 entrées
        if len(self._search_cache) > 256:
            self._search_cache.clear()
        self._search_cache[cache_key] = res
        return res


