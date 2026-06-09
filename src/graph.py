"""Ensamblaje del StateGraph — Flujo del enjambre v3.0 (INTELIGENCIA x4).

ARQUITECTURA V3.0:
  Gate 0 (Pro) → Meta-Planner: analiza requirement COMPLETO, configura router
  Flash (gratis) → 90% del trabajo: generación, análisis, testing rutinario
  Pro (pago, $)  → 10% estratégico: Gate 0, Gates auditor, desbloqueo de loops

  FLUJO MEJORADO v3.0:
    1. Gate 0 (Meta-Planner Pro) — configura pipeline óptimamente
    2. ParallelPrep (flash) — RAG + skills + lecciones
    3. Orquestador v3 (flash) — 2 variantes de plan, contexto DINÁMICO
    4. Gate 1 (Pro) — valida con contexto enriquecido
    5. Arquitecto v3 (flash) — ENSEMBLE de 3 blueprints en paralelo
    6. Gate 2 (Pro) — revisa ensemble + elige mejor blueprint
    7. Programador v3 (flash/pro) — auto-reflexión + TDD ligero
    8. Tester v3 (flash) — errores CLASIFICADOS
    9. Gate 3 (Pro) — desbloqueo si ≥3 iter
    10. Reflexión (flash) — aprendizaje por refuerzo
"""

import hashlib

from langgraph.graph import StateGraph, END
from src.state import TeamState
from src.config import (
    MAX_ITERATIONS, AUDITOR_TRIGGER_ITERATION, MAX_SCRATCHPAD_ENTRIES,
    should_skip_gate, get_max_iterations, get_hard_cap_iterations,
    get_current_complexity, detect_complexity
)
from src.model_router import get_router, reset_router

# ── Nodos ──
from src.nodes.parallel_prep import parallel_prep_node
from src.nodes.meta_planner import meta_planner_node  # 🆕 Gate 0 v3.0
from src.nodes.orchestrator import orchestrator_node
from src.nodes.architect import architect_node, architect_redesign_node
from src.nodes.programmer import programmer_node
from src.nodes.tester import parallel_tester_node
from src.nodes.knowledge_extractor import knowledge_extractor_node
from src.nodes.fail_diagnosis import fail_diagnosis_node
from src.nodes.reflection import reflection_node

# ── Auditor Gates ──
from src.nodes.auditor_gate import (
    auditor_gate_viability,
    auditor_gate_architecture,
    auditor_gate_stuck_loop,
    should_proceed_after_auditor,
)


def _compute_fingerprint(source_code: dict) -> str:
    """Genera un hash del código fuente para detectar loops."""
    if not source_code:
        return ""
    combined = "".join(f"{k}:{v}" for k, v in sorted(source_code.items()))
    return hashlib.md5(combined.encode()).hexdigest()[:16]


def should_retry(state: TeamState) -> str:
    """Condición de enrutamiento desde el Tester con cortocircuito de bucle.
    
    MEJORAS IMPLEMENTADAS:
    1. Loop detection: detecta código estancado y fuerza PASS o diagnóstico
    2. Model Router: escalado quirúrgico según iteración y errores
    3. Cortocircuito: si hay loop y calidad aceptable → forzar extractor
    """
    # ── Pruning del scratchpad ──
    scratchpad = state.get("scratchpad", [])
    if len(scratchpad) > MAX_SCRATCHPAD_ENTRIES:
        state["scratchpad"] = scratchpad[-MAX_SCRATCHPAD_ENTRIES:]

    test_report = state.get("test_report", {})
    iteration = state.get("iteration_count", 0)
    status = test_report.get("status", "FAIL")
    errors = len(test_report.get("errors", []))
    
    # ── Loop detection (fingerprint + estancamiento de FAILs) ──
    current_fp = _compute_fingerprint(state.get("source_code", {}))
    previous_fp = state.get("code_fingerprint", "")
    
    # Detectar estancamiento por FAIL CONSECUTIVOS
    error_history = state.get("error_history", [])
    error_history.append("FAIL" if status == "FAIL" else "PASS")
    state["error_history"] = error_history[-8:]  # últimas 8
    
    consecutive_fails = 0
    for e in reversed(error_history):
        if e == "FAIL":
            consecutive_fails += 1
        else:
            break
    
    # Prioridad 1: Gate 3 primero (en iter 3+), después de Gate 3 cortocircuito
    if status == "FAIL":
        if iteration >= AUDITOR_TRIGGER_ITERATION and iteration < 5:
            # Dar oportunidad a Gate 3 primero
            gate3_triggered = any(
                "Auditor Gate 3" in step.get("nodo", "")
                for step in state.get("audit_trail", [])
            )
            if not gate3_triggered:
                print(f"[Router] FAIL en iter {iteration} → Gate 3 (desbloqueo con pro)")
                return "auditor_gate_3"
        
        # Cortocircuito por FAIL consecutivos (después de Gate 3)
        if consecutive_fails >= 3 and iteration >= 3:
            print(f"[Router] ⚡ CORTOCIRCUITO: {consecutive_fails} FAILs consecutivos en iter {iteration}")
            state["loop_detected"] = True
            return "fail_diagnosis"
    
    # Loop por fingerprint (código no cambia)
    if iteration >= 2 and previous_fp and current_fp and current_fp == previous_fp:
        print(f"[Router] 🔄 LOOP DE CÓDIGO en iter {iteration}")
        state["loop_detected"] = True
        if iteration >= 3:
            print(f"[Router] ⚡ CORTOCIRCUITO: código estancado")
            return "fail_diagnosis"
    
    # Actualizar fingerprint
    state["code_fingerprint"] = current_fp
    
    # ── Hard cap ──
    hard_cap = get_hard_cap_iterations()
    if iteration >= hard_cap:
        print(f"[Router] ❌ HARD CAP ({hard_cap} iter). → Diagnóstico completo")
        return "fail_diagnosis"

    if status == "PASS":
        return "knowledge_extractor"

    # ── Router: decidir escalado ──
    router = get_router()
    router.decide("Router", iteration=iteration, errors=errors, loop_detected=state.get("loop_detected", False))
    state["router_stats"] = router.get_stats()
    
    print(f"[Router] 📊 Escalado: {router.escalado.name} | Pro usados: {router.pro_calls_used}/{router.max_pro} | Iter: {iteration}")

    # ── Escalamiento suave: rediseño de arquitectura en iter 9+
    if iteration >= 9:
        print(f"[Router] FAIL en iter {iteration} → rediseño de arquitectura (pro)")
        return "architect_redesign"

    if iteration < get_max_iterations():
        print(f"[Router] FAIL → reintentando (iter {iteration + 1}/{get_max_iterations()}, pro: {router.pro_calls_used}/{router.max_pro})")
        return "programmer"

    print(f"[Router] FAIL definitivo tras {get_max_iterations()} iteraciones")
    return "fail_diagnosis"


