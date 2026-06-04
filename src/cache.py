"""Caché de respuestas del enjambre — Fase 3: Efficiency Improvements.

Almacena respuestas de nodos costosos (Orquestador, Arquitecto, Auditor gates)
para evitar llamadas repetidas cuando el mismo requerimiento (o uno muy similar)
aparece de nuevo.

Estrategia:
- Key = SHA256 del requirement + nombre del nodo
- TTL = 24 horas por defecto
- Almacenamiento: archivos JSON en ~/.agents/enjambre_cache/
- Límite: 100 entradas máximo (FIFO)
"""

import hashlib
import json
import os
import time
from pathlib import Path

CACHE_DIR = Path.home() / ".agents" / "enjambre_cache"
DEFAULT_TTL = 86400  # 24 horas
MAX_ENTRIES = 100


def _ensure_cache_dir():
    """Crea el directorio de caché si no existe."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _cache_path(key: str) -> Path:
    """Devuelve la ruta del archivo de caché para una key."""
    return CACHE_DIR / f"{key}.json"


def _make_key(requirement: str, node_name: str) -> str:
    """Genera una key única para un requirement + nodo."""
    raw = f"{requirement.strip().lower()}::{node_name}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def _cleanup_if_needed():
    """Elimina entradas viejas si se supera MAX_ENTRIES."""
    if not CACHE_DIR.exists():
        return
    entries = sorted(CACHE_DIR.iterdir(), key=os.path.getmtime)
    if len(entries) > MAX_ENTRIES:
        for entry in entries[: len(entries) - MAX_ENTRIES]:
            try:
                entry.unlink()
            except OSError:
                pass


def get_cached(requirement: str, node_name: str) -> dict | None:
    """Obtiene respuesta cacheada. Retorna None si no existe o expiró."""
    _ensure_cache_dir()
    key = _make_key(requirement, node_name)
    path = _cache_path(key)

    if not path.exists():
        return None

    try:
        with open(path) as f:
            data = json.load(f)

        # Verificar TTL
        timestamp = data.get("_cached_at", 0)
        ttl = data.get("_ttl", DEFAULT_TTL)
        if time.time() - timestamp > ttl:
            path.unlink(missing_ok=True)
            return None

        # Actualizar timestamp de acceso (para cleanup FIFO)
        path.touch()

        return data.get("response")
    except (json.JSONDecodeError, OSError):
        return None


def set_cached(requirement: str, node_name: str, response: dict,
               ttl: int = DEFAULT_TTL):
    """Guarda respuesta en caché."""
    _ensure_cache_dir()
    key = _make_key(requirement, node_name)
    path = _cache_path(key)

    data = {
        "_cached_at": time.time(),
        "_ttl": ttl,
        "requirement": requirement[:100],
        "node": node_name,
        "response": response,
    }

    try:
        with open(path, "w") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        _cleanup_if_needed()
    except OSError:
        pass  # Si no se puede escribir, no es crítico


def invalidate_cache(requirement: str = None, node_name: str = None):
    """Invalida entradas de caché. Sin args, limpia todo."""
    if not CACHE_DIR.exists():
        return

    if requirement is None and node_name is None:
        # Limpiar todo
        for entry in CACHE_DIR.iterdir():
            try:
                entry.unlink()
            except OSError:
                pass
        return

    # Limpiar por requirement (para todos los nodos)
    if requirement and node_name is None:
        req_key = requirement.strip().lower()
        for entry in CACHE_DIR.iterdir():
            try:
                with open(entry) as f:
                    data = json.load(f)
                if data.get("requirement", "").strip().lower() == req_key:
                    entry.unlink()
            except (json.JSONDecodeError, OSError):
                pass
        return

    # Limpiar por requirement + node
    if requirement and node_name:
        key = _make_key(requirement, node_name)
        path = _cache_path(key)
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


def cache_stats() -> dict:
    """Estadísticas del caché."""
    if not CACHE_DIR.exists():
        return {"entries": 0, "size_bytes": 0}

    entries = list(CACHE_DIR.iterdir()) if CACHE_DIR.exists() else []
    total_size = sum(e.stat().st_size for e in entries if e.is_file())

    # Contar por nodo
    by_node = {}
    for entry in entries:
        try:
            with open(entry) as f:
                data = json.load(f)
            node = data.get("node", "unknown")
            by_node[node] = by_node.get(node, 0) + 1
        except (json.JSONDecodeError, OSError):
            pass

    return {
        "entries": len(entries),
        "size_bytes": total_size,
        "by_node": by_node,
    }
