"""
🧩 Chunker — Segmentación semántica de conversaciones.

Divide una conversación larga en chunks semánticos indexables.
Cada chunk tiene: índice, título, rango de turnos, resumen, temas.

Estrategia: chunking por turnos (turn-based) con agrupación semántica.
  - Cada interacción (user + agent) es una unidad mínima
  - Se agrupan turnos hasta alcanzar ~512 tokens
  - Se detectan cambios de tema por contenido
  - Cada chunk recibe un resumen generado por el agente
"""

from __future__ import annotations
import re
import math
from typing import Any

from src.memory_engine.models import ChatChunk


# ─── Constantes ────────────────────────────────────────────────

TARGET_TOKENS = 512       # Tokens objetivo por chunk
OVERLAP_TOKENS = 128      # Overlap entre chunks consecutivos
MIN_CHARS_PER_CHUNK = 200 # Caracteres mínimos por chunk (para evitar chunks vacíos)
MAX_CHARS_PER_CHUNK = 4000 # Caracteres máximos (~1000 tokens aprox)

# Patrón para detectar turnos en una conversación
TURN_PATTERN = re.compile(
    r"(?:^|\n)(?:\*\*?(?:Usuario|Isa|Tú|User|Isa Díaz|Yo)[:\*]?\*?|"
    r"(?:^|\n)(?:\*\*?Smith|Agente|Asistente|Enjambre|Orquestador)[:\*]?\*?)",
    re.IGNORECASE | re.MULTILINE
)

# Marcadores de cambio de tema
TOPIC_TRANSITION_MARKERS = [
    "ahora", "cambiando", "otro tema", "pasemos", "siguiente",
    "nuevo", "además", "por otro lado", "en cuanto a",
    "ahora", "change", "next", "another", "regarding",
    "con respecto a", "en relación con", "sobre",
]


# ─── Chunker principal ─────────────────────────────────────────

