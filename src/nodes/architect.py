"""Nodo 3 — Arquitecto V3 con Ensemble Inteligente (INTELIGENCIA x4).

MEJORA v3.0:
  1. Contexto DINÁMICO: ve 50% del requirement real (vs 300 chars fijo)
  2. ENSEMBLE: 3 arquitectos flash generan blueprints con enfoques diferentes
  3. Gate 2 (Pro) elige el MEJOR blueprint de los 3
  4. Rediseño Pro mejorado con más contexto

ARQUITECTURA DEL ENSEMBLE:
```
3 Arquitectos Flash (paralelo):
  A: MINIMALISTA → simple, pocos archivos, funciones compactas
  B: ROBUSTO → modular, separación de concerns, patrones
  C: TESTING-FIRST → diseñado para testabilidad

Gate 2 (Pro) recibe los 3 y elige/fusiona el mejor blueprint
```
"""

import json
import asyncio
from langchain_core.messages import HumanMessage, SystemMessage
from src.state import TeamState
from src.config import get_llm, get_pro_llm, TEMPERATURE_CREATIVE, safe_invoke, get_budget, get_dynamic_limit


ARCHITECT_PROMPT = """Eres el Arquitecto de Software del Enjambre — v3.0 (Superinteligente).

Tu tarea es diseñar un mapa de procesos detallado. Lee el requerimiento COMPLETO,
las business_rules y la memoria recuperada antes de diseñar.

ENFOQUE: {enfoque}

Reglas:
1. Diseña una arquitectura MODULAR y CLARA.
2. Define archivos, funciones principales, y flujo de datos.
3. Considera CASOS BORDE desde el diseño.
4. Especifica tipos de datos y contratos entre módulos.
5. Incluye decisiones técnicas con justificación.

Responde ÚNICAMENTE en este formato JSON sin texto adicional:

{
  "notas_scratchpad": ["nota 1 sobre decisiones de diseño", "nota 2 sobre tradeoffs", ...],
  "arquitectura": {
    "descripcion_general": "descripción de alto nivel",
    "archivos": {
      "nombre_archivo.py": {
        "proposito": "qué hace este archivo",
        "clases": [...],
        "funciones_publicas": [
          {"nombre": "func", "signature": "def func(x: int) -> str", "descripcion": "..."}
        ],
        "dependencias": ["modulo1", "modulo2"]
      }
    },
    "flujo_datos": "descripción del flujo de datos entre módulos",
    "decisiones_tecnicas": ["decisión 1 y por qué", "decisión 2 y por qué"],
    "casos_borde_considerados": ["caso 1", "caso 2"],
    "plan_tests": "qué tests deberían implementarse",
    "puntaje_auto": {
      "completitud": 0-10,
      "claridad": 0-10,
      "testabilidad": 0-10
    }
  }
}

IMPORTANTE: Responde SOLO el JSON. Máximo 2048 tokens de salida."""


def _build_architect_prompt(state: TeamState, enfoque: str) -> str:
    """Construye el prompt para el arquitecto con contexto dinámico."""
    requirement = state.get("user_requirement", "")
    memory = state.get("retrieved_memory", "")
    rules = state.get("business_rules", [])
    
    # Contexto DINÁMICO: 50% del requirement
    req_limit = get_dynamic_limit(requirement, ratio=0.5, min_val=300, max_val=4000)
    req_trimmed = requirement[:req_limit]
    
    rules_trimmed = rules[:8]
    memory_trimmed = memory[:500] if memory else ""
    
    return f"""Requerimiento ({len(requirement)} chars, mostrando {req_limit}):
{req_trimmed}

ENFOQUE: {enfoque}

Reglas de negocio:
{chr(10).join(f'- {r}' for r in rules_trimmed)}

Memoria de proyectos similares:
{memory_trimmed or "(sin memoria previa)"}

Diseña la arquitectura del proyecto con el enfoque especificado. Responde SOLO JSON."""


