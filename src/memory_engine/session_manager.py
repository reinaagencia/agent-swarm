"""
🎯 SessionManager — Conector agente ↔ Memory Engine.

Punto de integración entre el flujo del agente (Smith/pipeline) y el
sistema de memoria multi-capa. Se encarga de:

  1. Auto-guardar conversaciones al finalizar cada ejecución del pipeline
  2. Crear/actualizar diarios de proyecto automáticamente
  3. Mantener el índice general actualizado
  4. Proveer una API simple para que Smith guarde contexto

Uso desde main.py:
    from src.memory_engine.session_manager import SessionManager
    session = SessionManager(project="agent-swarm")
    session.save_pipeline_run(requirement, final_state, start_time)

Uso desde el agente (Smith):
    session.begin(project="enjambre-engine", topic="dashboard")
    # ... trabajar ...
    session.end(achievements=["...", "..."], pending=["..."])
"""

from __future__ import annotations
import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from src.memory_engine.models import today_compact, today_str, now_iso
from src.memory_engine.naming import generate_chat_id, parse_chat_id
from src.memory_engine.chat_logger import ChatLogger
from src.memory_engine.indexer import Indexer
from src.memory_engine.diary import DiaryManager
from src.memory_engine.search import Searcher
from src.memory_engine.chunker import Chunker


