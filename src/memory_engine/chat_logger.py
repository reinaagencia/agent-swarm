"""
💾 ChatLogger — Guardado e indexación de conversaciones.

L1/L2: Recibe el contenido completo de una conversación y:
  1. Genera/valida el frontmatter YAML
  2. Crea el índice de chunks semánticos
  3. Guarda el archivo completo en ~/.agents/memoria/chats/
  4. Actualiza el índice general (L4)
  5. Actualiza el diario del proyecto correspondiente (L3)
"""

from __future__ import annotations
import json
import os
import re
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from src.memory_engine.models import (
    ChatSession, ChatChunk, ChatStatus, now_iso, today_str, today_compact,
)
from src.memory_engine.naming import (
    generate_chat_id, parse_chat_id, build_frontmatter, parse_frontmatter,
    chat_file_exists, resolve_chat_path, CHAT_ID_IN_TEXT,
)
from src.memory_engine.chunker import Chunker


class ChatLogger:
    """Gestiona el guardado, recuperación e indexación de chats."""

    def __init__(self, base_dir: str):
        self.base_dir = Path(base_dir)
        self.chats_dir = self.base_dir / "chats"
        self.episodic_dir = self.base_dir / "episodic"
        self.sueltas_dir = self.base_dir / "sueltas"
        self.chunker = Chunker()

        # Asegurar directorios
        for d in [self.chats_dir, self.episodic_dir, self.sueltas_dir]:
            d.mkdir(parents=True, exist_ok=True)

    def save(
        self,
        chat_id: str,
        content: str,
        metadata: dict | None = None,
        target_dir: str | None = None,
    ) -> dict:
        """Guarda una conversación completa con su índice.

        Args:
            chat_id: ID del chat (CHAT-{date}-{project}-{topic}-v{N}.md)
            content: Contenido completo de la conversación
            metadata: Metadatos adicionales (tags, decisiones, etc.)
            target_dir: 'chats', 'episodic', o 'sueltas' (auto-detecta)

        Returns:
            dict con {chat_id, file_path, chunks_count, token_count, status}
        """
        # Validar/parsear el ID
        parsed = parse_chat_id(chat_id)
        if not parsed:
            # Intentar generar uno desde metadata
            if metadata:
                chat_id = generate_chat_id(
                    project=metadata.get("project", "general"),
                    topic=metadata.get("topic", "sesion"),
                )
                parsed = parse_chat_id(chat_id)
            else:
                raise ValueError(f"ID de chat inválido: {chat_id}")

        # Determinar directorio destino
        if target_dir:
            dest_dir = self.base_dir / target_dir
        else:
            project = parsed["project"]
            if project in ("general", "suelta", "consulta"):
                dest_dir = self.sueltas_dir
            else:
                dest_dir = self.chats_dir

        dest_dir.mkdir(parents=True, exist_ok=True)
        file_path = dest_dir / chat_id

        # Generar chunks
        chunks = self.chunker.chunk_conversation(content, chat_id)

        # Construir metadata completa
        fm = self._build_metadata(parsed, metadata, chunks, content)

        # Construir frontmatter
        frontmatter = build_frontmatter(fm)

        # Construir el índice de chunks (para incluir en el archivo)
        index_section = self._build_index_section(chunks, chat_id)

        # Contenido final = frontmatter + índice + conversación completa
        final_content = frontmatter + index_section + "\n\n---\n\n" + content

        # Guardar archivo
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(final_content)

        # Actualizar el índice general (L4)
        self._update_general_index({
            "id": chat_id,
            "type": "chat",
            "title": fm.get("summary", parsed["project"]),
            "project": parsed["project"],
            "date": parsed["date"],
            "tags": fm.get("tags", []),
            "summary": fm.get("summary", ""),
            "token_count": fm.get("tokens_used", 0),
            "status": "active",
            "file_path": str(file_path),
            "linked_to": fm.get("linked_chats", []),
        })

        # ── Vector Store: embedding + pgvector ──
        vector_result = self._vectorize(chat_id, content, chunks, fm, parsed)

        return {
            "chat_id": chat_id,
            "file_path": str(file_path),
            "chunks_count": len(chunks),
            "token_count": fm.get("tokens_used", 0),
            "status": "saved",
            "project": parsed["project"],
        }

    def get(self, chat_id: str) -> str | None:
        """Recupera el contenido completo de un chat."""
        path = resolve_chat_path(chat_id, str(self.base_dir))
        if not path:
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            # Devolver solo el contenido (sin frontmatter ni índice)
            metadata, body = parse_frontmatter(content)
            # Quitar sección de índice si existe
            body = self._strip_index_section(body)
            return {"metadata": metadata, "content": body}
        except Exception:
            return None

    def get_index(self, chat_id: str) -> dict | None:
        """Obtiene solo el índice (frontmatter + chunks) sin contenido completo."""
        path = resolve_chat_path(chat_id, str(self.base_dir))
        if not path:
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            metadata, body = parse_frontmatter(content)
            chunks_section = self._extract_index_section(body)
            return {
                "metadata": metadata,
                "chunks": chunks_section,
                "has_full_content": True,
            }
        except Exception:
            return None

    def list_chats(self, project: str | None = None) -> list[dict]:
        """Lista todos los chats, opcionalmente filtrados por proyecto.

        Returns:
            list[dict]: [{chat_id, project, date, topic, version, summary, tags, status}]
        """
        chats = []
        for directory in [self.chats_dir, self.sueltas_dir]:
            if not directory.exists():
                continue
            for fname in os.listdir(str(directory)):
                if not fname.startswith("CHAT-") or not fname.endswith(".md"):
                    continue
                parsed = parse_chat_id(fname)
                if not parsed:
                    continue
                if project and parsed["project"] != project:
                    continue

                # Leer metadatos del frontmatter
                fpath = directory / fname
                try:
                    with open(fpath, "r", encoding="utf-8") as f:
                        meta, _ = parse_frontmatter(f.read())
                except Exception:
                    meta = {}

                chats.append({
                    "chat_id": fname,
                    "project": parsed["project"],
                    "date": parsed["date"],
                    "topic": parsed["topic"],
                    "version": parsed["version"],
                    "summary": meta.get("summary", ""),
                    "tags": meta.get("tags", []),
                    "status": meta.get("status", "active"),
                    "file_path": str(fpath),
                    "file_size": fpath.stat().st_size if fpath.exists() else 0,
                })

        # Ordenar por fecha descendente
        chats.sort(key=lambda c: c["date"], reverse=True)
        return chats

    def consolidate_episodic(self) -> int:
        """Consolida sesiones episódicas antiguas a L2 (chats históricos).

        Mueve archivos de episodic/ a chats/ si tienen más de 24h.
        """
        count = 0
        cutoff = time.time() - 86400  # 24h
        if not self.episodic_dir.exists():
            return 0

        for fname in os.listdir(str(self.episodic_dir)):
            fpath = self.episodic_dir / fname
            if fpath.stat().st_mtime < cutoff:
                dest = self.chats_dir / fname
                shutil.move(str(fpath), str(dest))
                count += 1

        return count

    # ─── Helpers internos ──────────────────────────────────────

    def _build_metadata(
        self,
        parsed: dict,
        extra: dict | None,
        chunks: list[ChatChunk],
        content: str,
    ) -> dict:
        """Construye el diccionario de metadatos completo."""
        extra = extra or {}

        # Detectar participantes
        participants = extra.get("participants", ["user", "agent"])
        tools = extra.get("tools_used", [])

        # Detectar decisiones del contenido (si no vienen en extra)
        decisions = extra.get("decisions", [])
        pending = extra.get("pending_tasks", [])

        # Detectar chats vinculados en el contenido
        linked = list(set(CHAT_ID_IN_TEXT.findall(content)))

        # Construir metadata
        fm = {
            "session_id": parsed["filename"],
            "type": "session",
            "date": self._format_date(parsed["date"]),
            "project": parsed["project"],
            "topic": parsed["topic"],
            "version": parsed["version"],
            "status": "active",
            "tags": extra.get("tags", []),
            "model": extra.get("model", ""),
            "tokens_used": extra.get("tokens_used", len(content) // 4),
            "duration_seconds": extra.get("duration_seconds", 0),
            "summary": extra.get("summary", self._auto_summary(content)),
            "participants": participants,
            "tools_used": tools,
            "decisions": decisions,
            "pending_tasks": pending,
            "linked_chats": linked,
            "chunks": [c.to_dict() for c in chunks],
            "created_at": now_iso(),
            "updated_at": now_iso(),
        }

        return fm

    def _build_index_section(self, chunks: list[ChatChunk], chat_id: str) -> str:
        """Construye la sección de índice que se incluye en el archivo."""
        if not chunks:
            return ""

        lines = ["", "## 📇 Índice de la Conversación", ""]
        for c in chunks:
            lines.append(
                f"| {c.index:03d} | {c.title[:50]:<50} | "
                f"Turnos {c.turn_start}-{c.turn_end} | "
                f"{c.token_count} tok |"
            )

        # Añadir tabla de contenidos detallada
        lines.insert(1, "| # | Tema | Turnos | Tokens |")
        lines.insert(2, "|---|------|--------|--------|")

        lines.append("")
        return "\n".join(lines)

    def _strip_index_section(self, body: str) -> str:
        """Elimina la sección de índice del cuerpo."""
        # Buscar "## 📇 Índice" y eliminar hasta el siguiente "---"
        idx = body.find("## 📇 Índice")
        if idx != -1:
            end = body.find("---", idx)
            if end != -1:
                body = body[:idx] + body[end + 3:]
        return body.strip()

    def _extract_index_section(self, body: str) -> list[dict]:
        """Extrae la tabla de chunks del cuerpo."""
        chunks = []
        lines = body.split("\n")
        in_index = False
        for line in lines:
            if "📇 Índice" in line:
                in_index = True
                continue
            if in_index:
                if line.startswith("---"):
                    break
                match = re.match(r"\|\s*(\d+)\s*\|\s*(.*?)\s*\|\s*Turnos\s*(\d+)-(\d+)", line)
                if match:
                    chunks.append({
                        "index": int(match.group(1)),
                        "title": match.group(2).strip(),
                        "turn_start": int(match.group(3)),
                        "turn_end": int(match.group(4)),
                    })
        return chunks

    def _auto_summary(self, content: str) -> str:
        """Genera un resumen automático de 1 línea del contenido."""
        # Tomar primeras líneas no vacías
        lines = [l.strip() for l in content.split("\n") if l.strip()]
        for line in lines[:5]:
            clean = re.sub(r'[*_#`>]', '', line).strip()
            if len(clean) > 30:
                return clean[:150]
        return "Conversación"

    def _format_date(self, compact: str) -> str:
        """Convierte YYYYMMDD a YYYY-MM-DD."""
        if len(compact) == 8 and compact.isdigit():
            return f"{compact[:4]}-{compact[4:6]}-{compact[6:]}"
        return compact

    def _vectorize(self, chat_id: str, content: str, chunks: list, fm: dict, parsed: dict) -> dict:
        """Genera embedding + guarda en pgvector.

        Cada chunk del chat se vectoriza y almacena para búsqueda semántica.
        El contenido completo se vectoriza como entrada principal.
        """
        result = {"status": "skipped", "chunks_indexed": 0}
        try:
            from src.memory_engine.embedding_service import EmbeddingService
            from src.memory_engine.vector_store import VectorStore

            emb = EmbeddingService()
            store = VectorStore()

            # 1. Insertar el contenido completo como registro principal
            task_type = f"chat_{parsed['project']}"
            full_text = content[:10000]  # Limitar a 10k chars

            # Generar embedding del contenido principal
            vector = emb.embed(full_text)
            metadata = {
                "chat_id": chat_id,
                "project": parsed["project"],
                "topic": parsed["topic"],
                "tags": fm.get("tags", []),
                "version": parsed["version"],
                "type": "full_chat",
            }
            uid = store.insert(task_type, full_text, vector, metadata)

            # 2. Insertar chunks individuales para búsqueda granular
            indexed = 1 if uid else 0
            if chunks:
                for chunk in chunks:
                    chunk_text = ""
                    if hasattr(chunk, 'summary') and chunk.summary:
                        chunk_text = chunk.summary
                    elif isinstance(chunk, dict):
                        chunk_text = chunk.get("summary", str(chunk))
                    else:
                        chunk_text = str(chunk)
                    if len(chunk_text) < 20:
                        continue
                    chunk_vec = emb.embed(chunk_text)
                    c_idx = chunk.index if hasattr(chunk, 'index') else (chunk.get("index", 0) if isinstance(chunk, dict) else 0)
                    c_tstart = chunk.turn_start if hasattr(chunk, 'turn_start') else (chunk.get("turn_start", '?') if isinstance(chunk, dict) else '?')
                    c_tend = chunk.turn_end if hasattr(chunk, 'turn_end') else (chunk.get("turn_end", '?') if isinstance(chunk, dict) else '?')
                    chunk_meta = {
                        "chat_id": chat_id,
                        "project": parsed["project"],
                        "topic": parsed["topic"],
                        "chunk_index": c_idx,
                        "turn_range": f"{c_tstart}-{c_tend}",
                        "tags": fm.get("tags", []),
                        "type": "chat_chunk",
                    }
                    cid = store.insert(f"chunk_{parsed['project']}", chunk_text, chunk_vec, chunk_meta)
                    if cid:
                        indexed += 1

            store.close()
            result = {"status": "ok", "chunks_indexed": indexed}
        except ImportError as e:
            result = {"status": "unavailable", "error": str(e)}
        except Exception as e:
            result = {"status": "error", "error": str(e)}

        if result["status"] != "ok":
            print(f"  ⚠️ [VectorStore] {result.get('error', 'unknown')}")

        return result

    def _update_general_index(self, entry: dict):
        """Actualiza el índice general maestro (L4)."""
        index_path = self.base_dir / "index.json"
        index_data = {"entries": [], "updated_at": now_iso()}

        if index_path.exists():
            try:
                with open(index_path, "r") as f:
                    index_data = json.load(f)
            except (json.JSONDecodeError, Exception):
                pass

        # Actualizar o añadir entrada
        existing = [i for i in index_data["entries"] if i.get("id") == entry["id"]]
        if existing:
            existing[0].update(entry)
        else:
            index_data["entries"].append(entry)

        index_data["updated_at"] = now_iso()
        index_data["total_entries"] = len(index_data["entries"])

        with open(index_path, "w") as f:
            json.dump(index_data, f, indent=2, ensure_ascii=False)
