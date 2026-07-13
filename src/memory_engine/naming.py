"""
🏷️ Sistema de Nomenclatura y Frontmatter del Memory Engine.

Patrón de nomenclatura:
  CHAT-{YYYYMMDD}-{proyecto}-{tema}-v{N}.md

Frontmatter YAML estándar:
  ---
  session_id: CHAT-20260713-proyecto-tema-v1
  type: session
  date: 2026-07-13
  project: proyecto
  topic: tema
  version: 1
  status: active
  tags: [tag1, tag2]
  ...
  ---

Este módulo NO depende de PyYAML — parsea YAML mínimo manualmente
con regex para evitar dependencias externas y ser ultra-rápido.
"""

from __future__ import annotations
import re
import os
from datetime import datetime
from typing import Any


# ─── Patrones ──────────────────────────────────────────────────

# CHAT-20260713-proyecto--tema-v1.md
# (doble guión separa proyecto de tema para evitar ambigüedad)
CHAT_ID_PATTERN = re.compile(
    r"^CHAT-(\d{8})-([a-z0-9-]+)--([a-z0-9-]+)-v(\d+)\.md$"
)

# Para extraer IDs de chats de cualquier texto
CHAT_ID_IN_TEXT = re.compile(
    r"CHAT-\d{8}-[a-z0-9-]+--[a-z0-9-]+-v\d+"
)

# Frontmatter YAML entre ---
FRONTMATTER_PATTERN = re.compile(
    r"^---\s*\n(.*?)\n---\s*\n",
    re.DOTALL
)

# Línea YAML simple (clave: valor o clave: [lista])
YAML_LINE = re.compile(r"^(\w[\w_]*):\s*(.*)$")

# YAML inline list: [item1, item2, ...]
YAML_INLINE_LIST = re.compile(r"^\[(.*)\]$")

# Para extraer proyectos de IDs de chat
PROJECT_FROM_CHAT = re.compile(r"^CHAT-\d{8}-([a-z0-9-]+)--")


# ─── Generación de IDs ─────────────────────────────────────────

def generate_chat_id(
    project: str,
    topic: str,
    date: str | None = None,
    version: int = 1,
) -> str:
    """Genera un chat ID siguiendo la convención.

    Usa '--' para separar proyecto de tema, evitando ambigüedad
    cuando cualquiera de ellos contiene guiones.

    Args:
        project: Nombre del proyecto
        topic: Tema específico
        date: Fecha YYYYMMDD o None para hoy
        version: Número de versión

    Returns:
        str: CHAT-{YYYYMMDD}-{proyecto}--{tema}-v{N}.md
    """
    date_str = date or datetime.utcnow().strftime("%Y%m%d")
    project_slug = _slugify(project)
    topic_slug = _slugify(topic)
    return f"CHAT-{date_str}-{project_slug}--{topic_slug}-v{version}.md"


def parse_chat_id(chat_id: str) -> dict | None:
    """Parsea un chat ID y devuelve sus componentes.

    Args:
        chat_id: ID como "CHAT-20260713-proyecto-tema-v1.md"

    Returns:
        dict con {date, project, topic, version, filename} o None
    """
    match = CHAT_ID_PATTERN.match(chat_id)
    if not match:
        return None
    return {
        "date": match.group(1),
        "project": match.group(2),
        "topic": match.group(3),
        "version": int(match.group(4)),
        "filename": chat_id,
    }


def extract_project_from_chat(chat_id: str) -> str | None:
    """Extrae el nombre del proyecto de un chat ID."""
    match = PROJECT_FROM_CHAT.match(chat_id)
    return match.group(1) if match else None


def next_version(chat_id: str) -> str:
    """Incrementa la versión de un chat_id.

    Ej: CHAT-20260713-proyecto-tema-v1.md → CHAT-20260713-proyecto-tema-v2.md
    """
    parsed = parse_chat_id(chat_id)
    if not parsed:
        return chat_id
    return generate_chat_id(
        project=parsed["project"],
        topic=parsed["topic"],
        date=parsed["date"],
        version=parsed["version"] + 1,
    )


# ─── Frontmatter ───────────────────────────────────────────────

