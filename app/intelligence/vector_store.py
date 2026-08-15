"""Index vectoriel hybride et persistant pour la base de connaissances RAG.

Les passages restent dans les documents source et dans le manifest documentaire.
Ce module persiste uniquement les embeddings calculés afin d'éviter de les
reconstruire à chaque redémarrage. La recherche dense est complétée par une
vraie recherche TF-IDF, ce qui garde le RAG utilisable hors-ligne si le modèle
d'embeddings n'est pas disponible.
"""

from __future__ import annotations

from collections import Counter
from functools import lru_cache
import hashlib
import json
import logging
import math
import re
import unicodedata
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_EMBEDDING_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"
_EMBEDDING_INDEX_VERSION = 1
_STOP_WORDS = {
    # Français
    "a", "ai", "au", "aux", "avec", "ce", "ces", "comment", "dans", "de", "des", "du", "elle",
    "en", "est", "et", "il", "je", "la", "le", "les", "ma", "mes", "mon", "nous", "on", "ou",
    "par", "pas", "pour", "que", "quel", "quelle", "quelles", "quels", "question", "sa", "se", "son",
    "sur", "tu", "un", "une", "vers", "vos", "votre", "vous", "y",
    # English (documents et requêtes multilingues)
    "an", "and", "are", "at", "be", "by", "can", "do", "for", "from", "how", "in", "is", "it",
    "of", "or", "the", "to", "was", "what", "when", "where", "which", "who", "with", "your",
}


def _strip_accents(text: str) -> str:
    text = unicodedata.normalize("NFD", (text or "").lower())
    return "".join(char for char in text if unicodedata.category(char) != "Mn")


def _tokens(text: str) -> list[str]:
    return [
        token
        for token in re.findall(r"[a-z0-9]+", _strip_accents(text))
        if token not in _STOP_WORDS and len(token) > 1
    ]


@lru_cache(maxsize=2)
def _get_embedding_model(allow_remote_model_download: bool):
    """Partage le modèle local entre les assistants de langues différentes."""
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(
        _EMBEDDING_MODEL,
        local_files_only=not allow_remote_model_download,
    )


def _entry_text(entry: dict[str, Any]) -> str:
    source = entry.get("source") or {}
    source_context = " ".join(
        str(value)
        for value in (source.get("title"), source.get("section"), source.get("filename"))
        if value
    )
    return " ".join(
        part
        for part in (
            str(entry.get("question", "")),
            " ".join(entry.get("mots_cles", []) or []),
            str(entry.get("text") or entry.get("reponse", "")),
            source_context,
        )
        if part
    )


def format_source_citation(source: dict[str, Any]) -> str:
    """Construit une citation courte, explicite et sans chemin local absolu."""
    title = source.get("title") or source.get("filename") or "Base de connaissances interne"
    parts = [str(title)]
    section = source.get("section")
    page = source.get("page")
    if section:
        parts.append(str(section))
    if page is not None:
        parts.append(f"p. {page}")
    return " — ".join(parts)