def should_use_gate_0(state: TeamState) -> str:
    """Determina si Gate 0 (Meta-Planner Pro) debe ejecutarse.
    
    Gate 0 se ejecuta SIEMPRE para tareas medium/high.
    Para tareas low, se salta para ahorrar la llamada Pro (~$0.002).
    """
    requirement = state.get("user_requirement", "")
    complexity = detect_complexity(requirement)
    
    if complexity == "low" and len(requirement) < 200:
        print(f"[Router v3] Tarea simple ({len(requirement)} chars) → Saltando Gate 0")
        return "parallel_prep"
    
    print(f"[Router v3] 🎯 Activando Gate 0 (Meta-Planner Pro) para complejidad {complexity}")
    return "meta_planner"


def should_route_after_gate0(state: TeamState) -> str:
    """Después de Gate 0, configurar router y continuar a parallel_prep."""
    meta_plan = state.get("meta_plan", {})
    router_config = meta_plan.get("configuracion_router", {}) if meta_plan else {}
    
    # Configurar router con parámetros del Meta-Planner
    router = get_router()
    pro_active = router_config.get("pro_active_desde_inicio", False)
    if pro_active:
        router.set_pro_active_override(1)  # GATES_PRO desde el inicio
    
    # Ajustar max_pro dinámicamente
    suggested_pro = router_config.get("max_calls_pro_sugeridas", 0)
    if suggested_pro > 0:
        router.max_pro = suggested_pro
        print(f"[Router v3] Max Pro ajustado a {suggested_pro} según Meta-Planner")
    
    return "parallel_prep"


def should_audit_architecture(state: TeamState) -> str:
    """Condición para Auditor Gate 2 v3.0: revisa ensemble + Meta-Planner."""
    bluep = state.get("architecture_blueprint", {})
    files = bluep.get("archivos", {})
    ensemble = state.get("ensemble_blueprints", [])
    meta_plan = state.get("meta_plan", {})
    
    # Si Meta-Planner recomienda Gate 2, siempre ejecutarlo
    router_config = meta_plan.get("configuracion_router", {}) if meta_plan else {}
    if router_config.get("requiere_gate_2", True) == False:
        print(f"[Router v3] Meta-Planner recomienda saltar Gate 2")
        return "programmer"
    
    if should_skip_gate(2):
        print(f"[Router v3] Tarea simple → Saltando Gate 2")
        return "programmer"

    # Si hay ensemble (3 blueprints), SIEMPRE pasar por Gate 2 para que elija el mejor
    if len(ensemble) >= 2:
        print(f"[Router v3] 🏆 Ensemble activo ({len(ensemble)} blueprints) → Gate 2 elige el mejor")
        return "auditor_gate_2"

    if len(files) > 2:
        print(f"[Router v3] Arquitectura compleja ({len(files)} archivos) → Gate 2")
        return "auditor_gate_2"

    decisions = bluep.get("decisiones_tecnicas", [])
    if len(decisions) > 3:
        print(f"[Router v3] {len(decisions)} decisiones técnicas → Gate 2")
        return "auditor_gate_2"

    review = state.get("auditor_review", {})
    if review.get("risk") == "high":
        print(f"[Router v3] Riesgo alto de Gate 1 → Gate 2")
        return "auditor_gate_2"

    router = get_router()
    if router.escalado >= 1:
        print(f"[Router v3] Escalado activo ({router.escalado.name}) → Gate 2 preventivo")
        return "auditor_gate_2"

    print(f"[Router v3] Blueprint simple ({len(files)} archivos) → Saltando Gate 2")
    return "programmer"