def build_frontmatter(metadata: dict) -> str:
    """Construye un bloque frontmatter YAML a partir de un dict.

    Args:
        metadata: Diccionario con los metadatos

    Returns:
        str: Bloque YAML entre ---
    """
    lines = ["---"]
    for key, value in metadata.items():
        if value is None:
            continue
        if isinstance(value, list):
            if len(value) == 0:
                lines.append(f"{key}: []")
            elif all(isinstance(v, str) for v in value):
                items = ", ".join(v for v in value)
                lines.append(f"{key}: [{items}]")
            else:
                lines.append(f"{key}: {json_dumps(value)}")
        elif isinstance(value, dict):
            # Para chunks y otros objetos complejos, serializar como JSON
            lines.append(f"{key}: {json_dumps(value)}")
        elif isinstance(value, bool):
            lines.append(f"{key}: {'true' if value else 'false'}")
        elif isinstance(value, int) or isinstance(value, float):
            lines.append(f"{key}: {value}")
        else:
            lines.append(f"{key}: {str(value)}")
    lines.append("---")
    return "\n".join(lines) + "\n"


def parse_frontmatter(content: str) -> tuple[dict, str]:
    """Parsea frontmatter YAML de un contenido markdown.

    Args:
        content: Contenido completo del archivo (con o sin frontmatter)

    Returns:
        tuple: (metadata_dict, body_sin_frontmatter)
    """
    match = FRONTMATTER_PATTERN.match(content)
    if not match:
        return {}, content.strip()

    yaml_text = match.group(1)
    body = content[match.end():].strip()
    metadata = _parse_yaml_lines(yaml_text)

    return metadata, body


def chat_file_exists(chat_id: str, base_dir: str) -> bool:
    """Verifica si un archivo de chat existe en el directorio base."""
    # Buscar en chats/ y episodic/
    for subdir in ["chats", "episodic", "sueltas"]:
        path = os.path.join(base_dir, subdir, chat_id)
        if os.path.exists(path):
            return True
    return False


def resolve_chat_path(chat_id: str, base_dir: str) -> str | None:
    """Resuelve la ruta completa de un chat ID."""
    for subdir in ["chats", "episodic", "sueltas"]:
        path = os.path.join(base_dir, subdir, chat_id)
        if os.path.exists(path):
            return path
    return None


# ─── Helpers internos ──────────────────────────────────────────

def _slugify(text: str) -> str:
    """Convierte texto a slug para usar en IDs.

    Ej: "Enjambre Engine" → "enjambre-engine"
        "API REST" → "api-rest"
        "Bug #123" → "bug-123"
    """
    text = text.lower().strip()
    text = re.sub(r'[^a-z0-9-]+', '-', text)
    text = re.sub(r'-+', '-', text)
    text = text.strip('-')
    return text or "untitled"


def _parse_yaml_lines(yaml_text: str) -> dict:
    """Parsea líneas YAML simples (sin anidamiento complejo).

    Soporta:
      - clave: valor
      - clave: [item1, item2, ...]
      - clave: (dict JSON)
    """
    metadata = {}
    for line in yaml_text.split("\n"):
        line = line.strip()
        if not line:
            continue

        match = YAML_LINE.match(line)
        if not match:
            continue

        key = match.group(1)
        value_str = match.group(2).strip()

        # Lista inline: [item1, item2]
        list_match = YAML_INLINE_LIST.match(value_str)
        if list_match:
            items = [i.strip().strip('"').strip("'") for i in list_match.group(1).split(",")]
            metadata[key] = [i for i in items if i]
            continue

        # Booleanos
        if value_str.lower() == "true":
            metadata[key] = True
            continue
        if value_str.lower() == "false":
            metadata[key] = False
            continue

        # Números
        try:
            if "." in value_str:
                metadata[key] = float(value_str)
            else:
                metadata[key] = int(value_str)
            continue
        except ValueError:
            pass

        # String (sin comillas)
        metadata[key] = value_str.strip('"').strip("'")

    return metadata


def json_dumps(obj: Any) -> str:
    """JSON compacto para valores en YAML."""
    return json.dumps(obj, ensure_ascii=False, default=str)


# Para evitar import circular
import json
