"""Utilidades de Supabase — embeddings locales, búsqueda híbrida, inserción de memoria.

Embeddings:
  Usa fastembed con BAAI/bge-small-en-v1.5 (384 dimensiones) en local.
  No requiere API key externa — el modelo se descarga y cachea automáticamente.

Supabase:
  Service role key para operaciones de escritura/lectura en agent_memory.
  Búsqueda híbrida (RRF) vía RPC con fallback a select directo por fecha.
"""

import re  # Para _clean_error: parsear HTML de errores Supabase

from supabase import create_client
from fastembed import TextEmbedding
from src.config import SUPABASE_URL, SUPABASE_SERVICE_KEY

# ── Clientes singleton ──
_supabase = None
_embedding_model = None
_schema_ready = None

# Dimensión del embedding del modelo elegido (BAAI/bge-small-en-v1.5)
EMBEDDING_DIM = 384


def get_supabase():
    """Devuelve el cliente de Supabase (singleton)."""
    global _supabase
    if _supabase is None:
        _supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
    return _supabase


def get_embedding_model() -> TextEmbedding:
    """Devuelve el modelo de embeddings local (fastembed, singleton).
    
    Modelo: BAAI/bge-small-en-v1.5 → 384 dimensiones.
    Descarga automática en primera ejecución (cacheado en HF cache).
    """
    global _embedding_model
    if _embedding_model is None:
        print("[Embeddings] Cargando modelo local BAAI/bge-small-en-v1.5 (384 dims)...")
        _embedding_model = TextEmbedding(model_name="BAAI/bge-small-en-v1.5")
        print("[Embeddings] Modelo listo")
    return _embedding_model


def generate_embedding(text: str) -> list[float]:
    """Genera un vector de embedding local para un texto dado.
    
    fastembed devuelve numpy.ndarray → convertimos a lista Python
    para serialización JSON compatible con Supabase.
    
    Returns:
        Lista de floats de 384 dimensiones.
    """
    model = get_embedding_model()
    # fastembed.embed() devuelve generador de ndarrays
    embedding_ndarray = list(model.embed(text))[0]
    if hasattr(embedding_ndarray, 'tolist'):
        return embedding_ndarray.tolist()
    return list(embedding_ndarray)


def _clean_error(msg: str) -> str:
    """Si el error viene como HTML (RPC no existe o 404), devuelve mensaje limpio."""
    if not isinstance(msg, str):
        msg = str(msg)
    if msg.startswith("<!DOCTYPE") or "<html" in msg[:100]:
        match = re.search(r"<title>([^<]+)</title>", msg)
        if match:
            title = match.group(1)
            if "Not Found" in title or "404" in title:
                return "Supabase: endpoint no encontrado (404) — verifica URL o permisos"
            return f"Supabase: {title} (¿ejecutaste el schema SQL?)"
        return "Supabase: schema no configurado — ejecuta supabase_schema.sql en el SQL Editor"
    # Si es un dict (error de API de Supabase), extraer mensaje
    if isinstance(msg, str) and msg.startswith("{") and "message" in msg[:100]:
        try:
            import json
            parsed = json.loads(msg)
            return f"Supabase: {parsed.get('message', msg[:200])}"
        except json.JSONDecodeError:
            pass
    return msg[:200]


def is_schema_ready() -> bool:
    """Verifica si la tabla agent_memory existe en Supabase."""
    global _schema_ready
    if _schema_ready is not None:
        return _schema_ready
    try:
        supabase = get_supabase()
        result = supabase.table("agent_memory").select("id", count="exact").limit(0).execute()
        _schema_ready = result is not None
        return _schema_ready
    except Exception:
        _schema_ready = False
        return False


async def hybrid_search(query: str, limit: int = 5) -> str:
    """Búsqueda híbrida (RRF: Reciprocal Rank Fusion) en agent_memory.
    
    Combina similitud coseno (vectorial local) con búsqueda de texto completo (BM25).
    Retorna el contenido relevante concatenado como contexto para el LLM.
    
    Fallbacks:
    1. RPC match_agent_memory (híbrido real) → si falla por schema
    2. Select directo sin ranking por fecha → último recurso
    """
    if not is_schema_ready():
        return "[Sin memoria previa — schema no configurado en Supabase]"

    try:
        emb = generate_embedding(query)
        supabase = get_supabase()

        # Búsqueda híbrida (RRF) definida en supabase_schema.sql
        result = supabase.rpc("match_agent_memory", {
            "query_embedding": emb,
            "query_text": query,
            "match_limit": limit,
            "similarity_threshold": 0.5,
        }).execute()

        rows = result.data or []
        if not rows:
            return "[Sin memoria previa relevante]"

        context_parts = []
        for row in rows:
            score = row.get("similarity", 0)
            rrf = row.get("rrf_score", 0)
            content = row.get("content", "")
            task = row.get("task_type", "general")
            context_parts.append(
                f"[Memoria — Score: {score:.3f} | RRF: {rrf:.3f} — Tipo: {task}]\n{content}"
            )

        return "\n\n---\n\n".join(context_parts)
    except Exception as e:
        err_msg = _clean_error(str(e))
        print(f"[Supabase] RPC híbrido falló: {err_msg}")

        # Fallback: select directo con orden por fecha
        try:
            supabase = get_supabase()
            result = supabase.table("agent_memory") \
                .select("content, task_type, created_at") \
                .order("created_at", desc=True) \
                .limit(limit) \
                .execute()
            rows = result.data or []
            if not rows:
                return "[Sin memoria previa relevante]"
            context_parts = []
            for row in rows:
                task = row.get("task_type", "general")
                content = row.get("content", "")
                ts = row.get("created_at", "")[:10]
                context_parts.append(f"[Memoria reciente — {ts} — Tipo: {task}]\n{content}")
            print("[Supabase] Usando fallback: select directo por fecha")
            return "\n\n---\n\n".join(context_parts)
        except Exception as e2:
            err_msg2 = _clean_error(str(e2))
            print(f"[Supabase] Error total en búsqueda: {err_msg2}")
            return "[Error al buscar memoria — continuando sin contexto previo]"


async def save_to_memory(task_type: str, content: str, metadata: dict = None):
    """Inserta una nueva entrada en la memoria vectorial."""
    if not is_schema_ready():
        print(f"[Supabase] Memoria NO guardada (schema no configurado) — {task_type}: {content[:80]}...")
        return

    try:
        emb = generate_embedding(content)
        supabase = get_supabase()

        # Intentar vía RPC primero
        supabase.rpc("insert_agent_memory", {
            "p_task_type": task_type,
            "p_content": content,
            "p_embedding": emb,
            "p_metadata": metadata or {},
        }).execute()

        print(f"[Supabase] Memoria guardada: {task_type} ({len(content)} chars)")
    except Exception as e:
        err_msg = _clean_error(str(e))
        print(f"[Supabase] RPC insert falló: {err_msg}")
        # Fallback: inserción directa en la tabla
        try:
            supabase = get_supabase()
            supabase.table("agent_memory").insert({
                "task_type": task_type,
                "content": content,
                "embedding": emb,  # reuse embedding from above
                "metadata": metadata or {},
            }).execute()
            print(f"[Supabase] Memoria guardada (directa): {task_type} ({len(content)} chars)")
        except Exception as e2:
            err_msg2 = _clean_error(str(e2))
            print(f"[Supabase] Error guardando memoria: {err_msg2}")