def build_graph() -> StateGraph:
    """Construye y compila el StateGraph del enjambre de agentes."""
    
    workflow = StateGraph(TeamState)

    # ── Nodo router de entrada (v3.0) ──
    async def entry_router(state: TeamState) -> dict:
        """Router de entrada: decide si Gate 0 es necesario o salta directo."""
        decision = should_use_gate_0(state)
        return {"_entry_decision": decision}
    
    # ── Agregar nodos ──
    workflow.add_node("entry_router", entry_router)             # 🆕 Router de entrada
    workflow.add_node("meta_planner", meta_planner_node)       # 🆕 Gate 0 v3.0
    workflow.add_node("parallel_prep", parallel_prep_node)
    workflow.add_node("orchestrator", orchestrator_node)
    workflow.add_node("auditor_gate_1", auditor_gate_viability)
    workflow.add_node("architect", architect_node)
    workflow.add_node("auditor_gate_2", auditor_gate_architecture)
    workflow.add_node("architect_redesign", architect_redesign_node)
    workflow.add_node("programmer", programmer_node)
    workflow.add_node("tester", parallel_tester_node)
    workflow.add_node("auditor_gate_3", auditor_gate_stuck_loop)
    workflow.add_node("knowledge_extractor", knowledge_extractor_node)
    workflow.add_node("fail_diagnosis", fail_diagnosis_node)
    workflow.add_node("reflection", reflection_node)  # 🧠 Ciclo RL

    # ── ENTRY POINT → Router de entrada ──
    workflow.set_entry_point("entry_router")
    
    # Router → Gate 0 (si tarea medium/high) o ParallelPrep (si tarea simple)
    workflow.add_conditional_edges(
        "entry_router",
        lambda s: s.get("_entry_decision", "parallel_prep"),
        {"meta_planner": "meta_planner", "parallel_prep": "parallel_prep"},
    )
    
    # Gate 0 (Meta-Planner) → configura router → ParallelPrep
    workflow.add_conditional_edges(
        "meta_planner",
        should_route_after_gate0,
        {"parallel_prep": "parallel_prep"},
    )
    
    # ── Flujo principal ──
    workflow.add_edge("parallel_prep", "orchestrator")
    
    # OPTIMIZACIÓN P0: Gate 1 se salta si Meta-Planner ya validó viabilidad
    workflow.add_conditional_edges(
        "orchestrator",
        lambda s: "architect" if s.get("meta_planner_fused") else "auditor_gate_1",
        {"auditor_gate_1": "auditor_gate_1", "architect": "architect"},
    )

    # Gate 1 → Arquitecto (o END si rechazado) — solo si no está fusionado
    workflow.add_conditional_edges(
        "auditor_gate_1",
        should_proceed_after_auditor,
        {"architect": "architect", "end": END},
    )

    # Arquitecto → Gate 2 (condicional, con router) → Programador
    workflow.add_conditional_edges(
        "architect",
        should_audit_architecture,
        {"auditor_gate_2": "auditor_gate_2", "programmer": "programmer"},
    )
    workflow.add_edge("auditor_gate_2", "programmer")

    # Programador → Tester
    workflow.add_edge("programmer", "tester")

    # Tester → (varios destinos con cortocircuito de bucle)
    workflow.add_conditional_edges(
        "tester",
        should_retry,
        {
            "auditor_gate_3": "auditor_gate_3",
            "architect_redesign": "architect_redesign",
            "programmer": "programmer",
            "knowledge_extractor": "knowledge_extractor",
            "fail_diagnosis": "fail_diagnosis",
            END: END,
        },
    )

    # Gate 3 → Programador (desbloqueo)
    workflow.add_edge("auditor_gate_3", "programmer")

    # Rediseño → Programador
    workflow.add_edge("architect_redesign", "programmer")

    # Fail Diagnosis → Reflection (Ciclo RL)
    workflow.add_edge("fail_diagnosis", "reflection")

    # Extractor → Reflection (Ciclo RL)
    workflow.add_edge("knowledge_extractor", "reflection")

    # Reflection → END (cierra el ciclo)
    workflow.add_edge("reflection", END)

    return workflow.compile()


# ── Singleton del grafo compilado ──
_compiled_graph = None


def get_graph():
    """Devuelve el grafo compilado (singleton)."""
    global _compiled_graph
    if _compiled_graph is None:
        _compiled_graph = build_graph()
    return _compiled_graph
