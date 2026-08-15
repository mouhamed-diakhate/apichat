"""Ingestion des documents internes pour la base de connaissances RAG.

Les documents sont la source de vérité du RAG. Chaque passage conserve les
métadonnées nécessaires à une citation vérifiable : document, page, section
et identifiant stable du passage.

Documents pris en charge : PDF, TXT, Markdown, HTML et DOCX. Les documents
doivent être placés dans ``data/knowledge/``. Les fichiers documentaires
directement dans ``data/`` restent aussi pris en charge pour compatibilité avec
le PDF CGV déjà présent dans le projet.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import unicodedata
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

logger = logging.getLogger(__name__)

_CHUNK_SIZE_WORDS = 140
_CHUNK_OVERLAP_WORDS = 30
_INDEX_VERSION = 4
_SUPPORTED_SUFFIXES = {".pdf", ".txt", ".md", ".markdown", ".html", ".htm", ".docx"}


def _slug(value: str) -> str:
    """Retourne un identifiant lisible et stable, sans information sensible."""
    normalized = unicodedata.normalize("NFKD", value)
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    normalized = re.sub(r"[^a-zA-Z0-9]+", "_", normalized).strip("_").lower()
    return normalized or "document"


def _checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _clean_text(text: str) -> str:
    """Nettoie le texte extrait tout en conservant le contenu documentaire."""
    text = (text or "").replace("\ufeff", "").replace("\ufffd", " ")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # Répare les mots coupés à la fin d'une ligne par l'extraction PDF.
    text = re.sub(r"(?<=\w)-\s*\n\s*(?=\w)", "", text)
    text = re.sub(r"(?m)^\s*(?:page\s*)?[-–—]?\s*\d+\s*[-–—]?\s*$", "", text, flags=re.IGNORECASE)

    paragraphs: list[str] = []
    current_lines: list[str] = []
    for raw_line in text.split("\n"):
        line = re.sub(r"\s+", " ", raw_line).strip()
        if not line:
            if current_lines:
                paragraphs.append(" ".join(current_lines))
                current_lines = []
            continue
        current_lines.append(line)
    if current_lines:
        paragraphs.append(" ".join(current_lines))

    return "\n\n".join(paragraphs).strip()


def _split_into_chunks(
    text: str,
    chunk_size: int = _CHUNK_SIZE_WORDS,
    overlap: int = _CHUNK_OVERLAP_WORDS,
) -> list[str]:
    """Découpe un texte en passages avec recouvrement, sans mélanger les pages."""
    words = text.split()
    if len(words) < 6:
        return []

    chunks: list[str] = []
    start = 0
    while start < len(words):
        target_end = min(start + chunk_size, len(words))
        end = target_end

        # Privilégier une fin de phrase proche de la taille cible.
        if target_end < len(words):
            lower_bound = max(start + max(chunk_size // 2, 20), target_end - 35)
            sentence_breaks = [
                position + 1
                for position in range(lower_bound, target_end)
                if re.search(r"[.!?][\]\)\"']?$", words[position])
            ]
            if sentence_breaks:
                end = sentence_breaks[-1]

        chunk = " ".join(words[start:end]).strip()
        if len(chunk.split()) >= 6:
            chunks.append(chunk)

        if end >= len(words):
            break
        start = max(end - overlap, start + 1)

    return chunks


def _title_from_filename(path: Path) -> str:
    title = re.sub(r"[_-]+", " ", path.stem).strip()
    return title.capitalize() or "Document interne"


def _title_from_first_page(text: str, fallback: str) -> str:
    """Utilise le titre visible du PDF quand il est disponible."""
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    candidates = [line for line in lines if line and len(line) <= 90]
    upper = [line for line in candidates[:8] if any(char.isalpha() for char in line) and line == line.upper()]
    if upper:
        return " ".join(upper[:3]).capitalize()
    return fallback


def _extract_section(text: str, fallback: str | None = None) -> str | None:
    """Extrait la référence d'article ou de section affichable au client."""
    articles = re.findall(r"(?i)\barticle\s+(\d+(?:[.\-]\d+)?)", text)
    if articles:
        # Dans les CGV, le titre « Article N » suit souvent le paragraphe auquel
        # il se rapporte. Le dernier repère est donc le plus fiable sur un passage.
        return f"Article {articles[-1].replace('-', '.')}"

    clauses = re.findall(r"(?<!\d)(\d+\.\d+)\s*(?:[-:–—])", text)
    if clauses:
        return f"Article {clauses[0]}"

    return fallback


def _safe_relative_path(path: Path, root: Path | None) -> str:
    if root is not None:
        try:
            return path.resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            pass
    return path.name


