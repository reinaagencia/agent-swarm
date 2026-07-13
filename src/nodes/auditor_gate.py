"""Nodos del Auditor v3.0 — DeepSeek V4 Pro con contexto enriquecido.

MEJORA v3.0 (INTELIGENCIA x4):
  - Gate 1 y 2 reciben contexto del Meta-Planner (cuando existe)
  - Gate 1 recibe análisis completo del Orquestador (no solo 150 chars)
  - Gate 2 recibe los 3 blueprints del ensemble (no solo 1)
  - Gate 3 recibe errores CLASIFICADOS por categoría
  - System prompt mantiene cache hit (estático)
"""

import json
from langchain_core.messages import HumanMessage, SystemMessage
from src.state import TeamState
from src.config import get_pro_llm, AUDITOR_TEMPERATURE, safe_invoke, TOKEN_BUDGET_AUDITOR_G1, TOKEN_BUDGET_AUDITOR_G2, TOKEN_BUDGET_AUDITOR_G3, get_dynamic_limit

# ═══════════════════════════════════════════════════════════════
# System prompt del auditor — 100% ESTÁTICO para máximo cache hit
# ═══════════════════════════════════════════════════════════════
AUDITOR_SYSTEM = """Eres el Auditor del Enjambre v3.0. Validas decisiones críticas.
Reglas:
- Responde ÚNICAMENTE en JSON válido. Sin texto adicional, sin markdown, sin ```.
- No repitas el input que ya conoces.
- Máximo 300 tokens de salida.
- Incluye siempre confidence (0.0-1.0)."""


def _buscar_analisis_en_scratchpad(state: TeamState, prefix: str) -> dict:
    """Busca un análisis JSON en el scratchpad."""
    scratchpad = state.get("scratchpad", [])
    for entry in scratchpad:
        if prefix in entry:
            try:
                json_str = entry.split(prefix, 1)[1]
                return json.loads(json_str)
            except (json.JSONDecodeError, IndexError):
                pass
    return {}


def _depure_orchestrator_output(state: TeamState) -> str:
    """Prepara contexto ENRIQUECIDO para Gate 1 con Meta-Planner + Orquestador."""
    rules = state.get("business_rules", [])
    requirement = state.get("user_requirement", "")
    meta_plan = state.get("meta_plan", {})
    
    # Buscar análisis completo del orquestador v3
    analisis = _buscar_analisis_en_scratchpad(state, "Análisis completo orquestador: ")
    resumen = analisis.get("resumen_para_auditor", {}) if analisis else {}
    
    # Meta-Planner context
    meta_ctx = {}
    if meta_plan:
        meta_ctx = {
            "dominio": meta_plan.get("dominio", ""),
            "complejidad_estimada": meta_plan.get("complejidad_estimada", ""),
            "riesgos_criticos": meta_plan.get("riesgos_criticos", []),
            "hints": meta_plan.get("hints_para_orquestador", []),
        }
    
    context = {
        "gate": "viability_check",
        "meta_planner": meta_ctx,
        "analisis_orquestador": {
            "que_hace": resumen.get("que_hace", requirement[:100]),
            "complejidad": resumen.get("complejidad", "media"),
            "archivos_estimados": resumen.get("archivos_estimados", 3),
            "riesgos": resumen.get("riesgos_identificados", []),
            "puntos_clave": resumen.get("puntos_clave", []),
            "decisiones_criticas": resumen.get("decisiones_criticas", []),
        },
        "reglas_negocio": rules[:8],
        "requirement_preview": requirement[:400],
        "tecnologias_sugeridas": analisis.get("tecnologias", []) if analisis else [],
        "dependencias_externas": analisis.get("dependencias_externas", []) if analisis else [],
    }
    
    return json.dumps(context, ensure_ascii=False)


def _depure_architect_output(state: TeamState) -> str:
    """Prepara contexto ENRIQUECIDO para Gate 2 con ensemble de blueprints."""
    blueprint = state.get("architecture_blueprint", {})
    rules = state.get("business_rules", [])
    meta_plan = state.get("meta_plan", {})
    ensemble = state.get("ensemble_blueprints", [])
    analisis = _buscar_analisis_en_scratchpad(state, "Análisis completo orquestador: ")

    files = blueprint.get("archivos", {})
    file_summary = {k: {"proposito": v.get("proposito", "")[:100]} for k, v in list(files.items())[:8]}
    
    # Si hay ensemble, incluir resumen de cada blueprint
    ensemble_summary = []
    for i, bp in enumerate(ensemble):
        bp_files = bp.get("archivos", {})
        ensemble_summary.append({
            "id": i + 1,
            "descripcion": bp.get("descripcion_general", "")[:100],
            "archivos": list(bp_files.keys())[:5],
            "num_archivos": len(bp_files),
            "decisiones": bp.get("decisiones_tecnicas", [])[:2],
        })
    
    context = {
        "gate": "architecture_review",
        "meta_planner_hints": {
            "enfoque": meta_plan.get("enfoque_recomendado", {}) if meta_plan else {},
            "hints_arquitecto": meta_plan.get("hints_para_arquitecto", []) if meta_plan else [],
        } if meta_plan else {},
        "blueprint_principal": {
            "description": blueprint.get("descripcion_general", "")[:200],
            "files": file_summary,
            "tech_decisions": blueprint.get("decisiones_tecnicas", [])[:5],
            "flujo": blueprint.get("flujo_datos", "")[:200],
            "casos_borde": blueprint.get("casos_borde_considerados", []),
            "plan_tests": blueprint.get("plan_tests", ""),
        },
        "ensemble_blueprints": ensemble_summary if ensemble else [],
        "rules": rules[:5],
        "glosario": analisis.get("glosario", []) if analisis else [],
    }
    
    return json.dumps(context, ensure_ascii=False)


