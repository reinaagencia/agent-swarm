"""Nodo 2 — Orquestador (Manager/Router) v3.0 — INTELIGENCIA x4.
Analiza el requerimiento con contexto DINÁMICO (sin truncar a 300 fijo),
produce análisis estructurado PROFUNDO para el Auditor Gate 1,
y genera 2 variantes de plan en paralelo para mejor toma de decisiones.

MEJORA v3.0:
  - Contexto DINÁMICO: 60% del requirement real (vs 300 chars fijo)
  - Resumen_para_auditor ENRIQUECIDO: árbol de decisiones + dependencias + plan de pruebas
  - 2 variantes de plan en paralelo: enfoque minimalista vs robusto
  - Gate 0 ready: produce plan_maestro si Meta-Planner está activo
"""

import json
import asyncio
from langchain_core.messages import HumanMessage, SystemMessage
from src.state import TeamState
from src.config import (
    get_llm, TEMPERATURE_CREATIVE, safe_invoke, get_budget,
    detect_complexity, set_complexity, get_current_complexity,
    get_dynamic_limit, get_dynamic_memory_limit
)


ORCHESTRATOR_PROMPT = """Eres el Orquestador del Enjambre de Desarrollo — v3.0 (Superinteligente).

Tu tarea es analizar el requerimiento COMPLETO del usuario y la memoria recuperada.
Debes producir un análisis ESTRUCTURADO y PROFUNDO que el Auditor Gate 1 (DeepSeek V4 Pro)
consumirá para decidir la viabilidad del proyecto.

ANÁLISIS REQUERIDO:
1. ¿El requerimiento es claro y accionable? Si no, explica qué falta.
2. Restricciones técnicas y de negocio (business_rules) DETALLADAS.
3. Alcance del proyecto: qué incluye y qué NO incluye EXPLÍCITAMENTE.
4. Tecnologías sugeridas con justificación breve.
5. Árbol de decisiones: las decisiones técnicas clave que hay que tomar.
6. Dependencias externas: librerías, APIs, servicios que se necesitarán.
7. Plan de pruebas sugerido: qué tipo de tests aplicar.
8. Glosario de términos técnicos del dominio (si aplica).
9. Estimación de esfuerzo: archivos, funciones, complejidad.

IMPORTANTE: Sé específico y realista. El Gate 1 validará tu análisis.

Responde ÚNICAMENTE en este formato JSON sin texto adicional:

{
  "viable": true/false,
  "razon": "explicación detallada si no es viable",
  "business_rules": ["regla 1", "regla 2", ...],
  "alcance": "descripción del alcance (máx 300 chars)",
  "tecnologias_sugeridas": [
    {"tecnologia": "flask", "justificacion": "...", "alternativa": "fastapi"}
  ],
  "arbol_decisiones": [
    {"decision": "¿BD relacional o NoSQL?", "opciones": ["SQLite (simple)", "PostgreSQL (escalable)"], "recomendacion": "SQLite"}
  ],
  "dependencias_externas": ["librería X para Y", ...],
  "plan_pruebas": "unitarias con pytest, integración con ...",
  "glosario": [{"termino": "...", "definicion": "..."}],
  "estimacion": {
    "archivos": 5,
    "funciones_principales": 10,
    "complejidad": "baja|media|alta",
    "horas_estimadas_desarrollo": "2-4h"
  },
  "resumen_para_auditor": {
    "que_hace": "qué hace el sistema en 1 línea (máx 100 chars)",
    "complejidad": "baja|media|alta",
    "archivos_estimados": 5,
    "riesgos_identificados": ["riesgo 1 con impacto: ..."],
    "puntos_clave": ["punto 1", ...],
    "decisiones_criticas": ["decisión 1", ...],
    "recomendacion_router": {
      "pro_initial": false,
      "ensemble_architect": false,
      "max_pro_calls_suggested": 2,
      "context_priority": "medium"
    }
  }
}

IMPORTANTE: Responde SOLO el JSON sin texto adicional. Máximo 1024 tokens de salida."""


async def _generar_variante(state: TeamState, requirement: str, memory: str,
                             rules_inyectadas: list, enfoque: str) -> dict:
    """Genera una variante de plan con un enfoque específico."""
    llm = get_llm(temperature=0.4, max_tokens=get_budget("orchestrator"))
    
    context_rules = ""
    if rules_inyectadas:
        context_rules = "Reglas inyectadas:\n" + "\n".join(f"- {r}" for r in rules_inyectadas[:8])

    prompt = f"""Requerimiento COMPLETO ({len(requirement)} chars):
{requirement}

{context_rules}

Memoria de proyectos similares:
{memory if memory else "(sin memoria previa)"}

ENFOQUE: {enfoque}

Analiza el requerimiento COMPLETO y produce el JSON de decisión con resumen_para_auditor incluido.
Incluye todas las secciones del formato solicitado."""

    response = await safe_invoke(llm, [
        SystemMessage(content=ORCHESTRATOR_PROMPT),
        HumanMessage(content=prompt),
    ])
    
    content = response.content if hasattr(response, 'content') else str(response)
    try:
        content = content.strip()
        if content.startswith("```"):
            lines = content.split("\n")
            content = "\n".join(lines[1:-1])
        return json.loads(content)
    except json.JSONDecodeError:
        return None