def _document_id(path: Path, root: Path | None, source_name: str | None = None) -> str:
    if source_name:
        return _slug(source_name)
    relative = _safe_relative_path(path, root)
    suffix = hashlib.sha1(relative.encode("utf-8")).hexdigest()[:8]
    return f"doc_{_slug(path.stem)}_{suffix}"


def _entry(
    *,
    document_id: str,
    title: str,
    path: Path,
    relative_path: str,
    checksum: str,
    text: str,
    page: int | None,
    section: str | None,
    chunk_index: int,
) -> dict[str, Any]:
    page_token = f"p{page:03d}" if page is not None else "document"
    chunk_id = f"{document_id}_{page_token}_c{chunk_index:03d}"
    source = {
        "document_id": document_id,
        "title": title,
        "filename": path.name,
        "path": relative_path,
        "page": page,
        "section": section,
        "chunk_index": chunk_index,
        "checksum": checksum,
        "source_type": "document",
    }
    question = title if not section else f"{title} — {section}"
    return {
        "id": chunk_id,
        "question": question,
        "mots_cles": [],
        "reponse": text,
        "text": text,
        "source": source,
    }


def _load_pdf_pages(path: Path) -> list[str]:
    try:
        try:
            import pymupdf as fitz
        except ImportError:  # Compatibilité avec les versions plus anciennes.
            import fitz  # type: ignore[no-redef]
    except ImportError:
        logger.error("[RAG] PyMuPDF est requis pour indexer les PDF : %s", path.name)
        return []

    try:
        document = fitz.open(str(path))
        try:
            return [page.get_text("text") or "" for page in document]
        finally:
            document.close()
    except Exception as exc:  # noqa: BLE001 - un document invalide ne bloque pas le service.
        logger.error("[RAG] Lecture PDF impossible (%s) : %s", path.name, exc)
        return []


def _load_docx_text(path: Path) -> str:
    try:
        with zipfile.ZipFile(path) as archive:
            xml = archive.read("word/document.xml")
        root = ElementTree.fromstring(xml)
        namespace = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
        paragraphs = []
        for paragraph in root.iter(f"{namespace}p"):
            value = "".join(node.text or "" for node in paragraph.iter(f"{namespace}t")).strip()
            if value:
                paragraphs.append(value)
        return "\n\n".join(paragraphs)
    except Exception as exc:  # noqa: BLE001
        logger.error("[RAG] Lecture DOCX impossible (%s) : %s", path.name, exc)
        return ""