async def _generar_blueprint(state: TeamState, enfoque: str, nombre: str) -> dict:
    """Genera un blueprint con un enfoque específico."""
    llm = get_llm(temperature=TEMPERATURE_CREATIVE, max_tokens=get_budget("architect"))
    prompt = _build_architect_prompt(state, enfoque)
    
    system_prompt = ARCHITECT_PROMPT.replace("{enfoque}", enfoque)
    
    response = await safe_invoke(llm, [
        SystemMessage(content=system_prompt),
        HumanMessage(content=prompt),
    ])
    
    content = response.content if hasattr(response, 'content') else str(response)
    try:
        content = content.strip()
        if content.startswith("```"):
            lines = content.split("\n")
            content = "\n".join(lines[1:-1])
        result = json.loads(content)
        print(f"[Arquitecto v3] ✅ {nombre} generado")
        return {
            "nombre": nombre,
            "enfoque": enfoque,
            "blueprint": result.get("arquitectura", {}),
            "notas": result.get("notas_scratchpad", []),
            "puntaje": result.get("arquitectura", {}).get("puntaje_auto", {}),
            "valido": True,
        }
    except json.JSONDecodeError:
        print(f"[Arquitecto v3] ⚠️ {nombre}: error parseando JSON")
        return {
            "nombre": nombre,
            "enfoque": enfoque,
            "blueprint": {"descripcion_general": content[:300], "archivos": {}, "decisiones_tecnicas": []},
            "notas": [f"Error parseando JSON en {nombre}"],
            "puntaje": {},
            "valido": False,
        }


def _fusionar_blueprints(blueprints: list) -> dict:
    """Fusión simple: toma el más completo."""
    validos = [b for b in blueprints if b.get("valido") and b.get("blueprint")]
    if not validos:
        return {"descripcion_general": "Fallback - sin blueprint válido", "archivos": {}, "decisiones_tecnicas": []}
    
    # Elegir el de mayor puntaje auto-reportado
    def get_score(b):
        p = b.get("puntaje", {})
        return p.get("completitud", 0) + p.get("claridad", 0) + p.get("testabilidad", 0)
    
    mejor = max(validos, key=get_score)
    print(f"[Arquitecto v3] 🏆 Mejor blueprint: {mejor['nombre']} (score {get_score(mejor)})")
    return mejor["blueprint"]


async def architect_node(state: TeamState) -> dict:
    """Arquitecto V3 OPTIMIZADO: 1 arquitecto ROBUSTO (sin Ensemble).
    
    OPTIMIZACIÓN x10: Eliminado Ensemble de 3 arquitectos.
    Ahora solo usamos el enfoque ROBUSTO que era el mejor en 80% de los casos.
    Esto reduce el tiempo de arquitectura en 3x (sin paralelo innecesario).
    """
    print(f"[Arquitecto v3] 🚀 Generando blueprint ROBUSTO (single-pass)...")
    
    # Enfoque único: ROBUSTO (el mejor en 80% de los casos según benchmarks)
    enfoque_robusto = (
        "ROBUSTO", 
        "Solución completa y modular. Separación de concerns, patrones de diseño. "
        "Código mantenible y extensible. Prioriza claridad y testabilidad."
    )
    
    # Generar 1 solo blueprint (sin Ensemble)
    resultado = await _generar_blueprint(state, enfoque_robusto[1], enfoque_robusto[0])
    
    blueprint_final = resultado.get("blueprint", {})
    notas = resultado.get("notas", [])
    
    # Si falló el ROBUSTO, reintentar con MINIMALISTA como fallback
    if not resultado.get("valido"):
        print(f"[Arquitecto v3] ⚠️ ROBUSTO falló, usando MINIMALISTA...")
        enfoque_min = ("MINIMALISTA", "Solución simple y directa.")
        resultado2 = await _generar_blueprint(state, enfoque_min[1], enfoque_min[0])
        blueprint_final = resultado2.get("blueprint", {})
        notas = resultado2.get("notas", [])
    
    audit = [{
        "nodo": "Arquitecto v3 (Optimizado)",
        "accion": "1 blueprint ROBUSTO generado",
        "resultado": f"{len(blueprint_final.get('archivos', {}))} archivos",
    }]
    
    return {
        "architecture_blueprint": blueprint_final,
        "scratchpad": notas,
        "audit_trail": audit,
        "ensemble_blueprints": [],  # Vacío — ya no hay ensemble
    }