def _depure_stuck_loop(state: TeamState) -> str:
    """Prepara contexto ENRIQUECIDO para Gate 3 con errores CLASIFICADOS."""
    test_report = state.get("test_report", {})
    scratchpad = state.get("scratchpad", [])
    iteration = state.get("iteration_count", 0)
    debug_history = state.get("debug_history", [])
    meta_plan = state.get("meta_plan", {})

    errors = test_report.get("errors", [])
    debug_history = state.get("debug_history", [])
    
    # Clasificar errores por categoría
    por_categoria = {}
    for e in errors:
        if isinstance(e, dict):
            cat = e.get("categoria", "[?]")
            por_categoria.setdefault(cat, []).append(e.get("error", ""))
        else:
            por_categoria.setdefault("[?]", []).append(str(e))
    
    # Errores persistentes (no resueltos)
    persistentes = [e for e in debug_history if not e.get("resuelto")][-5:]
    
    context = {
        "gate": "stuck_loop_unblock",
        "meta_plan_dominio": meta_plan.get("dominio", "") if meta_plan else "",
        "iteration": iteration,
        "error_patterns": errors[:5],
        "errores_por_categoria": {k: v[:3] for k, v in por_categoria.items()},
        "errores_persistentes": [
            {"error": e.get("error", ""), "categoria": e.get("categoria", ""), "desde_iter": e.get("it", 0)}
            for e in persistentes
        ],
        "fixes_attempted": scratchpad[-6:] if scratchpad else [],
    }
    
    return json.dumps(context, ensure_ascii=False)


def _parse_auditor_response(content: str) -> dict:
    """Parsea JSON extrayéndolo del texto (tolerante a texto adicional del modelo)."""
    content = content.strip()
    if content.startswith("```"):
        lines = content.split("\n")
        content = "\n".join(lines[1:-1])
    if "{" in content and "}" in content:
        start = content.index("{")
        end = content.rindex("}") + 1
        try:
            return json.loads(content[start:end])
        except json.JSONDecodeError:
            pass
    return {"approved": True, "confidence": 0.5, "parse_error": True}


# ────────────────────────────────────────────────────────────────
# Gate 1: Validación de viabilidad (SIEMPRE post-orquestador)
# ────────────────────────────────────────────────────────────────
async def auditor_gate_viability(state: TeamState) -> dict:
    """Gate 1 v3: El auditor (pro) valida con contexto ENRIQUECIDO."""
    llm = get_pro_llm(max_tokens=TOKEN_BUDGET_AUDITOR_G1)
    depured_context = _depure_orchestrator_output(state)

    user_prompt = (
        "Valida si este requerimiento es VIABLE. "
        "Responde SOLO con JSON:\n"
        '{"approved": bool, "risk": "low"|"medium"|"high", '
        '"flags": [string], "confidence": float}\n\n'
        f"Contexto:\n{depured_context}"
    )

    response = await safe_invoke(llm, [
        SystemMessage(content=AUDITOR_SYSTEM),
        HumanMessage(content=user_prompt),
    ])

    content = response.content if hasattr(response, 'content') else str(response)
    verdict = _parse_auditor_response(content)

    approved = verdict.get("approved", True)
    risk = verdict.get("risk", "medium")
    flags = verdict.get("flags", [])

    print(f"[Auditor v3 · Gate 1] Viabilidad: {'✅ APROBADA' if approved else '❌ RECHAZADA'} "
          f"(riesgo: {risk}, confianza: {verdict.get('confidence', '?')})")

    if not approved:
        return {
            "auditor_review": verdict,
            "source_code": {"error.txt": f"Auditor rechazó: {', '.join(flags) if flags else 'requerimiento no viable'}"},
            "test_report": {"status": "FAIL", "errors": flags or ["Requerimiento rechazado por auditor"]},
            "scratchpad": [f"[Auditor Gate 1] RECHAZADO: {', '.join(flags)}"],
            "audit_trail": [{"nodo": "Auditor Gate 1 v3", "accion": "Viabilidad", "resultado": "RECHAZADO"}],
        }

    return {
        "auditor_review": verdict,
        "audit_trail": [{"nodo": "Auditor Gate 1 v3", "accion": "Viabilidad", "resultado": f"APROBADO (riesgo: {risk})"}],
    }


