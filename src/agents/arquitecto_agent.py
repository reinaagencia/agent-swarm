"""Arquitecto Agent — CLI wrapper independiente para diseño de sistemas.

Uso:
    python3 -m src.agents.arquitecto_agent '{"requirement": "API REST Flask", "rules": ["usar PostgreSQL"], "memory": "..."}'

Output: JSON con {"blueprint", "notas", "audit"}
"""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.config import get_llm, get_budget, TEMPERATURE_CREATIVE
from src.token_juice import compress
from langchain_core.messages import HumanMessage, SystemMessage


ARCHITECT_SYSTEM_PROMPT = """Eres el Arquitecto de Software del Enjambre 4.0 — Agente independiente.

Diseñas arquitecturas de software modulares, claras y testables. 
Generas blueprints JSON detallados con estructura de archivos, funciones, dependencias y flujo de datos.

RESPONDE ÚNICAMENTE EN JSON:
{
  "arquitectura": {
    "descripcion_general": "...",
    "archivos": {
      "nombre.py": {
        "proposito": "...",
        "clases": [...],
        "funciones_publicas": [{"nombre": "...", "signature": "def f(x: int) -> str", "descripcion": "..."}],
        "dependencias": [...]
      }
    },
    "flujo_datos": "...",
    "decisiones_tecnicas": ["... y por qué"],
    "casos_borde_considerados": ["..."],
    "plan_tests": "..."
  },
  "notas_scratchpad": ["nota 1", "nota 2"]
}"""


async def disenar(requirement: str, rules: list = None, memory: str = "",
                  enfoque: str = "ROBUSTO") -> dict:
    """Diseña la arquitectura para un requerimiento."""
    
    print(f"[Arquitecto Agent] 🏗️ Diseñando ({enfoque}): {requirement[:100]}...")
    
    # Comprimir contexto si es necesario
    if len(requirement) > 3000:
        requirement, _ = compress(requirement, max_tokens=2000)
    
    rules_str = "\n".join(f"- {r}" for r in (rules or [])[:8])
    memory_str = memory[:500] if memory else "(sin memoria previa)"
    
    prompt = f"""REQUERIMIENTO:
{requirement}

ENFOQUE: {enfoque}

REGLAS DE NEGOCIO:
{rules_str or '(sin reglas)'}

MEMORIA DE PROYECTOS SIMILARES:
{memory_str}

Diseña la arquitectura completa. Responde SOLO el JSON."""

    llm = get_llm(temperature=TEMPERATURE_CREATIVE, max_tokens=get_budget("architect"))
    
    try:
        response = await llm.ainvoke([
            SystemMessage(content=ARCHITECT_SYSTEM_PROMPT),
            HumanMessage(content=prompt),
        ])
        content = response.content if hasattr(response, 'content') else str(response)
    except Exception as e:
        return {
            "blueprint": {"descripcion_general": f"Error LLM: {str(e)[:200]}", "archivos": {}},
            "notas": [f"Error: {str(e)[:200]}"],
            "audit": {"action": "design", "status": "error", "error": str(e)[:200]},
        }
    
    # Parsear JSON
    try:
        content = content.strip()
        if content.startswith("```"):
            lines = content.split("\n")
            content = "\n".join(lines[1:-1])
        result = json.loads(content)
    except json.JSONDecodeError:
        result = {
            "arquitectura": {"descripcion_general": content[:500], "archivos": {}},
            "notas_scratchpad": ["Error parseando JSON del LLM"],
        }
    
    blueprint = result.get("arquitectura", {})
    notas = result.get("notas_scratchpad", [])
    
    return {
        "blueprint": blueprint,
        "notas": notas,
        "audit": {
            "action": "architecture_design",
            "enfoque": enfoque,
            "files_designed": len(blueprint.get("archivos", {})),
            "status": "ok",
        }
    }


def main():
    """CLI entry point."""
    if len(sys.argv) > 1:
        try:
            data = json.loads(sys.argv[1])
        except json.JSONDecodeError:
            print(json.dumps({"error": "Invalid JSON input"}))
            sys.exit(1)
    elif not sys.stdin.isatty():
        raw = sys.stdin.read()
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            print(json.dumps({"error": "Invalid JSON from stdin"}))
            sys.exit(1)
    else:
        print(json.dumps({"error": "No input. Use: echo '{\"requirement\":\"...\"}' | python3 -m src.agents.arquitecto_agent"}))
        sys.exit(1)
    
    requirement = data.get("requirement", "")
    rules = data.get("rules", [])
    memory = data.get("memory", "")
    enfoque = data.get("enfoque", "ROBUSTO")
    
    result = asyncio.run(disenar(requirement, rules=rules, memory=memory, enfoque=enfoque))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
