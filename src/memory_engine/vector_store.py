"""
🗄️ VectorStore — Conexión con Supabase Local (pgvector).

Proporciona inserción y búsqueda semántica usando PostgreSQL + pgvector.
Conecta al Supabase Local en puerto 54322.

Modo dual:
  - LOCAL: postgresql://postgres:postgres@127.0.0.1:54322/postgres
  - CLOUD: URL de Supabase Cloud (cuando se migre)

Auto-detecta el modo según la URL disponible.
"""

from __future__ import annotations
import json
import os
from typing import Any
from urllib.parse import urlparse


# ─── Constantes ────────────────────────────────────────────────

LOCAL_DATABASE_URL = "postgresql://postgres:postgres@127.0.0.1:54322/postgres"
EMBEDDING_DIMS = 384


class VectorStore:
    """Almacén vectorial con pgvector (local o cloud).

    Uso:
        store = VectorStore()
        
        # Insertar
        store.insert(
            task_type="chat_session",
            content="Texto completo...",
            embedding=vector_384d,  # list[float]
            metadata={"chat_id": "CHAT-...", "tags": [...]}
        )
        
        # Buscar
        results = store.search(
            query_embedding=vector_384d,  # list[float]
            query_text="texto búsqueda",
            limit=5
        )
    """

    def __init__(self, database_url: str | None = None):
        self.database_url = database_url or os.getenv(
            "SUPABASE_LOCAL_URL",
            LOCAL_DATABASE_URL,
        )
        self._conn = None
        self._use_direct_pg = True  # True = psycopg2, False = supabase-py

    @property
    def conn(self):
        if self._conn is None:
            import psycopg2
            self._conn = psycopg2.connect(self.database_url)
            self._conn.autocommit = True
        return self._conn

    # ─── Insert ───────────────────────────────────────────────

    def insert(
        self,
        task_type: str,
        content: str,
        embedding: list[float],
        metadata: dict | None = None,
    ) -> str | None:
        """Inserta un registro con embedding en pgvector.

        Args:
            task_type: Tipo de tarea (chat_session, lesson, pattern, etc.)
            content: Contenido textual completo
            embedding: Vector de 384 dimensiones
            metadata: Metadatos adicionales (chat_id, tags, etc.)

        Returns:
            str | None: UUID del registro insertado o None si falla
        """
        try:
            cur = self.conn.cursor()
            cur.execute(
                "SELECT insert_agent_memory(%s, %s, %s::vector, %s)",
                (
                    task_type,
                    content[:10000],  # Limitar a 10k chars para la DB
                    str(embedding),
                    json.dumps(metadata or {}),
                ),
            )
            result = cur.fetchone()
            cur.close()
            return str(result[0]) if result else None
        except Exception as e:
            print(f"  ⚠️ [VectorStore] Error insertando: {e}")
            return None

    # ─── Search ────────────────────────────────────────────────

    def search(
        self,
        query_embedding: list[float],
        query_text: str,
        limit: int = 5,
        threshold: float = 0.0,
    ) -> list[dict]:
        """Búsqueda híbrida: semántica + BM25 + RRF.

        Args:
            query_embedding: Vector de 384d para búsqueda semántica
            query_text: Texto para búsqueda BM25
            limit: Número máximo de resultados
            threshold: Umbral de similitud (0.0 = sin filtro)

        Returns:
            list[dict]: Resultados con id, content, task_type, metadata,
                       similarity, rrf_score
        """
        try:
            cur = self.conn.cursor()
            cur.execute(
                "SELECT id, content, task_type, metadata, similarity, rrf_score "
                "FROM match_agent_memory(%s::vector, %s, %s, %s)",
                (
                    str(query_embedding),
                    query_text,
                    limit,
                    threshold,
                ),
            )
            rows = cur.fetchall()
            cur.close()

            results = []
            for row in rows:
                results.append({
                    "id": str(row[0]),
                    "content": row[1],
                    "task_type": row[2],
                    "metadata": row[3] if isinstance(row[3], dict) else json.loads(row[3] or "{}"),
                    "similarity": float(row[4]) if row[4] else 0.0,
                    "rrf_score": float(row[5]) if row[5] else 0.0,
                })
            return results
        except Exception as e:
            print(f"  ⚠️ [VectorStore] Error buscando: {e}")
            return []

    # ─── Health ────────────────────────────────────────────────

    def health(self) -> dict:
        """Verifica que la DB esté accesible y pgvector activo."""
        try:
            cur = self.conn.cursor()
            cur.execute("SELECT extname, extversion FROM pg_extension WHERE extname = 'vector'")
            vec = cur.fetchone()
            cur.execute("SELECT COUNT(*) FROM agent_memory")
            count = cur.fetchone()[0]
            cur.close()
            return {
                "status": "ok",
                "pgvector": vec[0] if vec else None,
                "version": vec[1] if vec else None,
                "records": count,
                "database_url": self._mask_url(self.database_url),
            }
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def close(self):
        """Cierra la conexión a la DB."""
        if self._conn:
            self._conn.close()
            self._conn = None

    def _mask_url(self, url: str) -> str:
        """Oculta la contraseña en la URL para logging."""
        parsed = urlparse(url)
        if parsed.password:
            return url.replace(parsed.password, "****")
        return url
