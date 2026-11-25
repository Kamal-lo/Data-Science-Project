"""
Stratégies de découpage (chunking) pour le corpus entreprise (T40).

Prend en charge 3 stratégies comparables (recall@k) :
- recursive_structure : respecte les titres Markdown, CHAPITRE/ARTICLE/SECTION et paragraphes FR/AR
- sentence : découpage par phrases FR/AR avec fenêtre glissante
- fixed : découpage par taille fixe avec chevauchement (baseline)
"""

from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass
from typing import List, Tuple

from rag_module.schemas import ChunkRecord, ChunkStrategy, CorpusDocument

# Détection des titres structurels courants dans les mémoires techniques et DCE marocains (FR & AR)
HEADING_PATTERN = re.compile(
    r"^(?:"
    r"#{1,6}\s+.+"
    r"|(?:CHAPITRE|ARTICLE|SECTION|PARTIE|ANNEXE)\s+[0-9IVXLCDM]+.*"
    r"|\d+(?:\.\d+){0,3}\s+[A-ZÀ-Ÿ\u0600-\u06FF].+"
    r"|(?:الفصل|المادة|القسم|الباب)\s+.+"
    r")$",
    re.MULTILINE,
)

SENTENCE_SPLIT_PATTERN = re.compile(r"(?<=[.!?؟۔])\s+(?=[A-ZÀ-Ÿ0-9\u0600-\u06FF\-•])")

# Namespace UUID stable pour garantir l'idempotence des upserts dans Qdrant
QDRANT_POINT_NAMESPACE = uuid.UUID("c3a8d4e2-7b1f-4c9a-9e21-8f5b2d4a6c10")


@dataclass
class _RawSpan:
    text: str
    section: str
    char_start: int
    char_end: int


def compute_content_hash(text: str) -> str:
    """Calcule une empreinte SHA-256 normalisée pour la déduplication."""
    normalized = re.sub(r"\s+", " ", text.strip())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def build_deterministic_point_id(
    company_id: str,
    doc_id: str,
    chunk_index: int,
    content_hash: str,
) -> str:
    """Génère un UUIDv5 déterministe pour éviter tout doublon lors d'une ré-indexation."""
    key = f"{company_id}::{doc_id}::{chunk_index}::{content_hash[:16]}"
    return str(uuid.uuid5(QDRANT_POINT_NAMESPACE, key))


