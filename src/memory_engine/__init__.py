"""
🧠 Memory Engine — Sistema de Memoria Multi-Capa (L0-L5)
Enjambre 4.0 :: Agent Swarm

Arquitectura:
  L0: Working Memory (TeamState en LangGraph)
  L1: Episodic Buffer (sesión activa en ~/.agents/memoria/episodic/)
  L2: Chats Históricos (conversaciones completas + índice en ~/.agents/memoria/chats/)
  L3: Diarios de Proyecto (resúmenes ejecutivos en ~/.agents/memoria/proyectos/)
  L4: Índice General Maestro (cross-layer index en Supabase + JSON local)
  L5: Procesamiento Offline (consolidación, defragmentación, reflexión)

Uso rápido:
    from src.memory_engine import MemoryEngine
    engine = MemoryEngine()
    engine.save_chat("CHAT-20260713-proyecto-tema-v1.md", contenido)
    results = engine.search("consulta", project="enjambre-engine")
    engine.merge_projects(["proj-a", "proj-b"], strategy="fuse")
"""

from src.memory_engine.models import (
    ChatSession,
    ChatChunk,
    ProjectDiary,
    IndexEntry,
    SearchResult,
    MergeStrategy,
)
from src.memory_engine.naming import (
    generate_chat_id,
    parse_chat_id,
    parse_frontmatter,
    build_frontmatter,
    next_version,
    CHAT_ID_PATTERN,
)
from src.memory_engine.session_manager import SessionManager
from src.memory_engine.chat_logger import ChatLogger
from src.memory_engine.chunker import Chunker
from src.memory_engine.indexer import Indexer
from src.memory_engine.search import Searcher
from src.memory_engine.diary import DiaryManager
from src.memory_engine.project_manager import ProjectManager


class MemoryEngine:
    """Orquestador principal del sistema de memoria multi-capa."""

    def __init__(self, base_dir: str | None = None):
        import os
        self.base_dir = base_dir or os.path.expanduser("~/.agents/memoria")
        self.chat_logger = ChatLogger(self.base_dir)
        self.chunker = Chunker()
        self.indexer = Indexer(self.base_dir)
        self.searcher = Searcher(self.base_dir)
        self.diary = DiaryManager(self.base_dir)
        self.project_manager = ProjectManager(self.base_dir)

    # ── L1/L2: Chats ──────────────────────────────────────────

    def save_chat(self, chat_id: str, content: str, metadata: dict | None = None) -> dict:
        """Guarda un chat completo en L1/L2 con índice automático."""
        return self.chat_logger.save(chat_id, content, metadata)

    def get_chat(self, chat_id: str) -> str | None:
        """Recupera un chat completo."""
        return self.chat_logger.get(chat_id)

    def list_chats(self, project: str | None = None) -> list[dict]:
        """Lista chats, opcionalmente filtrados por proyecto."""
        return self.chat_logger.list_chats(project)

    def get_chat_index(self, chat_id: str) -> dict | None:
        """Obtiene solo el índice (frontmatter + resumenes) de un chat."""
        return self.chat_logger.get_index(chat_id)

    # ── L3: Diarios ───────────────────────────────────────────

    def get_diary(self, project: str) -> dict | None:
        """Obtiene el diario de un proyecto."""
        return self.diary.get(project)

    def update_diary(self, project: str, entry: dict) -> dict:
        """Añade una entrada al diario de un proyecto."""
        return self.diary.add_entry(project, entry)

    def list_projects(self) -> list[dict]:
        """Lista todos los proyectos con sus metadatos."""
        return self.diary.list_projects()

    # ── L4: Índice y Búsqueda ─────────────────────────────────

    def search(self, query: str, **filters) -> list[SearchResult]:
        """Búsqueda híbrida en toda la memoria (L2+L3+L4)."""
        return self.searcher.hybrid_search(query, **filters)

    def rebuild_index(self) -> dict:
        """Reconstruye el índice general desde cero."""
        return self.indexer.rebuild()

    def get_index(self) -> dict:
        """Obtiene el índice general maestro."""
        return self.indexer.get_index()

    # ── Gestión de Proyectos ──────────────────────────────────

    def merge_projects(self, project_names: list[str], strategy: str = "group", **kwargs) -> dict:
        """Une proyectos: 'group' (carpeta macro) o 'fuse' (fusión real)."""
        new_name = kwargs.get("new_name")
        return self.project_manager.merge(project_names, strategy, new_name)

    def split_project(self, project_name: str, splits: list[dict]) -> dict:
        """Divide un proyecto en múltiples sub-proyectos."""
        return self.project_manager.split(project_name, splits)

    # ── L5: Offline ──────────────────────────────────────────

    def run_maintenance(self) -> dict:
        """Ejecuta mantenimiento: consolidación, defragmentación, reflexión."""
        return self._run_offline_processing()

    def _run_offline_processing(self) -> dict:
        """Procesamiento offline (sleep-time compute)."""
        import time
        start = time.time()
        results = {
            "consolidated": 0,
            "defragmented": 0,
            "reflections": [],
            "duration_seconds": 0,
        }
        # 1. Consolidar L1→L2 (cerrar sesiones abandonadas)
        results["consolidated"] = self.chat_logger.consolidate_episodic()
        # 2. Reconstruir índice si es necesario
        if self.indexer.needs_rebuild():
            results["defragmented"] = 1
            self.indexer.rebuild()
        # 3. Actualizar diarios con reflexiones
        results["duration_seconds"] = round(time.time() - start, 2)
        return results


__all__ = [
    "MemoryEngine",
    "ChatSession", "ChatChunk", "ProjectDiary", "IndexEntry", "SearchResult", "MergeStrategy",
    "generate_chat_id", "parse_chat_id", "parse_frontmatter", "build_frontmatter",
    "SessionManager",
    "ChatLogger", "Chunker", "Indexer", "Searcher", "DiaryManager", "ProjectManager",
]
