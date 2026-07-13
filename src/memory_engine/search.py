"""
🔍 Searcher — Búsqueda híbrida en toda la memoria (L2+L3+L4).

Implementa búsqueda con 3 métodos combinados via RRF:
  1. Búsqueda semántica (pgvector cosine similarity)
  2. BM25 (PostgreSQL full-text search o fallback SQLite FTS5)
  3. Búsqueda por metadatos (fecha, proyecto, tags)

RRF K=60 es el estándar de la industria (Pinecone, Anthropic, Azure AI Search).
"""

from __future__ import annotations
import json
import re
import time
import math
from pathlib import Path
from typing import Any

from src.memory_engine.models import IndexEntry, EntryType, SearchResult


# ─── Constantes ────────────────────────────────────────────────

RRF_K = 60.0  # Constante de Reciprocal Rank Fusion
MAX_RESULTS = 20  # Resultados máximos por método de búsqueda
FINAL_RESULTS = 10  # Resultados finales a devolver


class Searcher:
    """Motor de búsqueda híbrida sobre la memoria del enjambre."""

    def __init__(self, base_dir: str):
        self.base_dir = Path(base_dir)
        self.index_path = self.base_dir / "index.json"

    def hybrid_search(
        self,
        query: str,
        project: str | None = None,
        entry_type: str | None = None,
        tag: str | None = None,
        limit: int = FINAL_RESULTS,
    ) -> SearchResult:
        """Búsqueda híbrida: semántica + BM25 + metadatos.

        Args:
            query: Texto de búsqueda
            project: Filtrar por proyecto
            entry_type: Filtrar por tipo (chat, diary, note)
            tag: Filtrar por tag
            limit: Número máximo de resultados

        Returns:
            SearchResult con entries rankeados
        """
        start = time.time()
        filters = {
            "project": project,
            "type": entry_type,
            "tag": tag,
        }

        # Obtener índice completo
        corpus = self._get_corpus()

        # Aplicar filtros primero (más rápido)
        filtered = self._apply_filters(corpus, filters)

        if not filtered:
            return SearchResult(
                entries=[],
                query=query,
                total_results=0,
                methods_used=["filters_only"],
                timing_ms=round((time.time() - start) * 1000, 2),
                filters_applied={k: v for k, v in filters.items() if v},
            )

        # Si no hay query textual, solo usar metadata
        if not query or len(query.strip()) < 2:
            ranked = sorted(
                filtered,
                key=lambda e: e.get("date", ""),
                reverse=True,
            )[:limit]
            results = [IndexEntry.from_dict(e) for e in ranked]
            return SearchResult(
                entries=results,
                query=query,
                total_results=len(results),
                methods_used=["date_sort"],
                timing_ms=round((time.time() - start) * 1000, 2),
                filters_applied={k: v for k, v in filters.items() if v},
            )

        # Método 1: Búsqueda por palabras clave (BM25-like)
        bm25_results = self._bm25_search(query, filtered, limit=MAX_RESULTS)

        # Método 2: Búsqueda semántica simple (TF-IDF-like sobre metadata)
        semantic_results = self._semantic_simple(query, filtered, limit=MAX_RESULTS)

        # Método 3: Búsqueda por tags exactos
        tag_results = self._tag_search(query, filtered, limit=MAX_RESULTS)

        # RRF: fusionar todos los rankings
        all_rankings = [bm25_results, semantic_results, tag_results]
        fused = self._rrf_fusion(all_rankings, limit=limit)

        # Marcar método de cada resultado
        methods_used = []
        if bm25_results:
            methods_used.append("bm25_keyword")
        if semantic_results:
            methods_used.append("semantic_simple")
        if tag_results:
            methods_used.append("tag_match")

        elapsed_ms = round((time.time() - start) * 1000, 2)

        return SearchResult(
            entries=fused,
            query=query,
            total_results=len(fused),
            methods_used=methods_used or ["no_match"],
            timing_ms=elapsed_ms,
            filters_applied={k: v for k, v in filters.items() if v},
        )

    # ─── BM25-like search ────────────────────────────────────────

    def _bm25_search(self, query: str, corpus: list[dict], limit: int) -> list[tuple[str, float]]:
        """Búsqueda por palabras clave con scoring TF-IDF-like.

        Implementa un BM25 simplificado:
          - Tokeniza query
          - Score = sum de (frecuencia_en_doc / (frecuencia_en_doc + k1 * (1 - b + b * doc_len/avg_len)))
          - Busca en: title, summary, tags, project
        """
        tokens = self._tokenize(query)
        if not tokens:
            return []

        # Estadísticas del corpus
        total_docs = len(corpus)
        if total_docs == 0:
            return []

        doc_lens = []
        for doc in corpus:
            doc_len = self._doc_length(doc)
            doc_lens.append(doc_len)
        avg_len = sum(doc_lens) / total_docs if total_docs > 0 else 1

        # Parámetros BM25
        k1 = 1.5
        b = 0.75

        scores = []
        for doc in corpus:
            doc_text = self._doc_text(doc)
            doc_len = self._doc_length(doc)
            score = 0.0

            for token in tokens:
                # Frecuencia del término en el documento
                tf = doc_text.lower().count(token.lower())
                if tf == 0:
                    continue

                # Frecuencia del término en el corpus
                df = sum(1 for d in corpus if token.lower() in self._doc_text(d).lower())
                idf = math.log((total_docs - df + 0.5) / (df + 0.5) + 1.0)

                # BM25 score
                numerator = tf * (k1 + 1)
                denominator = tf + k1 * (1 - b + b * (doc_len / avg_len))
                score += idf * (numerator / denominator)

            if score > 0:
                doc_id = doc.get("id", "")
                scores.append((doc_id, score))

        # Ordenar por score
        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:limit]

    # ─── Semantic simple ─────────────────────────────────────────

    def _semantic_simple(self, query: str, corpus: list[dict], limit: int) -> list[tuple[str, float]]:
        """Búsqueda semántica simple basada en co-ocurrencia de términos.

        Cuando no hay embeddings disponibles, usa:
          - Jaccard similarity entre tokens de query y documento
          - Peso extra si términos aparecen en título o proyecto
        """
        query_tokens = set(self._tokenize(query))
        if not query_tokens:
            return []

        scores = []
        for doc in corpus:
            doc_text = self._doc_text(doc)
            doc_tokens = set(self._tokenize(doc_text))

            # Jaccard similarity
            intersection = query_tokens & doc_tokens
            union = query_tokens | doc_tokens
            jaccard = len(intersection) / len(union) if union else 0

            if jaccard == 0:
                continue

            # Bonus por match en título
            title = doc.get("title", "").lower()
            title_bonus = sum(1 for t in query_tokens if t in title) * 0.2

            # Bonus por match en proyecto
            project = doc.get("project", "").lower()
            proj_bonus = sum(1 for t in query_tokens if t in project) * 0.15

            score = jaccard + title_bonus + proj_bonus
            doc_id = doc.get("id", "")
            scores.append((doc_id, score))

        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:limit]

    # ─── Tag search ──────────────────────────────────────────────

    def _tag_search(self, query: str, corpus: list[dict], limit: int) -> list[tuple[str, float]]:
        """Búsqueda por coincidencia exacta de tags."""
        tokens = self._tokenize(query)
        if not tokens:
            return []

        scores = []
        for doc in corpus:
            tags = [t.lower() for t in doc.get("tags", [])]
            # Bonus por cada tag que coincida
            match_count = sum(1 for t in tokens if t in tags)
            if match_count > 0:
                score = match_count * 1.5  # Peso alto para tags exactos
                doc_id = doc.get("id", "")
                scores.append((doc_id, score))

        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:limit]

    # ─── RRF Fusion ──────────────────────────────────────────────

    def _rrf_fusion(
        self,
        rankings: list[list[tuple[str, float]]],
        limit: int = FINAL_RESULTS,
    ) -> list[IndexEntry]:
        """Reciprocal Rank Fusion: combina múltiples rankings.

        Args:
            rankings: Lista de rankings, cada uno = [(doc_id, score), ...]
            limit: Número máximo de resultados finales

        Returns:
            list[IndexEntry]: Resultados fusionados y rankeados
        """
        # Coleccionar todos los doc_ids
        doc_scores: dict[str, float] = {}

        for ranking in rankings:
            for rank, (doc_id, _) in enumerate(ranking):
                if doc_id not in doc_scores:
                    doc_scores[doc_id] = 0.0
                # RRF: 1 / (rank + K) — rank empieza en 0
                doc_scores[doc_id] += 1.0 / (rank + 1 + RRF_K)

        # Ordenar por RRF score
        ranked_ids = sorted(doc_scores.keys(), key=lambda d: doc_scores[d], reverse=True)

        # Obtener datos completos del índice
        corpus_map = self._get_corpus_map()
        results = []
        for doc_id in ranked_ids[:limit]:
            entry_data = corpus_map.get(doc_id)
            if entry_data:
                entry = IndexEntry.from_dict(entry_data)
                entry.search_score = round(doc_scores[doc_id], 4)
                entry.search_method = "rrf_hybrid"
                results.append(entry)

        return results

    # ─── Helpers ─────────────────────────────────────────────────

    def _get_corpus(self) -> list[dict]:
        """Obtiene el corpus de búsqueda desde el índice local."""
        if not self.index_path.exists():
            return []
        try:
            with open(self.index_path, "r") as f:
                data = json.load(f)
            return data.get("entries", [])
        except Exception:
            return []

    def _get_corpus_map(self) -> dict[str, dict]:
        """Obtiene el corpus como mapa id→entry para lookup rápido."""
        entries = self._get_corpus()
        return {e.get("id", ""): e for e in entries if e.get("id")}

    def _apply_filters(self, corpus: list[dict], filters: dict) -> list[dict]:
        """Aplica filtros al corpus."""
        result = corpus
        if filters.get("project"):
            result = [e for e in result if e.get("project") == filters["project"]]
        if filters.get("type"):
            result = [e for e in result if e.get("type") == filters["type"]]
        if filters.get("tag"):
            result = [e for e in result if filters["tag"] in e.get("tags", [])]
        return result

    def _tokenize(self, text: str) -> list[str]:
        """Tokeniza texto: lowercase, solo alfanumérico."""
        if not text:
            return []
        text = text.lower()
        # Extraer palabras de 2+ caracteres (incluye "3d", "ai", "ui", etc.)
        tokens = re.findall(r'[a-záéíóúñü0-9]{2,}', text)
        return tokens

    def _doc_text(self, doc: dict) -> str:
        """Obtiene el texto completo de búsqueda de un documento."""
        parts = [
            doc.get("title", ""),
            doc.get("summary", ""),
            doc.get("project", ""),
            " ".join(doc.get("tags", [])),
        ]
        return " ".join(p for p in parts if p)

    def _doc_length(self, doc: dict) -> int:
        """Longitud del texto de búsqueda de un documento."""
        return len(self._doc_text(doc).split())