class _HtmlTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:  # type: ignore[override]
        if tag.lower() in {"p", "br", "div", "li", "h1", "h2", "h3", "h4", "tr"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def _load_text_document(path: Path) -> str:
    if path.suffix.lower() == ".docx":
        return _load_docx_text(path)

    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        logger.error("[RAG] Lecture document impossible (%s) : %s", path.name, exc)
        return ""

    if path.suffix.lower() in {".html", ".htm"}:
        parser = _HtmlTextExtractor()
        parser.feed(raw)
        parser.close()
        return "".join(parser.parts)
    return raw


def load_document_as_knowledge_entries(
    chemin_document: str | Path,
    *,
    source_root: str | Path | None = None,
    source_name: str | None = None,
) -> list[dict[str, Any]]:
    """Extrait un document et renvoie des passages RAG citables.

    Un PDF est traité page par page : aucun passage ne traverse une frontière de
    page, ce qui garantit que la page affichée dans une citation est correcte.
    """
    path = Path(chemin_document)
    root = Path(source_root) if source_root is not None else None
    if not path.exists() or not path.is_file():
        logger.warning("[RAG] Document introuvable : %s", path)
        return []
    if path.suffix.lower() not in _SUPPORTED_SUFFIXES:
        logger.warning("[RAG] Format non pris en charge : %s", path.name)
        return []

    checksum = _checksum(path)
    relative_path = _safe_relative_path(path, root)
    document_id = _document_id(path, root, source_name)
    fallback_title = _title_from_filename(path)
    entries: list[dict[str, Any]] = []

    if path.suffix.lower() == ".pdf":
        raw_pages = _load_pdf_pages(path)
        if not raw_pages:
            return []

        title = _title_from_first_page(raw_pages[0], fallback_title)
        extracted_any = False
        for page_number, raw_page in enumerate(raw_pages, start=1):
            page_text = _clean_text(raw_page)
            if not page_text:
                continue
            extracted_any = True
            current_section = _extract_section(page_text)
            for chunk_index, chunk in enumerate(_split_into_chunks(page_text), start=1):
                # Une clause peut commencer dans le chunk précédent et se poursuivre
                # dans le suivant. On conserve alors sa référence au lieu de revenir
                # à l'article global de la page.
                chunk_section = _extract_section(chunk)
                if chunk_section:
                    # Ne pas remplacer « Article 6.2 » par le titre global
                    # « Article 6 » qui apparaît souvent en pied de page.
                    if not (
                        current_section
                        and current_section.startswith(f"{chunk_section}.")
                    ):
                        current_section = chunk_section
                entries.append(
                    _entry(
                        document_id=document_id,
                        title=title,
                        path=path,
                        relative_path=relative_path,
                        checksum=checksum,
                        text=chunk,
                        page=page_number,
                        section=current_section,
                        chunk_index=chunk_index,
                    )
                )
        if not extracted_any:
            logger.warning(
                "[RAG] Aucun texte extractible dans %s. Un PDF scanné exige une étape OCR.",
                path.name,
            )
    else:
        text = _clean_text(_load_text_document(path))
        title = fallback_title
        document_section = _extract_section(text)
        for chunk_index, chunk in enumerate(_split_into_chunks(text), start=1):
            entries.append(
                _entry(
                    document_id=document_id,
                    title=title,
                    path=path,
                    relative_path=relative_path,
                    checksum=checksum,
                    text=chunk,
                    page=None,
                    section=_extract_section(chunk, document_section),
                    chunk_index=chunk_index,
                )
            )

    logger.info("[RAG] Document indexé : %s (%s passages)", path.name, len(entries))
    return entries


def _discover_documents(data_dir: Path) -> list[Path]:
    """Découvre les documents internes sans indexer les données applicatives."""
    documents: list[Path] = []
    if not data_dir.exists():
        return documents

    # Compatibilité : un document existant à la racine de data/ reste indexé.
    for path in data_dir.iterdir():
        if path.is_file() and path.suffix.lower() in _SUPPORTED_SUFFIXES:
            documents.append(path)

    # Emplacement recommandé pour les documents métier ajoutés à l'avenir.
    knowledge_dir = data_dir / "knowledge"
    if knowledge_dir.is_dir():
        for path in knowledge_dir.rglob("*"):
            if path.is_file() and path.suffix.lower() in _SUPPORTED_SUFFIXES:
                documents.append(path)

    return sorted({path.resolve() for path in documents}, key=lambda item: item.as_posix().lower())


def index_documents_in_data_folder(
    data_dir: str | Path = "data",
    *,
    index_dir: str | Path | None = None,
) -> list[dict[str, Any]]:
    """Construit ou recharge le cache persistant des passages documentaires.

    Le manifest ne remplace pas les documents source : il évite seulement de les
    réextraire si aucun fichier n'a changé. Chaque ajout, suppression ou modification
    est détecté par checksum et reconstruit automatiquement l'index.
    """
    root = Path(data_dir).resolve()
    cache_dir = Path(index_dir).resolve() if index_dir is not None else root / ".rag" / "documents"
    manifest_path = cache_dir / "documents.json"
    documents = _discover_documents(root)
    sources = [
        {"path": _safe_relative_path(path, root), "checksum": _checksum(path)}
        for path in documents
    ]

    try:
        if manifest_path.exists():
            cached = json.loads(manifest_path.read_text(encoding="utf-8"))
            if (
                cached.get("version") == _INDEX_VERSION
                and cached.get("sources") == sources
                and isinstance(cached.get("entries"), list)
            ):
                logger.info("[RAG] Cache documentaire rechargé : %s passages", len(cached["entries"]))
                return cached["entries"]
    except Exception as exc:  # noqa: BLE001
        logger.warning("[RAG] Cache documentaire illisible, reconstruction : %s", exc)

    entries: list[dict[str, Any]] = []
    for path in documents:
        entries.extend(load_document_as_knowledge_entries(path, source_root=root))

    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        temporary_path = manifest_path.with_suffix(".tmp")
        temporary_path.write_text(
            json.dumps(
                {"version": _INDEX_VERSION, "sources": sources, "entries": entries},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        temporary_path.replace(manifest_path)
    except OSError as exc:
        # L'index en mémoire reste fonctionnel dans un environnement en lecture seule.
        logger.warning("[RAG] Cache documentaire non persisté : %s", exc)

    logger.info("[RAG] Base documentaire prête : %s passages, %s documents", len(entries), len(documents))
    return entries


# Alias conservés pour les intégrations existantes du projet.
def load_pdf_as_faq_entries(chemin_pdf: str, source_name: str | None = None) -> list[dict[str, Any]]:
    return load_document_as_knowledge_entries(chemin_pdf, source_name=source_name)


def index_pdfs_in_data_folder(data_dir: str = "data") -> list[dict[str, Any]]:
    root = Path(data_dir)
    return [
        entry
        for path in _discover_documents(root)
        if path.suffix.lower() == ".pdf"
        for entry in load_document_as_knowledge_entries(path, source_root=root)
    ]