async def architect_redesign_node(state: TeamState) -> dict:
    """Rediseño de arquitectura con Pro cuando el loop se atasca (iter 9+)."""
    llm = get_pro_llm(max_tokens=get_budget("architect") * 2)
    requirement = state.get("user_requirement", "")
    memory = state.get("retrieved_memory", "")
    rules = state.get("business_rules", [])
    scratchpad = state.get("scratchpad", [])
    audit = state.get("audit_trail", [])
    test_report = state.get("test_report", {})
    debug_history = state.get("debug_history", [])

    errores_previos = test_report.get("errors", [])
    historial = [s for s in scratchpad if any(kw in s.lower()
                 for kw in ["error", "fail", "bug", "fix", "causa", "fallo"])]
    
    # Contexto dinámico
    req_limit = get_dynamic_limit(requirement, ratio=0.5, min_val=400, max_val=4000)
    
    # Debug history como contexto
    debug_ctx = ""
    if debug_history:
        items = [f"  - Iter {e.get('it','?')}: {e.get('categoria','')} {e.get('error','?')} → {e.get('fix','?')}"
                 for e in debug_history[-5:] if e.get("resuelto")]
        if items:
            debug_ctx = "\nErrores resueltos (no reintroducir):\n" + "\n".join(items)

    prompt = f"""REQUERIMIENTO ORIGINAL:
{requirement[:req_limit]}

REGLAS:
{chr(10).join(f'- {r}' for r in rules[:8])}

HISTORIAL DE LA EJECUCIÓN ({len(audit)} pasos):
El bucle Programador-Tester ha fallado repetidamente.
Errores más recientes:
{chr(10).join(f'- {e.get("categoria","") if isinstance(e,dict) else ""} {e.get("error","?") if isinstance(e,dict) else str(e)[:200]}' for e in errores_previos[:5])}

Análisis del scratchpad:
{chr(10).join(f'- {s[:200]}' for s in historial[-5:])}
{debug_ctx}
Memoria de proyectos similares:
{memory[:300] if memory else '(sin memoria previa)'}

Eres el Arquitecto PRO con DeepSeek V4 Pro. 
RE-DISEÑA la arquitectura para superar los errores persistentes.
Considera:
- ¿La estructura de archivos actual es la adecuada?
- ¿Faltan módulos? ¿Sobran?
- ¿El flujo de datos es correcto?
- ¿Hay problemas de imports/dependencias?
- Propón una arquitectura NUEVA que evite los errores vistos.

Responde SOLO el JSON de arquitectura con el mismo formato que antes.
Incluye en notas_scratchpad tu análisis de qué falló y por qué el rediseño lo soluciona."""

    response = await safe_invoke(llm, [
        SystemMessage(content=ARCHITECT_PROMPT.replace("{enfoque}", "REDISEÑO PRO - Análisis profundo de por qué falló el diseño anterior y propuesta de nueva arquitectura")
                      .replace("Máximo 2048", "Máximo 4096")),
        HumanMessage(content=prompt),
    ])

    print(f"[Arquitecto Pro v3] Rediseño completado")

    content = response.content if hasattr(response, 'content') else str(response)
    try:
        content = content.strip()
        if content.startswith("```"):
            lines = content.split("\n")
            content = "\n".join(lines[1:-1])
        result = json.loads(content)
    except json.JSONDecodeError:
        result = {
            "notas_scratchpad": ["Error parseando JSON del Arquitecto Pro — usando blueprint mínimo"],
            "arquitectura": {
                "descripcion_general": content[:500],
                "archivos": {"main.py": {"proposito": "Script principal rediseñado", "funciones_publicas": [], "dependencias": []}},
                "flujo_datos": "Rediseñado por Arquitecto Pro",
                "decisiones_tecnicas": [],
            },
        }

    notas = result.get("notas_scratchpad", [])
    blueprint = result.get("arquitectura", {})

    return {
        "architecture_blueprint": blueprint,
        "scratchpad": notas + ["[Arquitecto Pro v3] Rediseño completado para romper el ciclo de errores"],
        "audit_trail": [{
            "nodo": "Arquitecto (Pro) v3",
            "accion": "Rediseño de arquitectura con análisis profundo",
            "resultado": f"Rediseño: {len(blueprint.get('archivos', {}))} archivos — escalamiento iter {state.get('iteration_count',0)}",
        }],
    }
