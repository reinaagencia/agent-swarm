"""Estratega Agent — Planificador multi-paso con MoA y memoria jerárquica.

ROL:
  Recibe un requerimiento complejo del usuario.
  Consulta la memoria jerárquica (L1/L2/L3) para contexto.
  Descompone en subtareas con dependencias.
  Asigna agente óptimo a cada subtarea.
  Estima complejidad, tokens y presupuesto.
  Genera un plan de ejecución estructurado (JSON).

USO:
  python3 -m src.agents.estratega_agent '{"requirement": "...", "context": {...}}'

ARQUITECTURA MoA (Mixture-of-Agents):
  El estratega usa 3 perspectivas de razonamiento:
    A. MINIMALISTA: ¿Cuál es el camino más corto?
    B. ROBUSTO: ¿Cuál es la solución más completa?
    C. ARRIESGADO: ¿Qué atajos creativos podemos tomar?
  Sintetiza las 3 en un plan final balanceado.
"""

import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.config import get_llm, get_budget, TEMPERATURE_CREATIVE
from src.token_juice import compress
from langchain_core.messages import HumanMessage, SystemMessage


ESTRATEGA_SYSTEM_PROMPT = """Eres el Estratega del Enjambre 4.0 — Planificador Multi-Paso con MoA.

## Tu Rol
Descompones requerimientos complejos en planes de ejecución. NO ejecutas — planificas.
Usas razonamiento multi-perspectiva (MoA) para encontrar el mejor camino.

## Proceso de Planificación
1. Analiza el requerimiento y contexto de memoria
2. Descompón en subtareas atómicas (3-8 pasos)
3. Para cada subtarea: define agente, inputs, outputs esperados
4. Identifica dependencias entre subtareas
5. Estima complejidad, tokens y presupuesto
6. Aplica 3 perspectivas MoA → sintetiza plan final

## Agentes Disponibles
- investigador: Búsqueda RAG en Supabase
- arquitecto: Diseño de blueprints JSON
- programador: Generación de código + verificación
- tester: QA con pytest + análisis LLM
- auditor: Validación de calidad (DeepSeek Pro)

## Formato del Plan
{
  "plan": {
    "descripcion": "Resumen del plan",
    "complejidad_estimada": "low|medium|high|critical",
    "presupuesto_pro_estimado": 0.05,
    "pasos": [
      {
        "id": 1,
        "nombre": "Nombre del paso",
        "agente": "investigador|arquitecto|programador|tester|auditor",
        "descripcion": "Qué debe hacer",
        "input": "Qué recibe",
        "output_esperado": "Qué debe producir",
        "dependencias": [0],
        "complejidad": "low|medium|high",
        "modelo_sugerido": "flash|pro",
        "tiempo_estimado_seg": 30
      }
    ],
    "criterios_exito": ["criterio 1", "criterio 2"],
    "riesgos": [{"riesgo": "...", "mitigacion": "..."}]
  },
  "analisis_moa": {
    "minimalista": "camino más corto...",
    "robusto": "solución completa...",
    "arriesgado": "atajos creativos...",
    "plan_elegido": "por qué este balance"
  },
  "notas": ["nota 1", "nota 2"]
}"""


PERSPECTIVAS_MOA = {
    "MINIMALISTA": "Encuentra el camino MÁS CORTO para resolver esto. Mínimos pasos, mínimos agentes. ¿Qué es lo esencial? Prioriza velocidad sobre completitud.",
    "ROBUSTO": "Diseña la solución MÁS COMPLETA. Cubre todos los casos borde, todas las validaciones. ¿Qué haría un equipo senior con tiempo ilimitado?",
    "ARRIESGADO": "Propón el ENFOQUE MÁS CREATIVO. Atajos ingeniosos, arquitecturas no convencionales. ¿Qué harías si tuvieras que sorprender con la solución?",
}


async def _generar_perspectiva(requirement: str, context: str,
                                perspectiva: str, descripcion: str) -> dict:
    """Genera una perspectiva MoA del plan."""
    llm = get_llm(temperature=TEMPERATURE_CREATIVE, max_tokens=get_budget("architect"))
    
    prompt = f"""REQUERIMIENTO:
{requirement[:2000]}

CONTEXTO DE MEMORIA:
{context[:1500]}

PERSPECTIVA: {perspectiva}
{descripcion}

Genera un plan de ejecución desde esta perspectiva. 
Responde SOLO el JSON con la estructura de pasos (sin el análisis MoA completo, solo los pasos y criterios)."""

    try:
        response = await llm.ainvoke([
            SystemMessage(content=ESTRATEGA_SYSTEM_PROMPT),
            HumanMessage(content=prompt),
        ])
        content = response.content if hasattr(response, 'content') else str(response)
    except Exception as e:
        return {"pasos": [], "criterios_exito": [], "error": str(e)[:200]}

    try:
        content = content.strip()
        if content.startswith("```"):
            lines = content.split("\n")
            content = "\n".join(lines[1:-1])
        return json.loads(content)
    except json.JSONDecodeError:
        return {"pasos": [], "criterios_exito": [], "raw": content[:500]}