class VectorStore:
    """Recherche hybride sur des passages de connaissances enrichis de provenance."""

    def __init__(
        self,
        entries: list[dict[str, Any]],
        *,
        index_dir: str | Path | None = None,
        min_dense_score: float = 0.22,
        min_lexical_score: float = 0.035,
        allow_remote_model_download: bool = False,
    ) -> None:
        self.entries = entries
        self._texts = [_entry_text(entry) for entry in entries]
        self._model = None
        self.embeddings: Any | None = None
        self._search_cache: dict[tuple[str, int], list[dict[str, Any]]] = {}
        self.min_dense_score = min_dense_score
        self.min_lexical_score = min_lexical_score
        self.allow_remote_model_download = allow_remote_model_download
        self.index_dir = Path(index_dir).resolve() if index_dir is not None else None
        self._fingerprint = self._entries_fingerprint()

        self._build_lexical_index()
        self._load_dense_index()

    def _entries_fingerprint(self) -> str:
        payload = [
            {
                "id": entry.get("id"),
                "text": _entry_text(entry),
                "source": entry.get("source", {}),
            }
            for entry in self.entries
        ]
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _build_lexical_index(self) -> None:
        self._document_vectors: list[dict[str, float]] = []
        document_frequencies: Counter[str] = Counter()
        all_terms: list[list[str]] = []

        for text in self._texts:
            terms = _tokens(text)
            all_terms.append(terms)
            document_frequencies.update(set(terms))

        count = max(len(self.entries), 1)
        self._idf = {
            term: math.log((1 + count) / (1 + frequency)) + 1.0
            for term, frequency in document_frequencies.items()
        }
        for terms in all_terms:
            self._document_vectors.append(self._normalise_vector(terms))

    def _normalise_vector(self, terms: list[str]) -> dict[str, float]:
        frequencies = Counter(terms)
        total = len(terms) or 1
        vector = {
            term: (frequency / total) * self._idf.get(term, 1.0)
            for term, frequency in frequencies.items()
        }
        norm = math.sqrt(sum(value * value for value in vector.values())) or 1.0
        return {term: value / norm for term, value in vector.items()}

    def _embedding_paths(self) -> tuple[Path, Path] | tuple[None, None]:
        if self.index_dir is None:
            return None, None
        return self.index_dir / "embeddings.npy", self.index_dir / "embeddings.json"

    def _load_dense_index(self) -> None:
        """Charge les embeddings persistés ou les génère une seule fois."""
        if not self.entries:
            return
        try:
            import numpy as np
            # Ne jamais bloquer le démarrage de l'API sur un téléchargement implicite.
            # L'installation du modèle peut être autorisée explicitement via la config.
            self._model = _get_embedding_model(self.allow_remote_model_download)
            if self._load_cached_embeddings(np):
                return

            self.embeddings = self._model.encode(self._texts, normalize_embeddings=True)
            self.embeddings = np.asarray(self.embeddings, dtype="float32")
            self._persist_embeddings(np)
            logger.info("[RAG] Embeddings calculés pour %s passages.", len(self.entries))
        except Exception as exc:  # noqa: BLE001 - le fallback lexical doit toujours rester disponible.
            self._model = None
            self.embeddings = None
            logger.info("[RAG] Embeddings indisponibles (%s) ; recherche TF-IDF activée.", exc)

    def _load_cached_embeddings(self, np: Any) -> bool:
        embedding_path, manifest_path = self._embedding_paths()
        if embedding_path is None or manifest_path is None:
            return False
        try:
            if not embedding_path.exists() or not manifest_path.exists():
                return False
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if (
                manifest.get("version") != _EMBEDDING_INDEX_VERSION
                or manifest.get("model") != _EMBEDDING_MODEL
                or manifest.get("fingerprint") != self._fingerprint
                or manifest.get("entry_count") != len(self.entries)
            ):
                return False
            embeddings = np.load(str(embedding_path), allow_pickle=False)
            if len(embeddings) != len(self.entries):
                return False
            self.embeddings = embeddings
            logger.info("[RAG] Embeddings persistés rechargés : %s passages.", len(self.entries))
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("[RAG] Cache d'embeddings ignoré : %s", exc)
            return False

    def _persist_embeddings(self, np: Any) -> None:
        embedding_path, manifest_path = self._embedding_paths()
        if embedding_path is None or manifest_path is None or self.embeddings is None:
            return
        try:
            self.index_dir.mkdir(parents=True, exist_ok=True)
            temporary_embedding = embedding_path.with_suffix(".tmp")
            with temporary_embedding.open("wb") as stream:
                np.save(stream, self.embeddings)
            temporary_embedding.replace(embedding_path)

            temporary_manifest = manifest_path.with_suffix(".tmp")
            temporary_manifest.write_text(
                json.dumps(
                    {
                        "version": _EMBEDDING_INDEX_VERSION,
                        "model": _EMBEDDING_MODEL,
                        "fingerprint": self._fingerprint,
                        "entry_count": len(self.entries),
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            temporary_manifest.replace(manifest_path)
        except OSError as exc:
            logger.warning("[RAG] Embeddings non persistés : %s", exc)

    def _lexical_scores(self, query: str) -> list[float]:
        query_terms = _tokens(query)
        if not query_terms:
            return [0.0] * len(self.entries)
        query_vector = self._normalise_vector(query_terms)
        return [
            sum(query_vector.get(term, 0.0) * document_vector.get(term, 0.0) for term in query_vector)
            for document_vector in self._document_vectors
        ]

    @staticmethod
    def _is_document_source(entry: dict[str, Any]) -> bool:
        return (entry.get("source") or {}).get("source_type") == "document"

    @staticmethod
    def _prefer_primary_documents(query: str) -> bool:
        normalized = _strip_accents(query)
        keywords = {
            "cgv", "condition generale", "article", "indemnisation", "remboursement",
            "responsabilite", "assurance", "reclamation", "plainte", "facture",
            "paiement", "douane", "juridiction", "prescription", "retenion", "gage",
        }
        return any(keyword in normalized for keyword in keywords)

    def _result(self, entry: dict[str, Any], score: float) -> dict[str, Any]:
        source = dict(entry.get("source") or {})
        if not source:
            source = {
                "document_id": f"faq_{entry.get('id', 'entry')}",
                "title": "FAQ TexMiles",
                "filename": "faq",
                "source_type": "faq",
            }
        return {
            "id": entry.get("id", ""),
            "score": round(float(score), 4),
            "question": entry.get("question", ""),
            "reponse": entry.get("reponse") or entry.get("text", ""),
            "source": source,
            "citation": format_source_citation(source),
        }

    def search(self, query: str, limit: int = 3) -> list[dict[str, Any]]:
        """Retourne les passages pertinents avec leur provenance complète."""
        query = (query or "").strip()
        if not query or not self.entries:
            return []
        cache_key = (query.casefold(), limit)
        if cache_key in self._search_cache:
            return self._search_cache[cache_key]

        lexical_scores = self._lexical_scores(query)
        dense_scores: list[float | None] = [None] * len(self.entries)
        if self._model is not None and self.embeddings is not None:
            try:
                import numpy as np

                query_embedding = self._model.encode([query], normalize_embeddings=True)[0]
                dense_scores = [float(value) for value in np.dot(self.embeddings, query_embedding)]
            except Exception as exc:  # noqa: BLE001
                logger.warning("[RAG] Recherche dense indisponible : %s", exc)

        prefer_documents = self._prefer_primary_documents(query)
        candidates: list[tuple[int, float | None, float]] = []
        for index, entry in enumerate(self.entries):
            dense = dense_scores[index]
            lexical = lexical_scores[index]
            is_candidate = (
                (dense is not None and dense >= self.min_dense_score)
                or lexical >= self.min_lexical_score
            )
            if not is_candidate:
                continue
            candidates.append((index, dense, lexical))

        # Lorsqu'une question vise explicitement une politique/CGV, les documents
        # internes priment sur une FAQ éventuellement recopiée. On ne bascule vers
        # cette règle que s'il existe un passage documentaire avec un vrai recouvrement.
        if prefer_documents:
            primary_candidates = [
                item
                for item in candidates
                if self._is_document_source(self.entries[item[0]]) and item[2] >= self.min_lexical_score
            ]
            if primary_candidates:
                candidates = primary_candidates

        ranked: list[tuple[float, int, float]] = []
        for index, dense, lexical in candidates:
            if prefer_documents and self._is_document_source(self.entries[index]):
                # Pour une source primaire, la correspondance lexicale garde les
                # termes juridiques/article plus discriminants que la similarité dense.
                combined = lexical if dense is None else (0.30 * dense + 0.70 * lexical)
            else:
                combined = lexical if dense is None else (0.72 * dense + 0.28 * lexical)
            # Les documents internes sont des sources primaires : ils passent avant
            # une FAQ recopiée lorsque la question porte explicitement sur une politique.
            if self._is_document_source(self.entries[index]):
                combined += 0.035
                if prefer_documents:
                    combined += 0.12
            ranked.append((combined, index, dense if dense is not None else lexical))

        ranked.sort(key=lambda item: item[0], reverse=True)
        results = [self._result(self.entries[index], raw_score) for _, index, raw_score in ranked[:limit]]
        if len(self._search_cache) >= 256:
            self._search_cache.clear()
        self._search_cache[cache_key] = results
        return results

    # Nom historique conservé pour les appels existants du projet.
    def search_vector(self, query: str, limit: int = 3) -> list[dict[str, Any]]:
        return self.search(query, limit=limit)