class TextChunker:
    """Découpe un `CorpusDocument` en `ChunkRecord` prêts pour l'indexation Qdrant."""

    def __init__(
        self,
        strategy: ChunkStrategy = ChunkStrategy.RECURSIVE_STRUCTURE,
        chunk_size: int = 800,
        chunk_overlap: int = 120,
    ) -> None:
        if chunk_overlap >= chunk_size:
            raise ValueError("chunk_overlap doit être strictement inférieur à chunk_size.")
        self.strategy = strategy
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def chunk_document(self, document: CorpusDocument) -> List[ChunkRecord]:
        """Découpe un document en chunks traçables avec métadonnées complètes."""
        text = document.content.replace("\r\n", "\n").strip()
        if not text:
            return []

        if self.strategy == ChunkStrategy.FIXED:
            spans = self._chunk_fixed(text, default_section=document.metadata.title)
        elif self.strategy == ChunkStrategy.SENTENCE:
            spans = self._chunk_sentences(text, default_section=document.metadata.title)
        else:
            spans = self._chunk_recursive_structure(text, default_section=document.metadata.title)

        total = len(spans)
        records: List[ChunkRecord] = []
        for idx, span in enumerate(spans):
            content_hash = compute_content_hash(span.text)
            point_id = build_deterministic_point_id(
                company_id=document.metadata.company_id,
                doc_id=document.metadata.doc_id,
                chunk_index=idx,
                content_hash=content_hash,
            )
            records.append(
                ChunkRecord(
                    point_id=point_id,
                    chunk_id=f"{document.metadata.doc_id}::chunk_{idx}",
                    text=span.text,
                    page_or_section=span.section,
                    chunk_index=idx,
                    total_chunks=total,
                    char_start=span.char_start,
                    char_end=span.char_end,
                    content_hash=content_hash,
                    metadata=document.metadata,
                )
            )
        return records

    # ------------------------------------------------------------------
    # Stratégie 1 : Fixed window (baseline)
    # ------------------------------------------------------------------
    def _chunk_fixed(self, text: str, default_section: str) -> List[_RawSpan]:
        spans: List[_RawSpan] = []
        step = self.chunk_size - self.chunk_overlap
        start = 0
        length = len(text)

        while start < length:
            end = min(start + self.chunk_size, length)
            if end < length:
                # Évite de couper un mot au milieu si possible
                last_space = text.rfind(" ", start + int(self.chunk_size * 0.6), end)
                if last_space > start:
                    end = last_space
            chunk_text = text[start:end].strip()
            if chunk_text:
                spans.append(_RawSpan(text=chunk_text, section=default_section, char_start=start, char_end=end))
            if end >= length:
                break
            start = max(start + 1, end - self.chunk_overlap)
            if start >= length:
                break
        return spans

    # ------------------------------------------------------------------
    # Stratégie 2 : Sentence-based window
    # ------------------------------------------------------------------
    def _chunk_sentences(self, text: str, default_section: str) -> List[_RawSpan]:
        sentences = [s.strip() for s in SENTENCE_SPLIT_PATTERN.split(text) if s.strip()]
        if not sentences:
            return self._chunk_fixed(text, default_section)

        spans: List[_RawSpan] = []
        buffer: List[str] = []
        buffer_len = 0
        cursor = 0

        for sentence in sentences:
            # Si une seule phrase dépasse chunk_size, on la découpe en fixed
            if len(sentence) > self.chunk_size:
                if buffer:
                    joined = " ".join(buffer)
                    start_pos = text.find(joined[:30], cursor)
                    start_pos = start_pos if start_pos >= 0 else cursor
                    spans.append(_RawSpan(joined, default_section, start_pos, start_pos + len(joined)))
                    cursor = start_pos + len(joined)
                    buffer = []
                    buffer_len = 0
                spans.extend(self._chunk_fixed(sentence, default_section))
                continue

            projected = buffer_len + len(sentence) + (1 if buffer else 0)
            if projected > self.chunk_size and buffer:
                joined = " ".join(buffer)
                start_pos = text.find(buffer[0][:30], max(0, cursor - self.chunk_overlap))
                start_pos = start_pos if start_pos >= 0 else cursor
                spans.append(_RawSpan(joined, default_section, start_pos, start_pos + len(joined)))
                cursor = start_pos + len(joined)

                # Conserver un recouvrement de phrases en fin de buffer
                overlap_buf: List[str] = []
                overlap_len = 0
                for prev in reversed(buffer):
                    if overlap_len + len(prev) + 1 <= self.chunk_overlap:
                        overlap_buf.insert(0, prev)
                        overlap_len += len(prev) + 1
                    else:
                        break
                buffer = overlap_buf
                buffer_len = sum(len(s) for s in buffer) + max(0, len(buffer) - 1)

            buffer.append(sentence)
            buffer_len += len(sentence) + (1 if len(buffer) > 1 else 0)

        if buffer:
            joined = " ".join(buffer)
            start_pos = text.find(buffer[0][:30], max(0, cursor - self.chunk_overlap))
            start_pos = start_pos if start_pos >= 0 else cursor
            spans.append(_RawSpan(joined, default_section, start_pos, start_pos + len(joined)))

        return spans

    # ------------------------------------------------------------------
    # Stratégie 3 : Structure-aware (titres + paragraphes FR/AR)
    # ------------------------------------------------------------------
    def _split_into_sections(self, text: str, default_section: str) -> List[Tuple[str, str, int]]:
        """Découpe le texte en blocs (titre_section, contenu, offset_debut)."""
        matches = list(HEADING_PATTERN.finditer(text))
        if not matches:
            return [(default_section, text, 0)]

        sections: List[Tuple[str, str, int]] = []
        # Contenu avant le premier titre
        first_start = matches[0].start()
        if first_start > 0:
            preamble = text[:first_start].strip()
            if preamble:
                sections.append((default_section, preamble, 0))

        for i, match in enumerate(matches):
            heading_raw = match.group(0).strip().lstrip("#").strip()
            block_start = match.start()
            block_end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            block_text = text[block_start:block_end].strip()
            if block_text:
                sections.append((heading_raw, block_text, block_start))
        return sections

    def _chunk_recursive_structure(self, text: str, default_section: str) -> List[_RawSpan]:
        sections = self._split_into_sections(text, default_section)
        spans: List[_RawSpan] = []

        for section_name, section_text, base_offset in sections:
            if len(section_text) <= self.chunk_size:
                spans.append(
                    _RawSpan(
                        text=section_text,
                        section=section_name,
                        char_start=base_offset,
                        char_end=base_offset + len(section_text),
                    )
                )
                continue

            paragraphs = [p.strip() for p in re.split(r"\n{2,}", section_text) if p.strip()]
            current_parts: List[str] = []
            current_len = 0
            local_offset = 0

            for para in paragraphs:
                if len(para) > self.chunk_size:
                    if current_parts:
                        joined = "\n\n".join(current_parts)
                        spans.append(
                            _RawSpan(
                                text=joined,
                                section=section_name,
                                char_start=base_offset + local_offset,
                                char_end=base_offset + local_offset + len(joined),
                            )
                        )
                        local_offset += len(joined)
                        current_parts = []
                        current_len = 0
                    sub_spans = self._chunk_sentences(para, default_section=section_name)
                    for sub in sub_spans:
                        spans.append(
                            _RawSpan(
                                text=sub.text,
                                section=section_name,
                                char_start=base_offset + local_offset + sub.char_start,
                                char_end=base_offset + local_offset + sub.char_end,
                            )
                        )
                    local_offset += len(para)
                    continue

                projected = current_len + len(para) + (2 if current_parts else 0)
                if projected > self.chunk_size and current_parts:
                    joined = "\n\n".join(current_parts)
                    spans.append(
                        _RawSpan(
                            text=joined,
                            section=section_name,
                            char_start=base_offset + local_offset,
                            char_end=base_offset + local_offset + len(joined),
                        )
                    )
                    # Chevauchement basé sur la fin du bloc précédent
                    overlap_tail = joined[-self.chunk_overlap :].strip() if self.chunk_overlap > 0 else ""
                    local_offset += max(0, len(joined) - len(overlap_tail))
                    current_parts = [overlap_tail] if overlap_tail else []
                    current_len = len(overlap_tail)

                current_parts.append(para)
                current_len += len(para) + (2 if len(current_parts) > 1 else 0)

            if current_parts:
                joined = "\n\n".join(current_parts)
                spans.append(
                    _RawSpan(
                        text=joined,
                        section=section_name,
                        char_start=base_offset + local_offset,
                        char_end=base_offset + local_offset + len(joined),
                    )
                )

        return spans
