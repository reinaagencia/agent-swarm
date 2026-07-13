"""
🔀 ProjectManager — Gestión de Proyectos: Merge, Split, Fuse.

Operaciones:
  - MERGE (group): Une proyectos bajo una carpeta macro, manteniéndolos separados
  - FUSE (fuse): Fusiona proyectos en uno solo, reestructurando archivos
  - SPLIT: Divide un proyecto en múltiples sub-proyectos

Basado en patrones de monorepo + workspace isolation + PARA method.
"""

from __future__ import annotations
import json
import os
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from src.memory_engine.models import (
    MergeStrategy, ProjectStatus, now_iso, today_str,
)
from src.memory_engine.naming import (
    parse_frontmatter, build_frontmatter, CHAT_ID_IN_TEXT, generate_chat_id,
)
from src.memory_engine.diary import DiaryManager


class ProjectManager:
    """Gestiona operaciones de merge, split y fuse entre proyectos."""

    def __init__(self, base_dir: str):
        self.base_dir = Path(base_dir)
        self.proyectos_dir = self.base_dir / "proyectos"
        self.chats_dir = self.base_dir / "chats"
        self.index_path = self.base_dir / "index.json"
        self.diary = DiaryManager(base_dir)

    def merge(
        self,
        project_names: list[str],
        strategy: str = "group",
        new_name: str | None = None,
    ) -> dict:
        """Une múltiples proyectos.

        Args:
            project_names: Lista de nombres de proyectos a unir
            strategy: 'group' (carpeta macro) o 'fuse' (fusión real)
            new_name: Nombre del proyecto resultante (opcional)

        Returns:
            dict con {status, strategy, projects, result_path, details}
        """
        if len(project_names) < 2:
            return {"status": "error", "error": "Se necesitan al menos 2 proyectos"}

        # Validar que todos existan
        missing = [p for p in project_names if not (self.proyectos_dir / p / "diario.md").exists()]
        if missing:
            return {"status": "error", "error": f"Proyectos no encontrados: {missing}"}

        name = new_name or self._suggest_merge_name(project_names, strategy)

        if strategy == MergeStrategy.GROUP.value:
            return self._merge_group(project_names, name)
        elif strategy == MergeStrategy.FUSE.value:
            return self._merge_fuse(project_names, name)
        else:
            return {"status": "error", "error": f"Estrategia no válida: {strategy}"}

    def split(self, project_name: str, splits: list[dict]) -> dict:
        """Divide un proyecto en múltiples sub-proyectos.

        Args:
            project_name: Nombre del proyecto a dividir
            splits: Lista de dicts con {name, description, tags, chat_filters}

        Returns:
            dict con {status, original, splits_created, details}
        """
        # Validar que exista
        diary_path = self.proyectos_dir / project_name / "diario.md"
        if not diary_path.exists():
            return {"status": "error", "error": f"Proyecto no encontrado: {project_name}"}

        if len(splits) < 2:
            return {"status": "error", "error": "Se necesitan al menos 2 splits"}

        results = []
        errors = []

        for split_def in splits:
            split_name = split_def.get("name", "")
            if not split_name:
                errors.append("Split sin nombre")
                continue

            try:
                result = self._create_split(project_name, split_def)
                results.append(result)
            except Exception as e:
                errors.append(f"{split_name}: {str(e)}")

        # Actualizar el proyecto original para marcar que tiene sub-proyectos
        self._update_parent_project(project_name, [r["name"] for r in results])

        return {
            "status": "completed" if results else "error",
            "original": project_name,
            "splits_created": [r["name"] for r in results],
            "details": {"results": results, "errors": errors},
        }

    def group_projects(self, project_names: list[str], group_name: str) -> dict:
        """Agrupa proyectos en una carpeta macro (alias para merge group)."""
        return self.merge(project_names, strategy="group", new_name=group_name)

    # ─── Merge: GROUP (carpeta macro) ───────────────────────────

    def _merge_group(self, project_names: list[str], group_name: str) -> dict:
        """Merge strategy 'group': crea carpeta macro.

        Estructura resultante:
        grupo/
        ├── proyecto-A/    ← intacto
        ├── proyecto-B/    ← intacto
        ├── diario.md      ← nuevo diario del grupo
        └── index.md       ← índice de contenidos
        """
        group_dir = self.proyectos_dir / group_name
        if group_dir.exists():
            return {"status": "error", "error": f"Ya existe un proyecto llamado '{group_name}'"}

        group_dir.mkdir(parents=True)

        details = []
        for proj in project_names:
            src = self.proyectos_dir / proj
            dst = group_dir / proj
            shutil.copytree(str(src), str(dst))
            details.append({"project": proj, "copied": str(dst)})

        # Crear diario del grupo
        group_metadata = {
            "title": group_name,
            "tags": [],
            "description": f"Grupo de proyectos: {', '.join(project_names)}",
            "child_projects": project_names,
            "priority": "🟡 MEDIA",
        }
        self.diary.create_project(group_name, group_metadata)

        # Añadir entrada inicial
        self.diary.add_entry(group_name, {
            "date": today_str(),
            "achievements": [f"Agrupación de proyectos: {', '.join(project_names)}"],
            "decisions": [{"tema": "Estructura", "decision": "Carpeta macro — cada proyecto mantiene su independencia"}],
        })

        # Crear índice del grupo
        self._create_group_index(group_dir, project_names, group_name)

        # Actualizar índice general
        self._update_index_for_merge(group_name, project_names, "group")

        return {
            "status": "completed",
            "strategy": "group",
            "name": group_name,
            "projects": project_names,
            "result_path": str(group_dir),
            "details": details,
        }

    # ─── Merge: FUSE (fusión real) ──────────────────────────────

    def _merge_fuse(self, project_names: list[str], fused_name: str) -> dict:
        """Merge strategy 'fuse': fusiona proyectos en uno solo.

        Reestructura:
        - Unifica diarios en un solo timeline cronológico
        - Reorganiza chats por fecha no por proyecto original
        - Combina tags y elimina duplicados
        - Unifica archivos de conocimiento
        """
        fused_dir = self.proyectos_dir / fused_name
        if fused_dir.exists():
            return {"status": "error", "error": f"Ya existe un proyecto llamado '{fused_name}'"}

        fused_dir.mkdir(parents=True)
        details = []

        # 1. Recolectar todos los chats de todos los proyectos
        all_chats = []  # [(chat_id, project_name, date)]
        all_tags = set()
        all_entries = []  # Entradas de diario

        for proj in project_names:
            diary = self.diary.get(proj)
            if diary:
                all_entries.extend(diary.get("entries", []))
                for tag in diary.get("metadata", {}).get("tags", []):
                    all_tags.add(tag)

            # Buscar chats vinculados al proyecto en el índice
            index = self._get_index()
            for entry in index.get("entries", []):
                if entry.get("project") == proj and entry.get("type") == "chat":
                    all_chats.append((
                        entry.get("id", ""),
                        proj,
                        entry.get("date", ""),
                    ))

        # También buscar chats en disco
        if self.chats_dir.exists():
            for fname in os.listdir(str(self.chats_dir)):
                if fname.startswith("CHAT-"):
                    for proj in project_names:
                        if proj.replace("-", "") in fname:
                            all_chats.append((fname, proj, fname[5:13]))
                            break

        # 2. Reorganizar: copiar diarios combinados
        fused_metadata = {
            "title": fused_name,
            "tags": list(all_tags),
            "description": f"Fusión de proyectos: {', '.join(project_names)}",
            "child_projects": [],
            "priority": "🟡 ALTA",
            "fused_from": project_names,
        }
        self.diary.create_project(fused_name, fused_metadata)

        # 3. Añadir entradas cronológicas
        all_entries.sort(key=lambda e: e.get("date", ""))
        for entry in all_entries:
            entry["chat_id"] = entry.get("chat_id", "")
            self.diary.add_entry(fused_name, entry)

        # 4. Re-ligar chats al proyecto fusionado
        unique_chats = list(set(c[0] for c in all_chats))
        for chat_id in unique_chats:
            self._relink_chat(chat_id, fused_name)

        # 5. Actualizar índice
        self._update_index_for_merge(fused_name, project_names, "fuse")

        details.append({
            "chats_relinked": len(unique_chats),
            "diary_entries_merged": len(all_entries),
            "tags_combined": list(all_tags),
            "original_projects": project_names,
        })

        return {
            "status": "completed",
            "strategy": "fuse",
            "name": fused_name,
            "projects": project_names,
            "result_path": str(fused_dir),
            "details": details,
        }

    # ─── Split ─────────────────────────────────────────────────

    def _create_split(self, parent_project: str, split_def: dict) -> dict:
        """Crea un sub-proyecto a partir de un split."""
        split_name = split_def["name"]
        description = split_def.get("description", "")
        tags = split_def.get("tags", [])
        chat_filter = split_def.get("chat_filter", "")

        # Crear el proyecto
        metadata = {
            "title": split_name,
            "tags": tags,
            "description": description,
            "priority": "🟡 MEDIA",
            "parent": parent_project,
        }
        self.diary.create_project(split_name, metadata)

        # Buscar chats del proyecto padre que match con el filtro
        if chat_filter and self.chats_dir.exists():
            for fname in os.listdir(str(self.chats_dir)):
                if chat_filter.lower() in fname.lower():
                    self._relink_chat(fname, split_name)

        # Registrar en el diario del split
        self.diary.add_entry(split_name, {
            "date": today_str(),
            "achievements": [f"Split creado desde {parent_project}"],
            "decisions": [{"tema": "Origen", "decision": f"Separado de {parent_project}"}],
        })

        return {"name": split_name, "description": description, "status": "created"}

    def _update_parent_project(self, project: str, children: list[str]):
        """Actualiza el proyecto padre con sus hijos."""
        diary_path = self.proyectos_dir / project / "diario.md"
        if not diary_path.exists():
            return

        try:
            with open(diary_path, "r", encoding="utf-8") as f:
                content = f.read()
            metadata, body = parse_frontmatter(content)
            metadata["child_projects"] = list(set(metadata.get("child_projects", []) + children))
            metadata["status"] = "active"

            new_fm = build_frontmatter(metadata)
            with open(diary_path, "w", encoding="utf-8") as f:
                f.write(new_fm + body)
        except Exception:
            pass

    # ─── Helpers ───────────────────────────────────────────────

    def _suggest_merge_name(self, projects: list[str], strategy: str) -> str:
        """Sugiere un nombre para el proyecto fusionado."""
        if strategy == "group":
            return f"grupo-{projects[0]}" if len(projects) < 4 else f"grupo-{projects[0]}-y-otros"
        else:
            return f"fusion-{projects[0]}-{projects[-1]}"

    def _create_group_index(self, group_dir: Path, projects: list[str], group_name: str):
        """Crea un archivo de índice para el grupo."""
        index_content = f"""# 📚 Índice del Grupo: {group_name}

Este grupo contiene los siguientes proyectos independientes:

"""
        for proj in projects:
            diary = self.diary.get(proj)
            entry_count = len(diary.get("entries", [])) if diary else 0
            index_content += f"""
## {proj}
- **Entradas de diario**: {entry_count}
- **Ruta**: `proyectos/{group_name}/{proj}/`
"""
        index_path = group_dir / "INDEX.md"
        with open(index_path, "w", encoding="utf-8") as f:
            f.write(index_content)

    def _relink_chat(self, chat_id: str, new_project: str):
        """Actualiza el proyecto de un chat en el índice."""
        index = self._get_index()
        updated = False
        for entry in index.get("entries", []):
            if entry.get("id") == chat_id:
                entry["project"] = new_project
                updated = True
                break
        if updated:
            with open(self.index_path, "w") as f:
                json.dump(index, f, indent=2, ensure_ascii=False)

    def _update_index_for_merge(
        self,
        new_name: str,
        source_projects: list[str],
        strategy: str,
    ):
        """Actualiza el índice tras un merge."""
        index = self._get_index()

        # Añadir entrada para el nuevo proyecto
        index["entries"].append({
            "id": f"proj-{new_name}",
            "type": "project",
            "title": new_name,
            "project": new_name,
            "date": today_str(),
            "tags": [],
            "summary": f"{'Grupo' if strategy == 'group' else 'Fusión'} de: {', '.join(source_projects)}",
            "token_count": 0,
            "status": "active",
            "file_path": str(self.proyectos_dir / new_name / "diario.md"),
            "linked_to": [f"proj-{p}" for p in source_projects],
        })

        index["total_entries"] = len(index["entries"])
        index["updated_at"] = now_iso()

        with open(self.index_path, "w") as f:
            json.dump(index, f, indent=2, ensure_ascii=False)

    def _get_index(self) -> dict:
        """Obtiene el índice general."""
        if self.index_path.exists():
            try:
                with open(self.index_path, "r") as f:
                    return json.load(f)
            except Exception:
                pass
        return {"entries": [], "total_entries": 0, "updated_at": ""}
