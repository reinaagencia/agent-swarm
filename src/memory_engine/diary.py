"""
📓 DiaryManager — Gestión de Diarios de Proyecto (L3).

Cada proyecto tiene un diario en ~/.agents/memoria/proyectos/{project}/diario.md
que documenta el avance, decisiones, lecciones y tareas.

El diario referencia chats por su ID (CHAT-{fecha}-{proyecto}-{tema}-v{N}.md)
pero no duplica el contenido — solo guarda resúmenes ejecutivos.
"""

from __future__ import annotations
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from src.memory_engine.models import (
    ProjectDiary, ProjectStatus, now_iso, today_str,
)
from src.memory_engine.naming import (
    parse_frontmatter, build_frontmatter, CHAT_ID_IN_TEXT,
)


# Template para nuevo diario
DIARY_TEMPLATE = """# 📓 Diario: {project_name}

## Metadatos
- estado: active
- prioridad: 🟡 MEDIA
- tags: [{tags_str}]

---

## Línea de Tiempo

<!-- Las entradas se añaden automáticamente con: add_entry() -->
"""


class DiaryManager:
    """Gestiona los diarios de proyecto."""

    def __init__(self, base_dir: str):
        self.base_dir = Path(base_dir)
        self.proyectos_dir = self.base_dir / "proyectos"

    def get(self, project: str) -> dict | None:
        """Obtiene el diario completo de un proyecto.

        Returns:
            dict con {metadata, entries} o None si no existe
        """
        path = self._diary_path(project)
        if not path.exists():
            return None

        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()

            metadata, body = parse_frontmatter(content)

            # Parsear entradas de la línea de tiempo
            entries = self._parse_entries(body)

            return {
                "project": project,
                "metadata": metadata,
                "entries": entries,
                "file_path": str(path),
            }
        except Exception as e:
            return {"project": project, "error": str(e)}

    def add_entry(self, project: str, entry: dict) -> dict:
        """Añade una entrada al diario de un proyecto.

        Args:
            project: Nombre del proyecto
            entry: Dict con {date, chat_id, achievements, decisions, lessons, pending}

        Returns:
            dict con {status, project, entry_count}
        """
        path = self._diary_path(project)

        # Crear diario si no existe
        if not path.exists():
            self._create_diary(project)

        # Leer diario actual
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()

        metadata, body = parse_frontmatter(content)

        # Formatear nueva entrada
        date = entry.get("date", today_str())
        chat_id = entry.get("chat_id", "")
        achievements = entry.get("achievements", [])
        decisions = entry.get("decisions", [])
        lessons = entry.get("lessons", [])
        pending = entry.get("pending", [])

        entry_lines = [f"\n### {date}"]
        if chat_id:
            entry_lines.append(f"- **Chat**: {chat_id}")
        if achievements:
            entry_lines.append(f"- **Logros**:")
            for a in achievements:
                entry_lines.append(f"  - [x] {a}")
        if decisions:
            entry_lines.append(f"- **Decisiones**:")
            for d in decisions:
                entry_lines.append(f"  - **{d.get('tema', '')}**: {d.get('decision', '')}")
        if lessons:
            entry_lines.append(f"- **Lecciones**:")
            for l in lessons:
                entry_lines.append(f"  - {l}")
        if pending:
            entry_lines.append(f"- **Pendientes**:")
            for p in pending:
                entry_lines.append(f"  - [ ] {p}")

        entry_text = "\n".join(entry_lines)

        # Insertar antes del último '<!--' si existe
        insert_pos = content.rfind("<!--")
        if insert_pos != -1:
            new_content = content[:insert_pos] + entry_text + "\n\n" + content[insert_pos:]
        else:
            new_content = content + "\n" + entry_text

        with open(path, "w", encoding="utf-8") as f:
            f.write(new_content)

        # Actualizar linked_chats en frontmatter
        if chat_id:
            self._link_chat_to_project(project, chat_id)

        return {
            "status": "entry_added",
            "project": project,
            "date": date,
            "entry_count": len(self._parse_entries(new_content)),
        }

    def list_projects(self) -> list[dict]:
        """Lista todos los proyectos con sus metadatos."""
        if not self.proyectos_dir.exists():
            return []

        projects = []
        for proj_name in sorted(os.listdir(str(self.proyectos_dir))):
            proj_path = self.proyectos_dir / proj_name
            if not proj_path.is_dir():
                continue

            diary_path = proj_path / "diario.md"
            if not diary_path.exists():
                continue

            try:
                with open(diary_path, "r", encoding="utf-8") as f:
                    content = f.read()
                metadata, _ = parse_frontmatter(content)
                entries = self._parse_entries(content)

                projects.append({
                    "project": proj_name,
                    "title": metadata.get("title", proj_name),
                    "status": metadata.get("status", "active"),
                    "priority": metadata.get("priority", "🟡 MEDIA"),
                    "tags": metadata.get("tags", []),
                    "entry_count": len(entries),
                    "last_entry": entries[-1].get("date", "") if entries else "",
                    "file_path": str(diary_path),
                })
            except Exception:
                continue

        projects.sort(key=lambda p: p.get("last_entry", ""), reverse=True)
        return projects

    def create_project(self, project: str, metadata: dict | None = None) -> dict:
        """Crea un nuevo proyecto con su diario."""
        path = self._diary_path(project)
        if path.exists():
            return {"status": "already_exists", "project": project, "file_path": str(path)}

        self._create_diary(project, metadata)
        return {"status": "created", "project": project, "file_path": str(path)}

    def archive_project(self, project: str) -> dict:
        """Archiva un proyecto (cambia estado a archived)."""
        path = self._diary_path(project)
        if not path.exists():
            return {"status": "not_found", "project": project}

        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()

            # Actualizar frontmatter
            metadata, body = parse_frontmatter(content)
            metadata["status"] = "archived"
            new_fm = build_frontmatter(metadata)
            new_content = new_fm + body

            with open(path, "w", encoding="utf-8") as f:
                f.write(new_content)

            return {"status": "archived", "project": project}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    # ─── Helpers internos ──────────────────────────────────────

    def _diary_path(self, project: str) -> Path:
        """Ruta al archivo de diario de un proyecto."""
        return self.proyectos_dir / project / "diario.md"

    def _create_diary(self, project: str, metadata: dict | None = None):
        """Crea un nuevo archivo de diario."""
        path = self.proyectos_dir / project
        path.mkdir(parents=True, exist_ok=True)

        meta = metadata or {}
        tags_str = ", ".join(meta.get("tags", []))

        # Frontmatter
        fm_data = {
            "title": meta.get("title", project),
            "project": project,
            "status": "active",
            "priority": meta.get("priority", "🟡 MEDIA"),
            "tags": meta.get("tags", []),
            "description": meta.get("description", f"Proyecto: {project}"),
            "created_at": now_iso(),
            "updated_at": now_iso(),
            "linked_chats": [],
            "child_projects": [],
        }

        fm = build_frontmatter(fm_data)
        content = fm + f"\n# 📓 Diario: {meta.get('title', project)}\n\n"

        diary_file = path / "diario.md"
        with open(diary_file, "w", encoding="utf-8") as f:
            f.write(content)

    def _link_chat_to_project(self, project: str, chat_id: str):
        """Añade un chat_id a linked_chats del proyecto."""
        path = self._diary_path(project)
        if not path.exists():
            return

        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()

            metadata, body = parse_frontmatter(content)
            linked = list(set(metadata.get("linked_chats", []) + [chat_id]))
            metadata["linked_chats"] = linked

            new_fm = build_frontmatter(metadata)
            with open(path, "w", encoding="utf-8") as f:
                f.write(new_fm + body)
        except Exception:
            pass

    def _parse_entries(self, content: str) -> list[dict]:
        """Parsea las entradas de la línea de tiempo."""
        entries = []
        current_date = ""
        current_entry = None

        for line in content.split("\n"):
            line_stripped = line.strip()

            # Detectar fecha: ### YYYY-MM-DD
            if line_stripped.startswith("### ") and "-" in line_stripped[4:]:
                if current_entry and current_entry.get("achievements"):
                    entries.append(current_entry)
                date_part = line_stripped[4:].split(" ")[0]
                current_date = date_part
                current_entry = {
                    "date": current_date,
                    "chat_id": "",
                    "achievements": [],
                    "decisions": [],
                    "lessons": [],
                    "pending": [],
                }
                continue

            if current_entry is None:
                continue

            # Chat link
            if line_stripped.startswith("- **Chat**:"):
                current_entry["chat_id"] = line_stripped.split(":", 1)[1].strip()
            # Achievements
            elif "- [x]" in line_stripped or "✅" in line_stripped:
                current_entry["achievements"].append(self._clean_bullet(line_stripped))
            # Pending
            elif "- [ ]" in line_stripped:
                current_entry["pending"].append(self._clean_bullet(line_stripped))
            # Lecciones
            elif line_stripped.startswith("- **Lecciones**"):
                continue
            elif line_stripped.startswith("- ") and current_entry["lessons"]:
                current_entry["lessons"][-1] += " " + line_stripped[2:]
            elif current_entry["lessons"] and not line_stripped.startswith("-"):
                current_entry["lessons"][-1] += " " + line_stripped

        # Última entrada
        if current_entry and current_entry.get("achievements"):
            entries.append(current_entry)

        return entries

    def _clean_bullet(self, line: str) -> str:
        """Limpia un bullet point de marcadores markdown."""
        line = line.strip()
        for prefix in ["- [x]", "- [ ]", "✅", "-"]:
            if line.startswith(prefix):
                line = line[len(prefix):].strip()
        return line