def _sintetizar_plan(perspectivas: dict, requirement: str) -> dict:
    """Sintetiza las 3 perspectivas MoA en un plan final balanceado."""
    
    # Extraer pasos de cada perspectiva
    all_steps = []
    for nombre, resultado in perspectivas.items():
        pasos = resultado.get("pasos", [])
        for paso in pasos:
            paso["_fuente"] = nombre
        all_steps.extend(pasos)
    
    # Priorizar pasos que aparecen en múltiples perspectivas
    paso_nombres = {}
    for paso in all_steps:
        nombre = paso.get("nombre", "")[:80]
        if nombre not in paso_nombres:
            paso_nombres[nombre] = {"count": 0, "pasos": []}
        paso_nombres[nombre]["count"] += 1
        paso_nombres[nombre]["pasos"].append(paso)
    
    # Pasos que aparecen en ≥2 perspectivas → incluirlos
    plan_pasos = []
    for nombre, info in sorted(paso_nombres.items(), key=lambda x: -x[1]["count"]):
        if info["count"] >= 2:
            best = max(info["pasos"], key=lambda p: len(str(p.get("descripcion", ""))))
            plan_pasos.append(best)
    
    # Limitar a 8 pasos máximo
    plan_pasos = plan_pasos[:8]
    
    # Re-numerar
    for i, paso in enumerate(plan_pasos):
        paso["id"] = i + 1
    
    # Criterios de éxito: unión de todas las perspectivas
    criterios = set()
    for nombre, resultado in perspectivas.items():
        for c in resultado.get("criterios_exito", []):
            criterios.add(c)
    
    complejidad = "medium"
    if len(plan_pasos) > 5:
        complejidad = "high"
    elif len(plan_pasos) <= 2:
        complejidad = "low"
    
    return {
        "descripcion": f"Plan sintetizado de {len(plan_pasos)} pasos (MoA: 3 perspectivas)",
        "complejidad_estimada": complejidad,
        "presupuesto_pro_estimado": round(len(plan_pasos) * 0.01, 2),
        "pasos": plan_pasos,
        "criterios_exito": list(criterios)[:5],
        "riesgos": [
            {"riesgo": "Complejidad subestimada", "mitigacion": "Re-planificar si ≥3 iteraciones sin avance"},
            {"riesgo": "Dependencia entre pasos bloquea el flujo", "mitigacion": "Ejecutar pasos independientes en paralelo"},
        ],
    }


async def planificar(requirement: str, context: str = "",
                     use_moa: bool = True) -> dict:
    """Genera un plan de ejecución multi-paso.
    
    Args:
        requirement: Requerimiento del usuario
        context: Contexto de memoria jerárquica (L1+L2+L3)
        use_moa: Si True, usa 3 perspectivas MoA y sintetiza
        
    Returns:
        {"plan": {...}, "analisis_moa": {...}, "notas": [...]}
    """
    print(f"[Estratega Agent] 🎯 Planificando: {requirement[:120]}...")
    t_start = time.time()
    
    # Comprimir requirement si es necesario
    if len(requirement) > 3000:
        requirement, juice = compress(requirement, max_tokens=2000)
        print(f"[Estratega] TokenJuice req: {juice['tokens_before']}→{juice['tokens_after']}")
    
    if len(context) > 2000:
        context, juice = compress(context, max_tokens=1000)
    
    if use_moa:
        # Generar 3 perspectivas en paralelo
        tareas = [
            _generar_perspectiva(requirement, context, nombre, desc)
            for nombre, desc in PERSPECTIVAS_MOA.items()
        ]
        resultados = await asyncio.gather(*tareas)
        
        perspectivas = {
            nombre: resultado
            for (nombre, _), resultado in zip(PERSPECTIVAS_MOA.items(), resultados)
        }
        
        # Sintetizar plan final
        plan = _sintetizar_plan(perspectivas, requirement)
        
        analisis_moa = {
            "minimalista": f"{len(perspectivas.get('MINIMALISTA', {}).get('pasos', []))} pasos — enfoque más directo",
            "robusto": f"{len(perspectivas.get('ROBUSTO', {}).get('pasos', []))} pasos — cobertura completa",
            "arriesgado": f"{len(perspectivas.get('ARRIESGADO', {}).get('pasos', []))} pasos — atajos creativos",
            "plan_elegido": f"Síntesis balanceada: {len(plan['pasos'])} pasos con consenso ≥2/3 perspectivas",
        }
    else:
        # Single-pass sin MoA
        llm = get_llm(temperature=TEMPERATURE_CREATIVE, max_tokens=get_budget("architect") * 2)
        prompt = f"""REQUERIMIENTO:
{requirement}

CONTEXTO:
{context}

Genera un plan de ejecución completo. Responde SOLO el JSON."""
        
        try:
            response = await llm.ainvoke([
                SystemMessage(content=ESTRATEGA_SYSTEM_PROMPT),
                HumanMessage(content=prompt),
            ])
            content = response.content if hasattr(response, 'content') else str(response)
            content = content.strip()
            if content.startswith("```"):
                lines = content.split("\n")
                content = "\n".join(lines[1:-1])
            result = json.loads(content)
            plan = result.get("plan", {})
            analisis_moa = result.get("analisis_moa", {})
        except (json.JSONDecodeError, Exception) as e:
            plan = {"descripcion": f"Error generando plan: {str(e)[:200]}", "pasos": []}
            analisis_moa = {}
    
    latency_ms = (time.time() - t_start) * 1000
    
    return {
        "plan": plan,
        "analisis_moa": analisis_moa,
        "notas": [
            f"Plan generado en {latency_ms:.0f}ms",
            f"Complejidad: {plan.get('complejidad_estimada', '?')}",
            f"Presupuesto pro estimado: ${plan.get('presupuesto_pro_estimado', 0):.2f}",
        ],
        "audit": {
            "action": "strategic_planning",
            "method": "MoA-3-perspectivas" if use_moa else "single-pass",
            "steps": len(plan.get("pasos", [])),
            "latency_ms": round(latency_ms),
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
        print(json.dumps({"error": "No input. Provide JSON with requirement and optional context."}))
        sys.exit(1)
    
    requirement = data.get("requirement", "")
    context = data.get("context", "")
    use_moa = data.get("use_moa", True)
    
    result = asyncio.run(planificar(requirement, context=context, use_moa=use_moa))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
