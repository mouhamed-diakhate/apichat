"""Gestion durable des entrées de la FAQ éditable.

Le RAG utilise encore ``data/faq.fr.json`` comme source FAQ, mais ce module
évite aux agents d'avoir à manipuler ce JSON directement.  Toutes les
modifications passent par une validation applicative puis une écriture atomique
dans le même répertoire : un lecteur ne voit donc jamais un fichier partiel.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import threading
import unicodedata
from pathlib import Path
from typing import Any


class FaqManagementError(RuntimeError):
    """Erreur de lecture ou de persistance de la source FAQ."""


class FaqEntryNotFoundError(FaqManagementError):
    """L'identifiant demandé n'existe pas dans la FAQ."""


class FaqEntryConflictError(FaqManagementError):
    """Une création demanderait un identifiant déjà utilisé."""


_SAFE_ID = re.compile(r"^[a-z][a-z0-9_]{0,79}$")
_WRITE_LOCK = threading.RLock()


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _normalise_search_text(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value or "")
    without_accents = "".join(
        character for character in decomposed if not unicodedata.combining(character)
    )
    return without_accents.casefold()


def _slugify(value: str) -> str:
    """Construit un identifiant sûr et stable à partir de la question."""
    normalized = _normalise_search_text(value)
    slug = re.sub(r"[^a-z0-9]+", "_", normalized).strip("_")
    slug = slug[:80].rstrip("_")
    if not slug or not slug[0].isalpha():
        slug = f"faq_{slug}".rstrip("_")
    return (slug[:80].rstrip("_") or "faq")


def _public_entry(entry: dict[str, Any]) -> dict[str, Any]:
    """Ne retourne que les champs gérés par l'interface d'administration."""
    return {
        "id": str(entry["id"]),
        "question": str(entry.get("question") or ""),
        "reponse": str(entry.get("reponse") or ""),
        "mots_cles": list(entry.get("mots_cles") or []),
        # Certains contenus historiques utilisent cette indication. Elle reste
        # consultable, mais les formulaires ne peuvent pas injecter de métadonnées.
        "article": entry.get("article"),
    }


class FaqManagementService:
    """CRUD validé de ``faq.fr.json`` utilisé par le tableau de bord."""

    def __init__(self, faq_path: str | Path | None = None) -> None:
        self.faq_path = (
            Path(faq_path).resolve()
            if faq_path is not None
            else (_project_root() / "data" / "faq.fr.json").resolve()
        )

    def _load_document(self) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        try:
            raw_document = json.loads(self.faq_path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise FaqManagementError("Le fichier FAQ est introuvable.") from exc
        except (OSError, json.JSONDecodeError) as exc:
            raise FaqManagementError("Le fichier FAQ est illisible.") from exc

        if not isinstance(raw_document, dict) or not isinstance(raw_document.get("entrees"), list):
            raise FaqManagementError("Le format de la FAQ est invalide.")

        entries = raw_document["entrees"]
        seen_ids: set[str] = set()
        for entry in entries:
            if not isinstance(entry, dict):
                raise FaqManagementError("Le format d'une entrée FAQ est invalide.")
            entry_id = entry.get("id")
            if not isinstance(entry_id, str) or not _SAFE_ID.fullmatch(entry_id):
                raise FaqManagementError("Un identifiant FAQ existant est invalide.")
            if entry_id in seen_ids:
                raise FaqManagementError("Des identifiants FAQ existants sont dupliqués.")
            if (
                not isinstance(entry.get("question"), str)
                or not entry["question"].strip()
                or not isinstance(entry.get("reponse"), str)
                or not entry["reponse"].strip()
                or not isinstance(entry.get("mots_cles"), list)
                or not all(isinstance(keyword, str) for keyword in entry["mots_cles"])
            ):
                raise FaqManagementError("Le contenu d'une entrée FAQ existante est invalide.")
            seen_ids.add(entry_id)
        return raw_document, entries

    def _write_document(self, document: dict[str, Any]) -> None:
        """Écrit le JSON en UTF-8 puis le remplace atomiquement.

        ``os.replace`` garantit que le fichier final est soit l'ancienne version,
        soit la nouvelle version complète, y compris sous Windows puisque le fichier
        temporaire est fermé avant le remplacement.
        """
        temp_name: str | None = None
        try:
            self.faq_path.parent.mkdir(parents=True, exist_ok=True)
            descriptor, temp_name = tempfile.mkstemp(
                prefix=f".{self.faq_path.name}.",
                suffix=".tmp",
                dir=str(self.faq_path.parent),
                text=True,
            )
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
                json.dump(document, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_name, self.faq_path)
            temp_name = None
        except OSError as exc:
            raise FaqManagementError("La sauvegarde de la FAQ a échoué.") from exc
        finally:
            if temp_name:
                try:
                    os.unlink(temp_name)
                except OSError:
                    pass

    @staticmethod
    def _next_id(question: str, used_ids: set[str]) -> str:
        base = _slugify(question)
        candidate = base
        suffix = 2
        while candidate in used_ids:
            suffix_text = f"_{suffix}"
            candidate = f"{base[: 80 - len(suffix_text)].rstrip('_')}{suffix_text}"
            suffix += 1
        return candidate

    @staticmethod
    def _validate_id(entry_id: str) -> str:
        if not _SAFE_ID.fullmatch(entry_id):
            raise ValueError(
                "L'identifiant doit contenir seulement des minuscules, chiffres et "
                "traits de soulignement, et commencer par une lettre."
            )
        return entry_id

    def list_entries(
        self,
        *,
        query: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[dict[str, Any]], int]:
        """Liste ou filtre les entrées sans lancer une recherche RAG coûteuse."""
        with _WRITE_LOCK:
            _document, entries = self._load_document()
            public_entries = [_public_entry(entry) for entry in entries]

        normalized_query = _normalise_search_text(query or "").strip()
        if normalized_query:
            public_entries = [
                entry
                for entry in public_entries
                if normalized_query
                in _normalise_search_text(
                    " ".join(
                        [
                            entry["id"],
                            entry["question"],
                            entry["reponse"],
                            " ".join(str(keyword) for keyword in entry["mots_cles"]),
                        ]
                    )
                )
            ]

        total = len(public_entries)
        start = (page - 1) * page_size
        return public_entries[start : start + page_size], total

    def create_entry(
        self,
        *,
        question: str,
        reponse: str,
        mots_cles: list[str],
        entry_id: str | None = None,
    ) -> dict[str, Any]:
        with _WRITE_LOCK:
            document, entries = self._load_document()
            used_ids = {str(entry["id"]) for entry in entries}
            if entry_id is not None:
                entry_id = self._validate_id(entry_id)
                if entry_id in used_ids:
                    raise FaqEntryConflictError("Cet identifiant FAQ existe déjà.")
            else:
                entry_id = self._next_id(question, used_ids)

            entry = {
                "id": entry_id,
                "question": question,
                "mots_cles": mots_cles,
                "reponse": reponse,
            }
            entries.append(entry)
            self._write_document(document)
            return _public_entry(entry)

    def update_entry(self, entry_id: str, changes: dict[str, Any]) -> dict[str, Any]:
        self._validate_id(entry_id)
        with _WRITE_LOCK:
            document, entries = self._load_document()
            entry = next((item for item in entries if item["id"] == entry_id), None)
            if entry is None:
                raise FaqEntryNotFoundError("Entrée FAQ introuvable.")

            # Les champs autorisés sont intentionnellement limités : cela protège
            # les métadonnées RAG et évite de transformer l'API en éditeur JSON.
            for field in ("question", "reponse", "mots_cles"):
                if field in changes:
                    entry[field] = changes[field]
            self._write_document(document)
            return _public_entry(entry)

    def delete_entry(self, entry_id: str) -> None:
        self._validate_id(entry_id)
        with _WRITE_LOCK:
            document, entries = self._load_document()
            for index, entry in enumerate(entries):
                if entry["id"] == entry_id:
                    del entries[index]
                    self._write_document(document)
                    return
        raise FaqEntryNotFoundError("Entrée FAQ introuvable.")
