"""
📇 Indexer — Índice General Maestro (L4).

Mantiene un índice centralizado de toda la memoria del sistema:
  - Chat sessions (L2)
  - Project diaries (L3)
  - Knowledge notes (L3)
  - Sueltas/tareas sin proyecto

El índice se almacena en:
  1. ~/.agents/memoria/index.json (caché local, siempre disponible)
  2. Supabase pgvector (para búsqueda semántica, cuando disponible)

Puede reconstruirse desde cero escaneando los directorios.
"""

from __future__ import annotations
import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from src.memory_engine.models import (
    IndexEntry, EntryType, now_iso, today_str,
)
from src.memory_engine.naming import (
    parse_chat_id, parse_frontmatter, CHAT_ID_IN_TEXT,
)


class Indexer:
    """Gestiona el índice general maestro (L4)."""

    def __init__(self, base_dir: str):
        self.base_dir = Path(base_dir)
        self.index_path = self.base_dir / "index.json"

    def get_index(self) -> dict:
        """Obtiene el índice general completo."""
        if not self.index_path.exists():
            return {"entries": [], "total_entries": 0, "updated_at": ""}

        try:
            with open(self.index_path, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, Exception):
            return {"entries": [], "total_entries": 0, "updated_at": ""}

    def needs_rebuild(self) -> bool:
        """Verifica si el índice necesita reconstruirse."""
        if not self.index_path.exists():
            return True

        # Verificar si hay archivos más recientes que el índice
        index_mtime = self.index_path.stat().st_mtime
        for directory in [
            self.base_dir / "chats",
            self.base_dir / "sueltas",
            self.base_dir / "proyectos",
        ]:
            if not directory.exists():
                continue
            for fname in os.listdir(str(directory)):
                if fname.endswith(".md") or fname.endswith(".json"):
                    fpath = directory / fname
                    if fpath.stat().st_mtime > index_mtime:
                        return True
        return False

    def rebuild(self) -> dict:
        """Reconstruye el índice general desde cero.

        Escanea todos los directorios de memoria y genera entradas.

        Returns:
            dict con {entries_count, sources_scanned, duration_ms}
        """
        start = time.time()
        entries = []

        # 1. Escanear chats históricos (L2)
        chat_dirs = [
            self.base_dir / "chats",
            self.base_dir / "episodic",
            self.base_dir / "sueltas",
        ]
        for directory in chat_dirs:
            if not directory.exists():
                continue
            for fname in os.listdir(str(directory)):
                if not fname.endswith(".md"):
                    continue
                entry = self._index_chat_file(directory / fname)
                if entry:
                    entries.append(entry.to_dict())

        # 2. Escanear proyectos/diarios (L3)
        proyectos_dir = self.base_dir / "proyectos"
        if proyectos_dir.exists():
            for proj_dir in os.listdir(str(proyectos_dir)):
                proj_path = proyectos_dir / proj_dir
                if proj_path.is_dir():
                    diario_path = proj_path / "diario.md"
                    if diario_path.exists():
                        entry = self._index_diary_file(diario_path, proj_dir)
                        if entry:
                            entries.append(entry.to_dict())

        # 3. Escanear knowledge notes
        knowledge_dir = self.base_dir / "knowledge"
        if knowledge_dir.exists():
            for subdir in ["patrones", "lecciones", "referencias"]:
                sub_path = knowledge_dir / subdir
                if sub_path.exists():
                    for fname in os.listdir(str(sub_path)):
                        if fname.endswith(".md"):
                            fpath = sub_path / fname
                            entry = self._index_knowledge_file(fpath, subdir)
                            if entry:
                                entries.append(entry.to_dict())

        # Guardar índice
        index_data = {
            "entries": entries,
            "total_entries": len(entries),
            "updated_at": now_iso(),
            "sources_scanned": {
                "chats": len([e for e in entries if e.get("type") == "chat"]),
                "diaries": len([e for e in entries if e.get("type") == "diary"]),
                "knowledge": len([e for e in entries if e.get("type") == "note"]),
            },
        }

        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.index_path, "w") as f:
            json.dump(index_data, f, indent=2, ensure_ascii=False)

        elapsed = round((time.time() - start) * 1000, 1)

        return {
            "entries_count": len(entries),
            "sources_scanned": index_data["sources_scanned"],
            "duration_ms": elapsed,
            "file": str(self.index_path),
        }

    def update_entry(self, entry: IndexEntry):
        """Añade o actualiza una entrada en el índice."""
        index = self.get_index()
        entry_dict = entry.to_dict()

        # Buscar y reemplazar
        existing = [i for i, e in enumerate(index["entries"]) if e.get("id") == entry.id]
        if existing:
            index["entries"][existing[0]] = entry_dict
        else:
            index["entries"].append(entry_dict)

        index["total_entries"] = len(index["entries"])
        index["updated_at"] = now_iso()

        with open(self.index_path, "w") as f:
            json.dump(index, f, indent=2, ensure_ascii=False)

    def remove_entry(self, entry_id: str) -> bool:
        """Elimina una entrada del índice."""
        index = self.get_index()
        before = len(index["entries"])
        index["entries"] = [e for e in index["entries"] if e.get("id") != entry_id]
        if len(index["entries"]) == before:
            return False
        index["total_entries"] = len(index["entries"])
        index["updated_at"] = now_iso()
        with open(self.index_path, "w") as f:
            json.dump(index, f, indent=2, ensure_ascii=False)
        return True

    def query(
        self,
        project: str | None = None,
        entry_type: str | None = None,
        tag: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        """Consulta el índice con filtros básicos."""
        index = self.get_index()
        entries = index.get("entries", [])

        if project:
            entries = [e for e in entries if e.get("project") == project]
        if entry_type:
            entries = [e for e in entries if e.get("type") == entry_type]
        if tag:
            entries = [e for e in entries if tag in e.get("tags", [])]

        entries.sort(key=lambda e: e.get("date", ""), reverse=True)
        return entries[:limit]

    # ─── Helpers internos ──────────────────────────────────────

    def _index_chat_file(self, fpath: Path) -> IndexEntry | None:
        """Indexa un archivo de chat."""
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                content = f.read()
            metadata, body = parse_frontmatter(content)
            parsed = parse_chat_id(fpath.name)
            if not parsed:
                return None

            # Detectar enlaces a otros chats
            linked = list(set(CHAT_ID_IN_TEXT.findall(content)))

            return IndexEntry(
                id=parsed["filename"],
                type=EntryType.CHAT,
                title=metadata.get("summary", parsed["topic"]),
                project=parsed["project"],
                date=self._format_date_idx(parsed["date"]),
                tags=metadata.get("tags", []),
                summary=metadata.get("summary", parsed["topic"]),
                token_count=metadata.get("tokens_used", 0),
                status=metadata.get("status", "active"),
                file_path=str(fpath),
                linked_to=linked,
            )
        except Exception:
            return None

    def _index_diary_file(self, fpath: Path, project_name: str) -> IndexEntry | None:
        """Indexa un archivo de diario de proyecto."""
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                content = f.read()
            metadata, body = parse_frontmatter(content)

            # Detectar chats vinculados
            linked = list(set(CHAT_ID_IN_TEXT.findall(content)))

            return IndexEntry(
                id=f"proj-{project_name}",
                type=EntryType.DIARY,
                title=metadata.get("title", project_name),
                project=project_name,
                date=metadata.get("date", today_str()),
                tags=metadata.get("tags", []),
                summary=metadata.get("description", f"Diario del proyecto {project_name}"),
                token_count=len(content) // 4,
                status=metadata.get("status", "active"),
                file_path=str(fpath),
                linked_to=linked,
            )
        except Exception:
            return None

    def _index_knowledge_file(self, fpath: Path, subdir: str) -> IndexEntry | None:
        """Indexa un archivo de conocimiento."""
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                content = f.read()
            metadata, body = parse_frontmatter(content)

            return IndexEntry(
                id=f"note-{fpath.stem}",
                type=EntryType.NOTE,
                title=metadata.get("title", fpath.stem),
                project="knowledge",
                date=metadata.get("date", today_str()),
                tags=metadata.get("tags", []),
                summary=metadata.get("summary", fpath.stem),
                token_count=len(content) // 4,
                status="active",
                file_path=str(fpath),
                linked_to=list(set(CHAT_ID_IN_TEXT.findall(content))),
            )
        except Exception:
            return None

    def _format_date_idx(self, compact: str) -> str:
        """Convierte YYYYMMDD a YYYY-MM-DD o usa la fecha actual."""
        if len(compact) == 8 and compact.isdigit():
            return f"{compact[:4]}-{compact[4:6]}-{compact[6:]}"
        return compact or today_str()
