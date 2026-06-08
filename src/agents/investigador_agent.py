"""Investigador Agent — CLI wrapper independiente para búsqueda RAG.

Uso:
    python3 -m src.agents.investigador_agent '{"query": "cómo crear API REST", "limit": 5}'
    
    O desde stdin:
    echo '{"query": "conciliación bancaria CSV"}' | python3 -m src.agents.investigador_agent

Output: JSON con {"query", "results", "audit"}
"""

import asyncio
import json
import sys
from pathlib import Path

# Asegurar que el src/ está en el path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.supabase_utils import hybrid_search
from src.token_juice import compress


async def investigar(query: str, limit: int = 5, compress_result: bool = True) -> dict:
    """Ejecuta búsqueda RAG híbrida en Supabase y retorna resultados estructurados."""
    
    print(f"[Investigador Agent] 🔍 Buscando: {query[:120]}...")
    
    try:
        resultados = await hybrid_search(query, limit=limit)
    except Exception as e:
        print(f"[Investigador Agent] ⚠️ Supabase no disponible: {e}")
        resultados = f"(memoria no disponible: {str(e)[:100]})"
    
    if compress_result and len(resultados) > 2000:
        comprimido, report = compress(resultados, max_tokens=1500)
        print(f"[Investigador Agent] TokenJuice: {report['tokens_before']} → {report['tokens_after']} tokens")
        resultados = comprimido
    
    return {
        "query": query,
        "results": resultados[:5000],  # safety cap
        "audit": {
            "action": "hybrid_search_rrf",
            "database": "agent_memory (Supabase pgvector)",
            "result_length": len(resultados),
            "status": "ok",
        }
    }


def main():
    """CLI entry point."""
    query_str = ""
    
    if len(sys.argv) > 1:
        # Desde argumento JSON
        try:
            data = json.loads(sys.argv[1])
            query_str = data.get("query", "")
            limit = data.get("limit", 5)
        except json.JSONDecodeError:
            query_str = sys.argv[1]
            limit = 5
    elif not sys.stdin.isatty():
        # Desde stdin
        raw = sys.stdin.read()
        try:
            data = json.loads(raw)
            query_str = data.get("query", "")
            limit = data.get("limit", 5)
        except json.JSONDecodeError:
            query_str = raw.strip()
            limit = 5
    else:
        print(json.dumps({"error": "No query provided. Use: echo '{\"query\":\"...\"}' | python3 -m src.agents.investigador_agent"}))
        sys.exit(1)
    
    result = asyncio.run(investigar(query_str, limit=limit))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
