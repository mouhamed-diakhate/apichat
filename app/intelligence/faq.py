"""Base de connaissances RAG de TexMiles.

La FAQ JSON reste une source éditable, mais elle est maintenant réunie avec les
documents internes (PDF, DOCX, Markdown, TXT et HTML). Chaque résultat conserve
la provenance utilisée pour produire une citation fiable dans la réponse client.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.intelligence.pdf_loader import index_documents_in_data_folder
from app.intelligence.vector_store import VectorStore


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _resolve_path(path: str | Path) -> Path:
    """Résout les chemins relatifs depuis le projet, même hors du serveur ASGI."""
    candidate = Path(path)
    if candidate.exists() or candidate.is_absolute():
        return candidate.resolve()
    return (_project_root() / candidate).resolve()


def _faq_source(entry: dict[str, Any], faq_path: Path) -> dict[str, Any]:
    """Ajoute une provenance uniforme aux entrées FAQ historiques."""
    source = dict(entry.get("source") or {})
    if source:
        source.setdefault("source_type", "faq")
        source.setdefault("title", "FAQ TexMiles")
        source.setdefault("filename", faq_path.name)
        source.setdefault("document_id", f"faq_{faq_path.stem}")
        return source

    section = str(entry.get("id") or "question").replace("_", " ")
    return {
        "document_id": f"faq_{faq_path.stem}",
        "title": "FAQ TexMiles",
        "filename": faq_path.name,
        "path": faq_path.name,
        "page": None,
        "section": section,
        "source_type": "faq",
    }


class FaqBase:
    """Recherche hybride sur FAQ et documents internes, avec provenance citée."""

    def __init__(
        self,
        chemin_fichier: str | Path,
        *,
        data_dir: str | Path | None = None,
        index_dir: str | Path | None = None,
        allow_remote_model_download: bool = False,
    ) -> None:
        self.faq_path = _resolve_path(chemin_fichier)
        raw_data = json.loads(self.faq_path.read_text(encoding="utf-8"))
        raw_entries = raw_data.get("entrees", [])
        if not isinstance(raw_entries, list):
            raise ValueError(f"Format FAQ invalide : {self.faq_path}")

        self.data_dir = _resolve_path(data_dir) if data_dir is not None else self.faq_path.parent
        self.index_dir = (
            _resolve_path(index_dir)
            if index_dir is not None
            else self.data_dir / ".rag" / self.faq_path.stem
        )
        self.entrees: list[dict[str, Any]] = []
        for raw_entry in raw_entries:
            entry = dict(raw_entry)
            entry.setdefault("id", f"faq_{len(self.entrees) + 1:03d}")
            entry.setdefault("question", "Question FAQ")
            entry.setdefault("reponse", "")
            entry.setdefault("mots_cles", [])
            entry["text"] = entry.get("text") or entry["reponse"]
            entry["source"] = _faq_source(entry, self.faq_path)
            self.entrees.append(entry)

        # Les documents internes sont mis en cache par checksum. Les nouvelles versions
        # sont détectées automatiquement à la prochaine construction de l'assistant.
        self.document_entries = index_documents_in_data_folder(
            self.data_dir,
            # Les documents sont communs à toutes les langues ; un seul manifest
            # évite de réextraire le même PDF pour chaque assistant linguistique.
            index_dir=self.data_dir / ".rag" / "documents",
        )
        existing_ids = {str(entry.get("id")) for entry in self.entrees}
        self.entrees.extend(
            entry for entry in self.document_entries if str(entry.get("id")) not in existing_ids
        )

        self._search_cache: dict[tuple[str, int], list[dict[str, Any]]] = {}
        self.vector_store = VectorStore(
            self.entrees,
            index_dir=self.index_dir / "vectors",
            allow_remote_model_download=allow_remote_model_download,
        )

    def search(self, requete: str, limite: int = 2) -> list[dict[str, Any]]:
        """Retourne des passages RAG avec ``source`` et ``citation``.

        Une liste vide signifie qu'aucune source assez pertinente n'a été trouvée ;
        l'orchestrateur doit alors s'abstenir d'inventer une politique ou une réponse.
        """
        normalized_query = (requete or "").strip()
        if not normalized_query or limite <= 0:
            return []
        cache_key = (normalized_query.casefold(), limite)
        if cache_key not in self._search_cache:
            self._search_cache[cache_key] = self.vector_store.search(normalized_query, limit=limite)
            if len(self._search_cache) > 256:
                self._search_cache.clear()
        return self._search_cache.get(cache_key, [])
