"""Nodo 3 — Arquitecto V3 con MoA Intelligence Amplifier (INTELIGENCIA x5).

MEJORA TURBO (Julio 2026):
   1. MoA ENSEMBLE: 3 arquitectos en paralelo con perspectivas diferentes
   2. MoA Aggregator (deepseek-v4-pro) fusiona/elige el mejor blueprint
   3. Gate 2 recibe ensemble completo para validación
   4. Modo eficiente: sin MoA si es tarea simple (baja complejidad)

ARQUITECTURA DEL MoA ENSEMBLE:
```
Proposer 1 (flash): MINIMALISTA → simple, pocos archivos
Proposer 2 (kimi):  ROBUSTO → modular, patrones, escalable
Proposer 3 (qwen):  TESTING-FIRST → testabilidad ante todo

Aggregator (deepseek-v4-pro): analiza los 3 y produce blueprint óptimo
                              o elige el mejor según el contexto
```
"""

import json
import asyncio
from langchain_core.messages import HumanMessage, SystemMessage
from src.state import TeamState
from src.config import get_llm, get_pro_llm, get_kimi_llm, get_deepseek_pro_llm, get_nemotron_llm, TEMPERATURE_CREATIVE, safe_invoke, get_budget, get_dynamic_limit, get_current_complexity
from src.moa_engine import MoAOrchestrator, MoAConfig, PROPOSER_REGISTRY


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
    """Genera un blueprint con un enfoque específico.
    
    Usa Nemotron 3 Ultra Free si el requerimiento es >30K caracteres
    (aprovecha su RULER 94.7 para contexto largo).
    """
    requirement = state.get("user_requirement", "")
    if len(requirement) > 30000:
        llm = get_nemotron_llm(temperature=TEMPERATURE_CREATIVE, max_tokens=get_budget("architect"))
        print(f"[Arquitecto] 🚀 Usando Nemotron (requerimiento: {len(requirement)} chars > 30K)")
    else:
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
    """Arquitecto V3 con MoA: 3 proposers en paralelo + aggregator Pro.
    
    ESTRATEGIA MoA:
      Para tareas medium/high: activa MoA completo (3 proposers + aggregator Pro)
      Para tareas low: usa single-pass ROBUSTO (ahorro de tokens)
    
    PROPOSERS:
      - flash (MINIMALISTA): solución simple y directa
      - kimi (ROBUSTO): modular, patrones, escalable  
      - qwen (TESTING-FIRST): diseñado para testabilidad
    
    AGGREGATOR:
      - deepseek-v4-pro: sintetiza/elige el mejor blueprint
    """
    complexity = get_current_complexity()
    
    # Decidir si usar MoA completo o single-pass
    usar_moa = complexity in ("medium", "high")
    
    if not usar_moa:
        # Modo eficiente: single-pass ROBUSTO (tareas simples)
        print(f"[Arquitecto v3] 📐 Tarea simple ({complexity}) — single-pass ROBUSTO")
        enfoque = (
            "ROBUSTO", 
            "Solución completa y modular. Separación de concerns, patrones de diseño. "
            "Código mantenible y extensible."
        )
        resultado = await _generar_blueprint(state, enfoque[1], enfoque[0])
        
        blueprint_final = resultado.get("blueprint", {})
        notas = resultado.get("notas", [])
        
        if not resultado.get("valido"):
            enfoque_min = ("MINIMALISTA", "Solución simple y directa.")
            resultado2 = await _generar_blueprint(state, enfoque_min[1], enfoque_min[0])
            blueprint_final = resultado2.get("blueprint", {})
            notas = resultado2.get("notas", [])
        
        return {
            "architecture_blueprint": blueprint_final,
            "scratchpad": notas,
            "audit_trail": [{
                "nodo": "Arquitecto v3 (single-pass)",
                "accion": "1 blueprint ROBUSTO (sin MoA)",
                "resultado": f"{len(blueprint_final.get('archivos', {}))} archivos",
            }],
            "ensemble_blueprints": [],
        }
    
    # ── MoA completo para tareas medium/high ──
    print(f"[Arquitecto v3] 🧠 MoA ACTIVADO ({complexity}) — 3 blueprints en paralelo + aggregator Pro")
    
    # Generar 3 blueprints con diferentes enfoques en paralelo
    enfoques = [
        ("MINIMALISTA", "Solución simple y directa. Pocos archivos, funciones compactas. Enfoque práctico."),
        ("ROBUSTO", "Solución completa y modular. Separación de concerns, patrones de diseño. Código mantenible."),
        ("TESTING-FIRST", "Diseñado para testabilidad. Mockeable, inyección de dependencias,边界 casos."),
    ]
    
    tasks = [
        _generar_blueprint(state, enfoque[1], enfoque[0])
        for enfoque in enfoques
    ]
    
    blueprints = await asyncio.gather(*tasks)
    validos = [b for b in blueprints if b.get("valido")]
    
    # Extraer blueprints para ensemble
    ensemble = []
    for b in validos:
        bp = b.get("blueprint", {})
        if bp and bp.get("archivos"):
            ensemble.append({
                "nombre": b.get("nombre", "?"),
                "enfoque": b.get("enfoque", "")[:50],
                "archivos": list(bp.get("archivos", {}).keys())[:8],
                "num_archivos": len(bp.get("archivos", {})),
                "decisiones": bp.get("decisiones_tecnicas", [])[:3],
                "descripcion": bp.get("descripcion_general", "")[:200],
                "puntaje_auto": b.get("puntaje", {}),
            })
    
    print(f"[Arquitecto v3] 📐 {len(validos)}/{len(enfoques)} blueprints generados")
    
    # Elegir el mejor blueprint usando hard criteria + MoA si hay más de 1 válido
    if len(validos) == 1:
        mejor = validos[0]
        blueprint_final = mejor.get("blueprint", {})
        notas = mejor.get("notas", [])
        print(f"[Arquitecto v3] 🏆 Único blueprint válido: {mejor['nombre']}")
        
    elif len(validos) >= 2:
        # Usar MoA Aggregator (deepseek-v4-pro) para elegir el mejor
        print(f"[Arquitecto v3] 🔬 MoA Aggregator eligiendo mejor blueprint...")
        
        # Preparar resumen de cada blueprint para el aggregator
        resumenes = []
        for b in validos:
            bp = b.get("blueprint", {})
            archivos = bp.get("archivos", {})
            resumen = f"""{b['nombre']} ({b['enfoque'][:80]}):
  Archivos ({len(archivos)}): {', '.join(archivos.keys())[:200]}
  Descripción: {bp.get('descripcion_general', '')[:200]}
  Decisiones técnicas: {chr(10).join(f'  - {d}' for d in bp.get('decisiones_tecnicas', [])[:3])}
  Auto-puntaje: {json.dumps(b.get('puntaje', {}))}"""
            resumenes.append(resumen)
        
        # Llamar al aggregator Pro para que elija
        aggregator_llm = get_deepseek_pro_llm(temperature=0.15, max_tokens=1024)
        aggregator_prompt = f"""Eres un arquitecto senior evaluando 3 propuestas de arquitectura.
Debes elegir la MEJOR basado en completitud, claridad, y testabilidad.

Responde SOLO JSON:
{{
    "mejor_blueprint": 0|1|2,
    "justificacion": "por qué este es el mejor",
    "confianza": 0.0-1.0,
    "fusion_sugerida": "elementos de otros blueprints que deberían incorporarse"
}}

Propuestas:
{chr(10).join(f'--- #{i} ---{chr(10)}{r}' for i, r in enumerate(resumenes))}"""
        
        response = await safe_invoke(aggregator_llm, [
            SystemMessage(content="Eres un evaluador de arquitecturas. Responde SOLO JSON."),
            HumanMessage(content=aggregator_prompt),
        ])
        
        content = response.content if hasattr(response, 'content') else str(response)
        
        try:
            content_clean = content.strip()
            if content_clean.startswith("```"):
                lines = content_clean.split("\n")
                content_clean = "\n".join(lines[1:-1])
            decision = json.loads(content_clean)
            
            mejor_idx = decision.get("mejor_blueprint", 0)
            if 0 <= mejor_idx < len(validos):
                mejor = validos[mejor_idx]
                blueprint_final = mejor.get("blueprint", {})
                notas = mejor.get("notas", [])
                print(f"[Arquitecto v3] 🏆 MoA Aggregator eligió: {mejor['nombre']} "
                      f"(confianza: {decision.get('confianza', '?')})")
                notas.append(f"[MoA Aggregator] Elegido: {mejor['nombre']} — {decision.get('justificacion', '')[:200]}")
                
                # Si hay sugerencia de fusión, agregarla como nota
                fusion = decision.get("fusion_sugerida", "")
                if fusion:
                    notas.append(f"[MoA Aggregator] Fusión sugerida: {fusion[:200]}")
            else:
                raise ValueError(f"Índice inválido: {mejor_idx}")
        except (json.JSONDecodeError, ValueError) as e:
            print(f"[Arquitecto v3] ⚠️ Aggregator falló ({e}), usando score auto-reportado")
            # Fallback: el de mayor puntaje auto-reportado
            def get_score(b):
                p = b.get("puntaje", {})
                return p.get("completitud", 0) + p.get("claridad", 0) + p.get("testabilidad", 0)
            mejor = max(validos, key=get_score)
            blueprint_final = mejor.get("blueprint", {})
            notas = mejor.get("notas", [])
            print(f"[Arquitecto v3] 🏆 Fallback a mejor score: {mejor['nombre']} (score {get_score(mejor)})")
    else:
        # Sin blueprints válidos
        blueprint_final = {"descripcion_general": "Fallback - sin blueprint válido", "archivos": {}}
        notas = ["[MoA] Ningún blueprint válido — usando fallback vacío"]
    
    num_files = len(blueprint_final.get("archivos", {}))
    print(f"[Arquitecto v3] 🏆 MoA completado: {num_files} archivos | "
          f"ensemble={len(ensemble)} variantes")
    
    audit = [{
        "nodo": "Arquitecto v3 (MoA)",
        "accion": f"MoA ensemble: {len(validos)} proposers + aggregator Pro",
        "resultado": f"{num_files} archivos, ensemble={len(ensemble)} variantes",
    }]
    
    return {
        "architecture_blueprint": blueprint_final,
        "scratchpad": notas + [
            f"[MoA Arquitecto] {len(proposer_responses)} proposers, confianza={confidence:.2f}",
            f"[MoA Arquitecto] Ensemble: {len(ensemble)} variantes de blueprint",
        ],
        "audit_trail": audit,
        "ensemble_blueprints": ensemble,
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
