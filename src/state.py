"""Estado compartido del grafo — TeamState TypedDict usado por todos los nodos."""

from typing import TypedDict, Annotated, Optional
from langgraph.graph.message import add_messages
import operator


class TeamState(TypedDict):
    """Estado que fluye entre todos los nodos del enjambre de agentes."""

    # ── Entrada original ──
    user_requirement: str
    """El prompt original del usuario con el requerimiento a desarrollar."""

    # ── Reglas inmutables ──
    business_rules: list[str]
    """Reglas de negocio inyectadas al inicio que ningún agente debe violar."""

    # ── Memoria RAG ──
    retrieved_memory: str
    """Contexto recuperado de Supabase por el agente Investigador (RAG híbrido)."""

    # ── Skills inyectadas ──
    injected_skills: dict
    """Skills activadas por el Skill Resolver con sus secciones (rules, blueprint, code, checks).
    Estructura: {"matched": [...], "rules": [...], "blueprint": "...", "code": "...", "checks": "..."}"""

    # ── Plan de arquitectura ──
    architecture_blueprint: dict
    """JSON con el mapa de procesos diseñado por el Arquitecto."""

    # ── Código fuente ──
    source_code: dict
    """Diccionario de archivos y su contenido {"main.py": "código...", ...}."""

    # ── Reporte de QA ──
    test_report: dict
    """Errores y estado del Tester {"status": "PASS"|"FAIL", "errors": [...]}."""

    # ── Bitácora de iteración (acumulativa) ──
    scratchpad: Annotated[list[str], operator.add]
    """
    Notas de iteración donde los agentes anotan qué falló y cómo corregirlo.
    Se acumulan automáticamente gracias a Annotated + operator.add.
    """

    # ── Conteo de iteraciones ──
    iteration_count: int
    """Contador para evitar bucles infinitos. Límite: 10."""

    # ── Trazabilidad ──
    audit_trail: Annotated[list[dict], operator.add]
    """Registro de quién hizo qué en cada paso del pipeline."""

    # ── Revisiones del Auditor (DeepSeek V4 Pro, uso quirúrgico) ──
    auditor_review: Optional[dict]
    """Gate 1: veredicto del auditor sobre viabilidad del orquestador."""

    auditor_review_architecture: Optional[dict]
    """Gate 2: veredicto del auditor sobre blueprint del arquitecto."""

    # ── Debug Memory (historial de errores y fixes) ──
    debug_history: list[dict]
    """Historial de errores encontrados y cómo se solucionaron entre iteraciones.
    Cada entrada: {"it": int, "error": str, "fix": str, "file": str}
    Se usa para que el Programador no reintroduzca errores ya resueltos."""

    # ── Loop Detection ──
    loop_detected: bool
    """True cuando el router detecta que el código no cambia entre iteraciones."""

    # ── Code Fingerprint (hash del código anterior para detectar loops) ──
    code_fingerprint: str
    """Hash del código generado en la iteración anterior. Si se repite → loop."""

    # ── Error Stagnation (mismos errores apareciendo una y otra vez) ──
    error_history: list[str]
    """Hashes de conjuntos de errores de iteraciones anteriores.
    Si el mismo set de errores se repite ≥2 veces → estancamiento."""

    # ── Último set de errores (para detectar estancamiento) ──
    last_error_set: str
    """Hash del conjunto de errores de la iteración actual para comparar con la siguiente."""

    # ── Estado del Model Router ──
    router_stats: dict
    """Estadísticas del Model Router para logging y debugging.
    Estructura: {"escalado": int, "pro_calls_used": int, "max_pro": int, ...}"""

    # ═══════════════════════════════════════════════════════════════
    # V3.0 — INTELIGENCIA x4 (nuevos campos)
    # ═══════════════════════════════════════════════════════════════

    # ── Meta-Planner (Gate 0) ──
    meta_plan: Optional[dict]
    """Plan maestro generado por el Meta-Planner (Gate 0).
    Contiene análisis profundo, configuración del router, hints, riesgos."""

    # ── Ensemble de arquitectura ──
    ensemble_blueprints: list
    """Lista de blueprints generados por el ensemble de arquitectura.
    Gate 2 los analiza y elige el mejor. Cada entrada es un dict con blueprint."""

    # ── Micro-gates (validaciones Pro con output mínimo) ──
    micro_gates: dict
    """Resultados de los micro-gates de validación Pro.
    Estructura: {"M1_design": {"decision": "PASS", "confidence": 0.95, "reason": "..."},
                 "M2_code_triage": {...}, "M3_plan_eval": {...},
                 "M4_risk": {...}, "M5_reflection": {...}}
    Cada micro-gate produce JSON con ~40 tokens de output a costo ~$0.0036."""

    # ── Flags internos del grafo ──
    _entry_decision: Optional[str]
    """Decisión del router de entrada: 'meta_planner' o 'parallel_prep'."""

    # ── Mensajes (para compatibilidad con LangGraph) ──
    messages: Annotated[list, add_messages]
    """Historial de mensajes entre nodos (requerido por LangGraph)."""