class SessionManager:
    """Manejador de sesión que conecta al agente con el Memory Engine.

    Tracks el proyecto y tema actual, y auto-guarda al finalizar.
    """

    def __init__(self, base_dir: str | None = None):
        _base = base_dir or os.path.expanduser("~/.agents/memoria")
        self.chat_logger = ChatLogger(_base)
        self.indexer = Indexer(_base)
        self.diary = DiaryManager(_base)
        self.searcher = Searcher(_base)
        self.chunker = Chunker()
        self.current_project: str = ""
        self.current_topic: str = ""
        self.current_chat_id: str = ""
        self.conversation_buffer: list[str] = []
        self.start_time: float = 0.0
        self.tags: list[str] = []
        self.tools_used: list[str] = []
        self.decisions: list[str] = []
        self.pending_tasks: list[str] = []
        self.participants: list[str] = ["user", "smith"]

    # ─── Gestión de sesión ──────────────────────────────────────

    def begin(
        self,
        project: str,
        topic: str = "sesion",
        tags: list[str] | None = None,
        participants: list[str] | None = None,
    ) -> str:
        """Inicia una nueva sesión.

        Args:
            project: Nombre del proyecto
            topic: Tema de la sesión
            tags: Tags para clasificación
            participants: Participantes de la conversación

        Returns:
            str: chat_id generado
        """
        self.current_project = project
        self.current_topic = topic
        self.tags = tags or []
        self.participants = participants or ["user", "smith"]
        self.conversation_buffer = []
        self.start_time = time.time()
        self.decisions = []
        self.pending_tasks = []
        self.tools_used = []

        self.current_chat_id = generate_chat_id(project, topic)
        return self.current_chat_id

    def add_turn(self, speaker: str, message: str):
        """Añade un turno de conversación al buffer.

        Args:
            speaker: "user" o "smith" (o "agent")
            message: Contenido del mensaje
        """
        label = "Smith" if speaker.lower() in ("smith", "agent") else "Usuario"
        formatted = f"**{label}**: {message}"
        self.conversation_buffer.append(formatted)

    def add_decision(self, decision: str):
        """Registra una decisión tomada durante la sesión."""
        self.decisions.append(decision)

    def add_pending(self, task: str):
        """Registra una tarea pendiente."""
        self.pending_tasks.append(task)

    def add_tool(self, tool: str):
        """Registra una herramienta usada."""
        if tool not in self.tools_used:
            self.tools_used.append(tool)

    def end(
        self,
        achievements: list[str] | None = None,
        pending: list[str] | None = None,
        decisions: list[str] | None = None,
        lessons: list[str] | None = None,
        summary: str | None = None,
    ) -> dict:
        """Finaliza la sesión: guarda chat + actualiza diario + índice.

        Returns:
            dict con {chat_saved, diary_updated, index_rebuilt, duration}
        """
        if not self.conversation_buffer:
            return {"status": "empty_session", "chat_id": self.current_chat_id}

        # Generar contenido completo
        content = "\n\n".join(self.conversation_buffer)
        duration = int(time.time() - self.start_time)

        # Construir metadata
        metadata = {
            "project": self.current_project,
            "topic": self.current_topic,
            "tags": self.tags,
            "participants": self.participants,
            "tools_used": self.tools_used,
            "decisions": self.decisions + (decisions or []),
            "pending_tasks": self.pending_tasks + (pending or []),
            "duration_seconds": duration,
            "model": "deepseek-v4-flash",
            "summary": summary or self._auto_summary(),
        }

        # 1. Guardar chat completo
        chat_result = self.chat_logger.save(
            self.current_chat_id,
            content,
            metadata,
        )

        # 2. Actualizar diario del proyecto
        diary_result = self.diary.add_entry(
            self.current_project,
            {
                "chat_id": self.current_chat_id,
                "achievements": achievements or [],
                "decisions": [{"tema": d.split(":")[0] if ":" in d else d,
                               "decision": d.split(":", 1)[1].strip() if ":" in d else ""}
                              for d in (decisions or self.decisions)],
                "lessons": lessons or [],
                "pending": self.pending_tasks + (pending or []),
            },
        )

        # 3. Reconstruir índice
        index_result = self.indexer.rebuild()

        # 4. Resetear sesión
        duration_str = f"{duration // 60}m {duration % 60}s"
        result = {
            "status": "saved",
            "chat_id": self.current_chat_id,
            "project": self.current_project,
        "duration": duration_str,
        "chat_saved": chat_result,
        "diary_updated": diary_result,
        "index_entries": index_result.get("entries_count", 0),
        "config": {"supabase": "local", "pgvector": True, "embedding_dims": 384},
        }

        self._reset()
        return result

    def save_checkpoint(self) -> dict:
        """Guarda un checkpoint intermedio sin cerrar la sesión.

        Útil para sesiones largas — preserva el buffer.
        """
        if not self.conversation_buffer:
            return {"status": "empty"}

        # Guardar en episodic/ como checkpoint
        content = "\n\n".join(self.conversation_buffer)
        metadata = {
            "project": self.current_project,
            "topic": self.current_topic,
            "tags": self.tags,
            "participants": self.participants,
            "tools_used": self.tools_used,
            "summary": f"Checkpoint - {len(self.conversation_buffer)} turnos",
        }

        result = self.chat_logger.save(
            self.current_chat_id,
            content,
            metadata,
            target_dir="episodic",
        )
        return {
            "status": "checkpoint_saved",
            "chat_id": self.current_chat_id,
            "turns": len(self.conversation_buffer),
        }

    # ─── Integración con pipeline ─────────────────────────────

    def save_pipeline_run(
        self,
        requirement: str,
        final_state: dict,
        start_time: float,
        project: str | None = None,
    ) -> dict:
        """Guarda el resultado de una ejecución del pipeline.

        Se llama desde main.py después de run_swarm().

        Args:
            requirement: El requerimiento original
            final_state: El TeamState final del pipeline
            start_time: time.time() del inicio

        Returns:
            dict con resultados de la operación
        """
        project = project or "agent-swarm"
        topic = requirement[:60].strip()

        # Iniciar sesión con el requerimiento como primer turno
        self.begin(project=project, topic=topic, tags=["pipeline-run"])

        # Añadir el requerimiento como turno de usuario
        self.add_turn("user", requirement)

        # Añadir resultados como turno de Smith
        test_report = final_state.get("test_report", {})
        source_code = final_state.get("source_code", {})
        iterations = final_state.get("iteration_count", 0)
        status = test_report.get("status", "FAIL")

        result_summary = (
            f"Pipeline completado en {iterations} iteraciones.\n"
            f"Estado QA: {status}\n"
        )
        if source_code:
            files = list(source_code.keys())
            result_summary += f"Archivos generados: {', '.join(files)}\n"
        if test_report.get("errors"):
            result_summary += f"Errores: {len(test_report['errors'])}"

        self.add_turn("smith", result_summary)

        # Registrar herramientas usadas
        self.add_tool("python")
        self.add_tool("langgraph")
        self.add_tool("deepseek-v4-flash")
        if status == "PASS":
            self.add_tool("deepseek-v4-pro")

        # Decisiones del pipeline
        audit = final_state.get("audit_trail", [])
        for step in audit:
            action = step.get("accion", "")
            if action and len(action) > 20:
                self.add_decision(f"{step.get('nodo', '?')}: {action[:100]}")

        # Pendientes si falló
        if status == "FAIL":
            for err in test_report.get("errors", []):
                self.add_pending(f"Resolver: {str(err)[:100]}")

        # Finalizar sesión
        achievements = [f"Pipeline ejecutado: {status}"]
        if source_code:
            achievements.append(f"{len(source_code)} archivos generados")

        return self.end(
            achievements=achievements,
            summary=f"Pipeline: {requirement[:100]} — {status}",
        )

    # ─── Utilidad ──────────────────────────────────────────────

    def _auto_summary(self) -> str:
        """Genera resumen automático de los primeros turnos."""
        if not self.conversation_buffer:
            return ""
        first = self.conversation_buffer[0]
        # Limpiar formato markdown
        clean = first.replace("**", "").replace("*", "")
        return clean[:150]

    def _reset(self):
        """Resetea el estado de la sesión."""
        self.current_project = ""
        self.current_topic = ""
        self.current_chat_id = ""
        self.conversation_buffer = []
        self.start_time = 0.0
        self.tags = []
        self.tools_used = []
        self.decisions = []
        self.pending_tasks = []

    def status(self) -> dict:
        """Devuelve el estado actual de la sesión."""
        return {
            "active": bool(self.current_project),
            "project": self.current_project,
            "topic": self.current_topic,
            "chat_id": self.current_chat_id,
            "turns": len(self.conversation_buffer),
            "duration_seconds": int(time.time() - self.start_time) if self.start_time else 0,
        }