def should_proceed_after_auditor(state: TeamState) -> str:
    """Condición post-auditor Gate 1: continuar a arquitecto o detener."""
    review = state.get("auditor_review", {})
    if not review.get("approved", True):
        return "end"
    return "architect"


# ────────────────────────────────────────────────────────────────
# Gate 2: Revisión de arquitectura (SIEMPRE post-arquitecto)
# ────────────────────────────────────────────────────────────────
async def auditor_gate_architecture(state: TeamState) -> dict:
    """Gate 2 v3: El auditor (pro) revisa con ENSEMBLE de blueprints + Meta-Planner."""
    llm = get_pro_llm(max_tokens=TOKEN_BUDGET_AUDITOR_G2)
    depured_context = _depure_architect_output(state)

    user_prompt = (
        "Revisa este blueprint de arquitectura (y sus variantes de ensemble). "
        "¿Tiene fallas críticas? ¿Hay un blueprint claramente mejor? "
        "Responde SOLO con JSON:\n"
        '{"approved": bool, "critical_flaws": [string], '
        '"improvements": [string], "recommended_blueprint": int|null, '
        '"confidence": float}\n\n'
        f"Contexto:\n{depured_context}"
    )

    response = await safe_invoke(llm, [
        SystemMessage(content=AUDITOR_SYSTEM),
        HumanMessage(content=user_prompt),
    ])

    content = response.content if hasattr(response, 'content') else str(response)
    verdict = _parse_auditor_response(content)

    approved = verdict.get("approved", True)
    flaws = verdict.get("critical_flaws", [])
    improvements = verdict.get("improvements", [])
    recommended = verdict.get("recommended_blueprint")

    print(f"[Auditor v3 · Gate 2] Arquitectura: {'✅ APROBADA' if approved else '⚠️ CON FALLAS'} "
          f"({len(flaws)} fallas, {len(improvements)} mejoras, "
          f"blueprint recomendado: {recommended}, "
          f"confianza: {verdict.get('confidence', '?')})")

    result = {
        "auditor_review_architecture": verdict,
        "audit_trail": [{
            "nodo": "Auditor Gate 2 v3",
            "accion": "Revisión de arquitectura con ensemble",
            "resultado": f"{'APROBADA' if approved else 'FALLAS'} — {len(flaws)} críticas, rec: blueprint {recommended}",
        }],
    }

    if flaws:
        result["scratchpad"] = [f"[Auditor Gate 2] Falla crítica: {f}" for f in flaws]

    if improvements:
        existing = result.get("scratchpad", [])
        existing.extend([f"[Auditor Gate 2] Mejora: {i}" for i in improvements])
        result["scratchpad"] = existing

    return result


# ────────────────────────────────────────────────────────────────
# Gate 3: Desbloqueo de loop (CONDICIONAL: solo si ≥3 iteraciones)
# ────────────────────────────────────────────────────────────────
async def auditor_gate_stuck_loop(state: TeamState) -> dict:
    """Gate 3 v3: El auditor (pro) analiza errores CLASIFICADOS + persistentes."""
    llm = get_pro_llm(max_tokens=TOKEN_BUDGET_AUDITOR_G3)
    depured_context = _depure_stuck_loop(state)

    user_prompt = (
        "El loop Programador-Tester está atascado. Analiza los errores CLASIFICADOS. "
        "Responde SOLO con JSON:\n"
        '{"root_cause": string, "fix_strategy": string, '
        '"should_restart": bool, "confidence": float}\n\n'
        f"Contexto:\n{depured_context}"
    )

    response = await safe_invoke(llm, [
        SystemMessage(content=AUDITOR_SYSTEM),
        HumanMessage(content=user_prompt),
    ])

    content = response.content if hasattr(response, 'content') else str(response)
    verdict = _parse_auditor_response(content)

    root_cause = verdict.get("root_cause", "No determinado")
    fix = verdict.get("fix_strategy", "Reintentar con enfoque diferente")
    should_restart = verdict.get("should_restart", False)

    print(f"[Auditor v3 · Gate 3] Loop atascado (iter {state.get('iteration_count', 0)}): "
          f"Causa: {root_cause[:80]}... "
          f"Estrategia: {fix[:80]}... "
          f"Reiniciar: {'SÍ' if should_restart else 'NO'}")

    result = {
        "audit_trail": [{
            "nodo": "Auditor Gate 3 v3",
            "accion": "Desbloqueo de loop con errores clasificados",
            "resultado": f"Causa raíz: {root_cause[:100]}",
        }],
        "scratchpad": [
            f"[Auditor Gate 3] Causa raíz: {root_cause}",
            f"[Auditor Gate 3] Estrategia: {fix}",
        ],
    }

    if should_restart:
        result["scratchpad"].append("[Auditor Gate 3] Se recomienda reiniciar el pipeline desde Arquitecto")

    return result