async def orchestrator_node(state: TeamState) -> dict:
    """Analiza el requerimiento con contexto DINÁMICO y produce análisis estructurado."""
    requirement = state.get("user_requirement", "")
    memory = state.get("retrieved_memory", "")

    # Detectar y establecer complejidad
    complexity = detect_complexity(requirement)
    set_complexity(complexity)
    
    # CONTEXTO DINÁMICO: 60% del requirement real (en vez de 300 fijo)
    req_limit = get_dynamic_limit(requirement, ratio=0.6, min_val=300, max_val=4000)
    req_trimmed = requirement[:req_limit]
    mem_trimmed = memory[:get_dynamic_memory_limit(memory)] if memory else ""
    
    rules_inyectadas = state.get("injected_skills", {}).get("rules", [])
    rules_context = ""
    if rules_inyectadas:
        rules_context = "Reglas inyectadas:\n" + "\n".join(f"- {r}" for r in rules_inyectadas[:8])

    # --- GENERAR 2 VARIANTES EN PARALELO (v3.0) ---
    print(f"[Orquestador v3] Contexto dinámico: {req_limit} chars de {len(requirement)}")
    print(f"[Orquestador v3] Generando 2 variantes en paralelo...")
    
    variante_a = asyncio.create_task(
        _generar_variante(state, req_trimmed, mem_trimmed, rules_inyectadas, 
                          "MINIMALISTA: solución simple, pocos archivos, funciones directas")
    )
    variante_b = asyncio.create_task(
        _generar_variante(state, req_trimmed, mem_trimmed, rules_inyectadas,
                          "ROBUSTA: solución completa, modular, con tests, logging y manejo de errores")
    )
    
    resultado_a, resultado_b = await asyncio.gather(variante_a, variante_b)
    
    # Elegir la mejor variante (la más completa)
    if resultado_a and resultado_b:
        # Puntuar: gana la que tenga más secciones completas
        def puntuar(r):
            score = 0
            if r.get("resumen_para_auditor"): score += 3
            if r.get("arbol_decisiones"): score += 2
            if r.get("dependencias_externas"): score += 1
            if r.get("plan_pruebas"): score += 1
            if r.get("glosario"): score += 1
            if r.get("estimacion"): score += 1
            if r.get("business_rules"): score += len(r["business_rules"])
            return score
        
        score_a, score_b = puntuar(resultado_a), puntuar(resultado_b)
        result = resultado_a if score_a >= score_b else resultado_b
        print(f"[Orquestador v3] ✅ Variante elegida: {'A (minimalista)' if score_a >= score_b else 'B (robusta)'} (score {max(score_a, score_b)} vs {min(score_a, score_b)})")
    elif resultado_a:
        result = resultado_a
    elif resultado_b:
        result = resultado_b
    else:
        result = {}
        print(f"[Orquestador v3] ⚠️ Ambas variantes fallaron, usando fallback")

    print(f"[Orquestador v3] Requerimiento analizado ({complexity}) — {len(requirement)} chars vistos")

    return _process_orchestrator_response(result, state, complexity)


def _process_orchestrator_response(result: dict, state: TeamState, complexity: str) -> dict:
    """Procesa la respuesta del LLM y extrae el análisis estructurado."""
    requirement = state.get("user_requirement", "")

    if not result:
        result = {
            "viable": True,
            "razon": "Requerimiento parseado con fallback",
            "business_rules": [],
            "alcance": "A determinar",
            "tecnologias_sugeridas": [],
            "resumen_para_auditor": {
                "que_hace": requirement[:100],
                "complejidad": complexity,
                "archivos_estimados": 3,
                "riesgos_identificados": ["Falta de información detallada"],
                "puntos_clave": ["Requerimiento genérico"],
                "decisiones_criticas": [],
                "recomendacion_router": {"pro_initial": False}
            },
        }

    viable = result.get("viable", True)
    rules = result.get("business_rules", [])
    alcance = result.get("alcance", "")
    tecnologias = result.get("tecnologias_sugeridas", [])
    resumen = result.get("resumen_para_auditor", {})

    # Guardar resumen_para_auditor + análisis completo en scratchpad como JSON
    analisis_completo = {
        "alcance": alcance,
        "tecnologias": tecnologias,
        "arbol_decisiones": result.get("arbol_decisiones", []),
        "dependencias_externas": result.get("dependencias_externas", []),
        "plan_pruebas": result.get("plan_pruebas", ""),
        "glosario": result.get("glosario", []),
        "estimacion": result.get("estimacion", {}),
        "resumen_para_auditor": resumen,
        "recomendacion_router": resumen.get("recomendacion_router", {}),
    }
    analisis_json = json.dumps(analisis_completo, ensure_ascii=False)
    
    # Combinar reglas
    existing_rules = state.get("business_rules", [])
    all_rules = list(set(existing_rules + rules))

    return {
        "business_rules": all_rules,
        "scratchpad": [
            f"Alcance: {alcance}",
            f"Tecnologías: {', '.join(t if isinstance(t, str) else t.get('tecnologia', '?') for t in tecnologias)}",
            f"Análisis completo orquestador: {analisis_json}",
        ],
        "audit_trail": [{
            "nodo": "Orquestador v3",
            "accion": "Análisis profundo del requerimiento (2 variantes)",
            "resultado": f"Viable: {viable} | Reglas: {len(rules)} | Complejidad: {complexity}",
        }],
    }

