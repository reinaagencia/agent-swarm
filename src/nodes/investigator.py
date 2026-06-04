"""Nodo 1 — Investigador (Contexto RAG).
Toma el user_requirement, genera embedding, busca en Supabase con búsqueda híbrida,
y llena retrieved_memory en el estado."""

from langchain_core.messages import SystemMessage
from src.state import TeamState
from src.supabase_utils import hybrid_search


async def investigator_node(state: TeamState) -> dict:
    """Recupera memoria relevante de Supabase usando búsqueda híbrida (RRF)."""
    query = state.get("user_requirement", "")
    print(f"[Investigador] Buscando memoria para: {query[:80]}...")

    retrieved = await hybrid_search(query, limit=5)

    return {
        "retrieved_memory": retrieved,
        "audit_trail": [{
            "nodo": "Investigador",
            "accion": "Búsqueda híbrida RRF en agent_memory",
            "resultado": f"{len(retrieved)} caracteres recuperados",
        }],
        "messages": [SystemMessage(content=f"[Memoria RAG recuperada]\n{retrieved}")],
    }
