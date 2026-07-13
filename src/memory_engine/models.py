"""
📦 Modelos de datos del Memory Engine.

Define las estructuras fundamentales para todo el sistema de memoria:
  - ChatSession: una conversación completa
  - ChatChunk: un segmento indexable de un chat
  - ProjectDiary: el diario de avance de un proyecto
  - IndexEntry: entrada en el índice general maestro
  - SearchResult: resultado de una búsqueda híbrida
  - MergeStrategy: tipos de fusión de proyectos
"""

from __future__ import annotations
import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from typing import Any


# ─── Enums ─────────────────────────────────────────────────────

class ChatStatus(str, Enum):
    ACTIVE = "active"        # Sesión en curso
    CLOSED = "closed"        # Sesión finalizada normalmente
    ARCHIVED = "archived"    # Conservado pero no activo
    CORRUPTED = "corrupted"  # Archivo dañado o incompleto


class EntryType(str, Enum):
    CHAT = "chat"              # Conversación
    DIARY = "diary"            # Entrada de diario
    NOTE = "note"              # Nota de conocimiento
    PROJECT = "project"        # Proyecto
    TASK = "task"              # Tarea suelta sin proyecto


class ProjectStatus(str, Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class MergeStrategy(str, Enum):
    GROUP = "group"   # Carpeta macro: proyectos intactos bajo mismo paraguas
    FUSE = "fuse"     # Fusión real: reestructuración en un solo proyecto


# ─── Dataclasses ───────────────────────────────────────────────

@dataclass
class ChatChunk:
    """Un segmento indexable de una conversación."""
    index: int                       # Número de chunk (001, 002...)
    title: str                       # Título descriptivo del chunk
    turn_start: int                  # Turno inicial del chunk
    turn_end: int                    # Turno final del chunk
    summary: str                     # Resumen de 1-2 líneas
    token_count: int = 0             # Tokens estimados
    topics: list[str] = field(default_factory=list)  # Temas detectados
    tags: list[str] = field(default_factory=list)    # Tags del chunk

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> ChatChunk:
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class ChatSession:
    """Una conversación completa entre Smith y el usuario."""
    session_id: str                  # CHAT-20260713-proyecto-tema-v1
    type: str = "session"            # Tipo de entrada
    date: str = ""                   # YYYY-MM-DD
    project: str = ""                # Nombre del proyecto
    topic: str = ""                  # Tema específico
    version: int = 1                 # Versión
    status: ChatStatus = ChatStatus.ACTIVE

    # Metadatos extendidos
    tags: list[str] = field(default_factory=list)
    model: str = ""
    tokens_used: int = 0
    duration_seconds: int = 0
    summary: str = ""
    participants: list[str] = field(default_factory=list)
    tools_used: list[str] = field(default_factory=list)
    decisions: list[str] = field(default_factory=list)
    pending_tasks: list[str] = field(default_factory=list)
    linked_chats: list[str] = field(default_factory=list)

    # Índice de chunks
    chunks: list[ChatChunk] = field(default_factory=list)

    # Metadatos del sistema
    created_at: str = ""
    updated_at: str = ""
    file_path: str = ""
    file_size: int = 0
    is_corrupted: bool = False

    def to_frontmatter(self) -> dict:
        """Convierte a dict plano para frontmatter YAML."""
        d = asdict(self)
        d["status"] = self.status.value
        d["chunks"] = [c.to_dict() for c in (self.chunks or [])]
        d["version"] = self.version
        return d

    @classmethod
    def from_frontmatter(cls, data: dict) -> ChatSession:
        """Reconstruye desde un dict de frontmatter."""
        chunks_data = data.pop("chunks", []) or []
        status_val = data.pop("status", "active")
        chunks = [ChatChunk.from_dict(c) if isinstance(c, dict) else c for c in chunks_data]
        return cls(
            **{k: v for k, v in data.items() if k in cls.__dataclass_fields__ and k != "chunks"},
            status=ChatStatus(status_val),
            chunks=chunks,
        )


@dataclass
class ProjectDiary:
    """Diario de avance de un proyecto."""
    project_id: str                  # Nombre único del proyecto
    title: str = ""                  # Nombre legible
    status: ProjectStatus = ProjectStatus.ACTIVE
    priority: str = "🟡 MEDIA"
    description: str = ""
    tags: list[str] = field(default_factory=list)
    linked_chats: list[str] = field(default_factory=list)  # IDs de chats relacionados
    parent_project: str = ""         # Si es sub-proyecto, proyecto padre
    child_projects: list[str] = field(default_factory=list)  # Sub-proyectos

    # Línea de tiempo
    entries: list[dict] = field(default_factory=list)  # Lista de entradas del diario
    # {date, chat_id, achievements, decisions, lessons, pending}

    # Métricas
    total_chats: int = 0
    total_tokens: int = 0
    last_active: str = ""

    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d["status"] = self.status.value
        return d

    @classmethod
    def from_dict(cls, d: dict) -> ProjectDiary:
        status_val = d.pop("status", "active")
        entries = d.pop("entries", []) or []
        return cls(
            **{k: v for k, v in d.items() if k in cls.__dataclass_fields__ and k != "entries"},
            status=ProjectStatus(status_val),
            entries=entries,
        )


@dataclass
class IndexEntry:
    """Entrada en el índice general maestro (L4)."""
    id: str                          # ID único (chat_id o project_id)
    type: EntryType                  # Tipo de entrada
    title: str = ""                  # Título descriptivo
    project: str = ""                # Proyecto al que pertenece (si aplica)
    date: str = ""                   # Fecha YYYY-MM-DD
    tags: list[str] = field(default_factory=list)
    summary: str = ""                # Resumen de 1 línea
    token_count: int = 0
    status: str = ""
    file_path: str = ""              # Ruta al archivo completo
    linked_to: list[str] = field(default_factory=list)  # IDs de entradas relacionadas

    # Scores de búsqueda (se llenan en runtime)
    search_score: float = 0.0
    search_method: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d["type"] = self.type.value
        return d

    @classmethod
    def from_dict(cls, d: dict) -> IndexEntry:
        type_val = d.pop("type", "chat")
        return cls(
            **{k: v for k, v in d.items() if k in cls.__dataclass_fields__},
            type=EntryType(type_val),
        )


@dataclass
class SearchResult:
    """Resultado de una búsqueda híbrida."""
    entries: list[IndexEntry] = field(default_factory=list)
    query: str = ""
    total_results: int = 0
    methods_used: list[str] = field(default_factory=list)
    timing_ms: float = 0.0
    filters_applied: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "query": self.query,
            "total_results": self.total_results,
            "methods_used": self.methods_used,
            "timing_ms": self.timing_ms,
            "filters_applied": self.filters_applied,
            "entries": [e.to_dict() for e in self.entries],
        }


# ─── Helpers ───────────────────────────────────────────────────

def now_iso() -> str:
    """Devuelve timestamp ISO 8601 actual."""
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


def today_str() -> str:
    """Devuelve fecha actual como YYYY-MM-DD."""
    return datetime.utcnow().strftime("%Y-%m-%d")


def today_compact() -> str:
    """Devuelve fecha actual como YYYYMMDD."""
    return datetime.utcnow().strftime("%Y%m%d")