class Chunker:
    """Segmenta conversaciones en chunks semánticos."""

    def __init__(self, target_tokens: int = TARGET_TOKENS):
        self.target_tokens = target_tokens

    def chunk_conversation(self, content: str, chat_id: str = "") -> list[ChatChunk]:
        """Divide una conversación completa en chunks semánticos.

        Args:
            content: Texto completo de la conversación
            chat_id: ID del chat (para referencia)

        Returns:
            list[ChatChunk]: Lista de chunks indexables
        """
        if not content or not content.strip():
            return []

        # Si es muy corto, devolver 1 chunk con todo
        if len(content.strip()) < MIN_CHARS_PER_CHUNK:
            return [
                ChatChunk(
                    index=1,
                    title=self._generate_title(content, 1),
                    turn_start=1,
                    turn_end=1,
                    summary=self._generate_summary(content),
                    token_count=self._estimate_tokens(content),
                    topics=self._detect_topics(content),
                    tags=[],
                )
            ]

        # 1. Detectar turnos
        turns = self._split_turns(content)

        # 2. Agrupar turnos en chunks
        raw_chunks = self._group_turns(turns)

        # 3. Crear objetos ChatChunk
        chunks = []
        for i, (turn_start, turn_end, text) in enumerate(raw_chunks):
            chunk = ChatChunk(
                index=i + 1,
                title=self._generate_title(text, i + 1),
                turn_start=turn_start,
                turn_end=turn_end,
                summary=self._generate_summary(text),
                token_count=self._estimate_tokens(text),
                topics=self._detect_topics(text),
                tags=[],
            )
            chunks.append(chunk)

        return chunks

    def _split_turns(self, content: str) -> list[dict]:
        """Divide el contenido en turnos de conversación.

        Returns:
            list[dict]: [{speaker, text, index}, ...]
        """
        # Buscar todas las posiciones de inicio de turno
        matches = list(TURN_PATTERN.finditer(content))
        if not matches:
            # No se detectaron turnos → tratar todo como un solo turno
            return [{"speaker": "unknown", "text": content.strip(), "index": 1}]

        turns = []
        for i, match in enumerate(matches):
            start = match.start()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
            turn_text = content[start:end].strip()
            if turn_text:
                speaker = self._detect_speaker(match.group())
                turns.append({
                    "speaker": speaker,
                    "text": turn_text,
                    "index": i + 1,
                })

        return turns

    def _detect_speaker(self, turn_header: str) -> str:
        """Detecta quién habla en un turno."""
        header = turn_header.lower().strip("*").strip()
        if any(name in header for name in ["usuario", "isa", "tú", "user", "yo"]):
            return "user"
        return "agent"

    def _group_turns(self, turns: list[dict]) -> list[tuple[int, int, str]]:
        """Agrupa turnos en chunks de tamaño objetivo.

        Returns:
            list[(turn_start, turn_end, text)]
        """
        if not turns:
            return []

        chunks = []
        current_turns = []
        current_chars = 0
        current_start = 1

        for turn in turns:
            turn_chars = len(turn["text"])
            needs_new = False

            # Detectar cambio de tema
            if self._is_topic_transition(turn["text"]):
                needs_new = True

            # Si el chunk actual excede el límite
            if current_chars + turn_chars > MAX_CHARS_PER_CHUNK:
                needs_new = True

            if needs_new and current_turns:
                # Cerrar chunk actual
                chunk_text = "\n\n".join(t["text"] for t in current_turns)
                chunks.append((current_start, current_turns[-1]["index"], chunk_text))
                current_start = turn["index"]
                current_turns = []
                current_chars = 0

            current_turns.append(turn)
            current_chars += turn_chars

        # Último chunk
        if current_turns:
            chunk_text = "\n\n".join(t["text"] for t in current_turns)
            chunks.append((current_start, current_turns[-1]["index"], chunk_text))

        return chunks

    def _is_topic_transition(self, text: str) -> bool:
        """Detecta si un texto indica cambio de tema."""
        text_lower = text.lower()
        for marker in TOPIC_TRANSITION_MARKERS:
            if marker in text_lower[:200]:  # Solo primeros 200 chars
                # Verificar que sea inicio de turno
                first_words = text_lower.split()[:10]
                first_text = " ".join(first_words)
                if marker in first_text:
                    return True
        return False

    def _generate_title(self, text: str, index: int) -> str:
        """Genera un título descriptivo para el chunk."""
        # Tomar las primeras palabras significativas
        first_line = text.strip().split("\n")[0][:100]
        # Limpiar formato markdown
        first_line = re.sub(r'[*#_\[\]]', '', first_line).strip()
        if len(first_line) > 60:
            first_line = first_line[:57] + "..."
        return first_line if first_line else f"Chunk {index:03d}"

    def _generate_summary(self, text: str) -> str:
        """Genera un resumen de 1-2 líneas del chunk."""
        # Por ahora, extracción simple de primeras líneas
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        # Buscar líneas con preguntas o afirmaciones clave
        key_lines = []
        for line in lines[:15]:  # Prrimeras 15 líneas
            clean = re.sub(r'[*#_\[\]]', '', line).strip()
            if clean and len(clean) > 20:
                key_lines.append(clean)
            if len(key_lines) >= 2:
                break

        if key_lines:
            summary = " / ".join(key_lines[:2])
            return summary[:200]
        return f"Segmento de conversación ({self._estimate_tokens(text)} tokens)"

    def _detect_topics(self, text: str) -> list[str]:
        """Detecta palabras clave/temas en el texto."""
        # Palabras clave comunes en nuestro dominio
        keywords = [
            "enjambre", "agente", "pipeline", "debug", "deploy",
            "api", "frontend", "backend", "database", "memoria",
            "chat", "proyecto", "skill", "código", "test",
            "arquitectura", "diseño", "implementar", "bug",
            "websocket", "dashboard", "3d", "websocket",
        ]
        found = []
        text_lower = text.lower()
        for kw in keywords:
            if kw in text_lower:
                found.append(kw)
        return found[:5]  # Máximo 5 temas

    def _estimate_tokens(self, text: str) -> int:
        """Estima tokens (aproximación 4 chars = 1 token)."""
        return max(1, len(text) // 4)


# ─── Utilidad ──────────────────────────────────────────────────

def token_estimate(text: str) -> int:
    """Estimación rápida de tokens (chars/4)."""
    return max(1, len(text) // 4)
