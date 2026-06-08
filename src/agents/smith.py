"""Smith 1.0 — Orquestador independiente del Enjambre 4.0.

EVOLUCION:
  v1.0: Pipeline monolitico (script Python)
  v2.0: LangGraph StateGraph (6 nodos internos)
  v3.0: LangGraph + subagentes task() (actual)
  v4.0: Smith orquestador independiente + agentes autonomos

OPTIMIZACIONES INTEGRADAS (herencia del Enjambre v1->v3):
  - Scratchpad acumulativo -> session_memory entre turnos
  - ParallelPrep -> delegacion asyncio a multiples agentes
  - Model Router flash<->pro -> SmithRouter con budget tracking
  - Loop detection -> pregunta repetida -> respuesta cacheada
  - Audit trail -> decision_log de cada turno
  - Token budgets -> self_limit_output + max_tokens por modo
  - Business rules -> rules_engine inyectable
  - Fallback 3 niveles -> mismo fallback de config.py
  - Reflection -> post_turn_hook de aprendizaje
  - Gate system -> auditor solo si es critico
  - TokenJuice -> comprime contexto antes de enviar
  - Lessons engine -> inyecta lecciones como business_rules
  - Skill resolver -> skills matcheadas automaticamente
  - Error dedup -> mistake_registry para no repetir
"""

from __future__ import annotations

import asyncio
import time
import hashlib
import logging
from pathlib import Path
from typing import Optional, Dict, Any, List, Callable
from dataclasses import dataclass, field

from src.agents.smith_router import (
    SmithRouter, RouterDecision, ModelTier, TaskComplexity,
)
from src.token_juice import compress

logger = logging.getLogger(__name__)

SMITH_MEMORY_DIR = Path.home() / ".agents" / "smith_memory"
SESSION_MAX_TURNS = 50
SCRATCHPAD_MAX_ENTRIES = 20
DEDUP_CACHE_SIZE = 100

TOKEN_BUDGET = {
    ModelTier.FLASH: {"max_output": 1024, "max_context": 4000},
    ModelTier.PRO:   {"max_output": 2048, "max_context": 8000},
}


@dataclass
class SessionMemory:
    """Memoria de sesion de Smith (equivalente al scratchpad acumulativo v3)."""
    turns: list = field(default_factory=list)
    scratchpad: list = field(default_factory=list)
    business_rules: list = field(default_factory=list)
    injected_lessons: list = field(default_factory=list)
    matched_skills: list = field(default_factory=list)
    decision_log: list = field(default_factory=list)
    mistake_registry: set = field(default_factory=set)
    dedup_cache: dict = field(default_factory=dict)

    def add_turn(self, user_msg: str, response: str, decision: RouterDecision,
                 tokens_used: int, latency_ms: float):
        turn = {
            "user": user_msg[:500],
            "response": response[:500],
            "model": decision.tier.value,
            "complexity": decision.complexity.value,
            "tokens": tokens_used,
            "latency_ms": round(latency_ms),
            "timestamp": time.time(),
        }
        self.turns.append(turn)
        self.decision_log.append({
            "action": "responder",
            "model": decision.tier.value,
            "reason": decision.reason,
            "tokens": tokens_used,
        })
        if len(self.turns) > SESSION_MAX_TURNS:
            self.turns = self.turns[-SESSION_MAX_TURNS:]

    def add_to_scratchpad(self, entry: str):
        self.scratchpad.append(f"[{time.strftime('%H:%M:%S')}] {entry}")
        if len(self.scratchpad) > SCRATCHPAD_MAX_ENTRIES:
            self.scratchpad = self.scratchpad[-SCRATCHPAD_MAX_ENTRIES:]

    def get_context(self, max_chars: int = 3000) -> str:
        parts = []
        if self.business_rules:
            parts.append("## Reglas de Negocio\n" + "\n".join(
                f"- {r}" for r in self.business_rules[:10]))
        if self.injected_lessons:
            parts.append("## Lecciones Aprendidas\n" + "\n".join(
                f"- {l}" for l in self.injected_lessons[:5]))
        if self.matched_skills:
            parts.append("## Skills Activas\n" + ", ".join(self.matched_skills[:8]))
        if self.scratchpad:
            parts.append("## Historial Reciente\n" + "\n".join(self.scratchpad[-5:]))
        if self.turns:
            recent = self.turns[-3:]
            parts.append("## Conversacion Reciente\n" + "\n".join(
                f"Usuario: {t['user'][:200]}\nSmith: {t['response'][:200]}"
                for t in recent))
        context = "\n\n".join(parts)
        if len(context) > max_chars:
            context = context[:max_chars] + "\n\n[... contexto truncado ...]"
        return context


# ── Delegation routing ──

DELEGATION_MAP = {
    "estratega": ["planifica", "planea", "estrategia", "plan", "descompón",
                  "descompone", "divide en pasos", "divide la tarea",
                  "multi-paso", "multipaso", "complejo", "compleja",
                  "prioriza", "roadmap", "hoja de ruta", "fases"],
    "investigador": ["investiga", "busca", "consulta", "rag", "memoria", "recupera",
                     "conocimiento previo", "proyectos similares", "lecciones"],
    "arquitecto": ["disena", "diseña", "arquitectura", "blueprint", "estructura",
                   "diseño", "diagrama", "patron", "patrón", "modulos", "módulos",
                   "arquitectonico", "arquitectónico"],
    "programador": ["programa", "codigo", "código", "implementa", "desarrolla",
                    "crea el archivo", "escribe el codigo", "script", "funcion",
                    "función", "clase", "api", "endpoint", "refactoriza",
                    "genera codigo", "genera código"],
    "tester": ["testea", "prueba", "test", "qa", "valida codigo", "valida el codigo",
               "revisa el codigo", "revisa el código", "encuentra bugs", "bug",
               "depura", "debug", "pytest"],
    "auditor": ["audita", "valida decision", "valida la decision", "gate",
                "viabilidad", "critico", "crítico", "supervisa"],
    "trader": ["trading", "acciones", "portafolio", "mercado", "alpaca",
               "financiero", "inversion", "inversión", "stock", "etf"],
    "visor": ["imagen", "captura", "video", "audio", "multimodal",
              "foto", "screenshot", "pdf visual", "grafico", "gráfico"],
}


def _detect_delegation_target(message: str) -> str | None:
    """Detecta qué agente debe manejar esta tarea. Retorna nombre o None."""
    msg_lower = message.lower()
    
    # Contar matches por agente
    scores = {}
    for agent, keywords in DELEGATION_MAP.items():
        score = sum(1 for kw in keywords if kw in msg_lower)
        if score > 0:
            scores[agent] = score
    
    if not scores:
        return None
    
    # El agente con más matches gana
    best = max(scores, key=scores.get)
    return best


def _detect_delegation(message: str) -> bool:
    """Detecta si el mensaje requiere delegación a algún agente especializado."""
    return _detect_delegation_target(message) is not None


class SmithAgent:
    """Smith 1.0 — Orquestador principal del Enjambre 4.0."""

    def __init__(self, daily_budget: float = 2.0, llm_caller: Callable = None):
        self.router = SmithRouter(daily_budget=daily_budget)
        self.memory = SessionMemory()
        self.llm_caller = llm_caller
        self.total_turns = 0
        self.total_tokens = 0
        self.total_cost = 0.0
        SMITH_MEMORY_DIR.mkdir(parents=True, exist_ok=True)

    async def process(self, message: str, force_model: str = None) -> Dict[str, Any]:
        t_start = time.time()
        self.total_turns += 1

        # 1. Modelo: flash o pro
        force_pro = force_model == "pro"
        force_flash = force_model == "flash"
        decision = self.router.decide(message, force_pro=force_pro, force_flash=force_flash)

        # 2. Dedup cache
        msg_hash = hashlib.md5(message.encode()).hexdigest()[:12]
        if msg_hash in self.memory.dedup_cache and not force_pro:
            cached = self.memory.dedup_cache[msg_hash]
            return {
                "text": cached["response"], "model_used": "cached",
                "tokens_used": 0, "cost_usd": 0.0,
                "complexity": decision.complexity.value,
                "was_delegated": False, "latency_ms": 0.5,
                "budget_status": self.router.get_budget_status(),
            }

        # 3. Contexto
        context = self.memory.get_context()

        # 4. Delegar o responder
        needs_delegation = _detect_delegation(message)

        if needs_delegation:
            result = await self._delegate(message, context, decision)
        else:
            result = await self._respond_direct(message, context, decision)

        # 5. Post-turn
        latency_ms = (time.time() - t_start) * 1000
        tokens_used = result.get("tokens_used", 0)
        success = len(result.get("text", "")) > 10

        self.memory.add_turn(message, result["text"], decision, tokens_used, latency_ms)
        self.router.record_usage(
            tier=decision.tier, tokens_input=tokens_used // 2,
            tokens_output=tokens_used // 2, success=success,
            latency_ms=latency_ms, message=message)

        if success and len(message) > 10:
            self.memory.dedup_cache[msg_hash] = {
                "response": result["text"][:500], "timestamp": time.time()}
            if len(self.memory.dedup_cache) > DEDUP_CACHE_SIZE:
                oldest = min(self.memory.dedup_cache.keys(),
                           key=lambda k: self.memory.dedup_cache[k]["timestamp"])
                del self.memory.dedup_cache[oldest]

        self.total_tokens += tokens_used
        total_cost = result.get("cost_usd", 0.0)
        self.total_cost += total_cost

        budget_status = self.router.get_budget_status()
        warning = ""
        if 0.05 < budget_status["remaining_pct"] <= 0.20:
            warning = f"\n\nWarning: Presupuesto pro al {budget_status['remaining_pct']:.0%} (${budget_status['remaining']:.2f} de ${self.router.daily_budget:.2f})"
        elif budget_status["remaining_pct"] <= 0.05:
            warning = "\n\nPRESUPUESTO PRO AGOTADO. Solo flash hasta manana."

        return {
            "text": result["text"] + warning,
            "model_used": decision.tier.value,
            "tokens_used": tokens_used,
            "cost_usd": round(total_cost, 6),
            "complexity": decision.complexity.value,
            "complexity_score": decision.complexity_score,
            "was_delegated": needs_delegation,
            "latency_ms": round(latency_ms),
            "budget_status": budget_status,
        }

    def set_business_rules(self, rules: list):
        self.memory.business_rules = rules
        self.memory.add_to_scratchpad(f"Inyectadas {len(rules)} business rules")

    def inject_lessons(self, lessons: list):
        self.memory.injected_lessons = lessons
        self.memory.add_to_scratchpad(f"Inyectadas {len(lessons)} lecciones")

    def activate_skills(self, skill_names: list):
        self.memory.matched_skills = skill_names
        if skill_names:
            self.memory.add_to_scratchpad(f"Skills: {', '.join(skill_names[:5])}")

    def register_mistake(self, mistake_key: str):
        self.memory.mistake_registry.add(mistake_key)

    def has_mistake(self, mistake_key: str) -> bool:
        return mistake_key in self.memory.mistake_registry

    def get_stats(self) -> dict:
        return {
            "total_turns": self.total_turns,
            "total_tokens": self.total_tokens,
            "total_cost": round(self.total_cost, 4),
            "dedup_hits": len(self.memory.dedup_cache),
            "mistakes": len(self.memory.mistake_registry),
            **self.router.get_budget_status(),
        }

    def get_stats_summary(self) -> str:
        stats = self.get_stats()
        return (
            f"Smith 1.0: {stats['total_turns']} turnos | "
            f"{stats['total_tokens']} tokens | "
            f"${stats['total_cost']:.4f} total | "
            f"Pro: {stats['total_pro_calls']} | Flash: {stats['total_flash_calls']} | "
            f"Budget: ${stats['remaining']:.2f}"
        )

    async def _respond_direct(self, message: str, context: str,
                             decision: RouterDecision) -> dict:
        budget = TOKEN_BUDGET[decision.tier]
        if self.llm_caller:
            return await self.llm_caller(
                message=message, context=context,
                model=decision.tier.value, max_tokens=budget["max_output"])
        return await self._fallback_pipeline(message, context, decision)

    async def _delegate(self, message: str, context: str,
                       decision: RouterDecision) -> dict:
        target = _detect_delegation_target(message) or "general"
        self.memory.add_to_scratchpad(f"Delegando a {target}: {message[:100]}...")
        if len(context) > 1000:
            context, juice_report = compress(context, max_tokens=1500)
            self.memory.add_to_scratchpad(
                f"TokenJuice: {juice_report['tokens_before']}->{juice_report['tokens_after']} tokens")
        if self.llm_caller:
            return await self.llm_caller(
                message=message, context=context,
                model=decision.tier.value,
                max_tokens=TOKEN_BUDGET[decision.tier]["max_output"])
        result = await self._fallback_pipeline(message, context, decision)
        self.memory.add_to_scratchpad(f"Delegacion a {target} completada")
        result["delegation_target"] = target
        return result

    async def _fallback_pipeline(self, message: str, context: str,
                                decision: RouterDecision) -> dict:
        from src.graph import get_graph
        full_context = f"{context}\n\n---\nMensaje: {message}"
        compressed, juice_report = compress(full_context, max_tokens=3000)
        graph = get_graph()
        initial_state = {
            "user_requirement": compressed,
            "business_rules": self.memory.business_rules,
            "iteration_count": 0, "loop_detected": False,
            "code_fingerprint": "", "router_stats": {},
            "error_history": [], "last_error_set": "",
            "retrieved_memory": "", "injected_skills": {"matched": self.memory.matched_skills},
            "scratchpad": self.memory.scratchpad[-5:],
            "audit_trail": [], "debug_history": [],
            "source_code": {}, "test_report": {}, "messages": [],
        }
        try:
            final_state = await graph.ainvoke(initial_state)
            test_report = final_state.get("test_report", {})
            source_code = final_state.get("source_code", {})
            if test_report.get("status") == "PASS" and source_code:
                files = list(source_code.keys())
                text = f"Tarea completada. Archivos: {', '.join(files)}"
            elif test_report.get("errors"):
                errors = test_report["errors"][:3]
                text = f"Completado con {len(test_report['errors'])} errores: {'; '.join(errors)}"
            else:
                text = "Tarea procesada."
            return {"text": text, "tokens_used": 5000,
                    "cost_usd": 0.01 if decision.tier == ModelTier.FLASH else 0.05}
        except Exception as e:
            logger.error(f"Smith fallback error: {e}")
            return {"text": f"Error: {str(e)[:200]}", "tokens_used": 100, "cost_usd": 0.001}


SMITH_SYSTEM_PROMPT = """Eres Smith, el orquestador principal del Enjambre 4.0.

## Tu Rol
Eres un agente independiente, NO un pipeline. Tu trabajo es:
1. Analizar lo que el usuario necesita
2. Decidir si puedes responder tu mismo o delegar a un especialista via task()
3. Sintetizar los resultados de forma clara y accionable

## Agentes Especialistas (Fase 3-4 — Independientes)
- **estratega**: Planificacion multi-paso con MoA. Descompone tareas complejas. (Fase 4)
- **investigador**: Busqueda RAG en Supabase (pgvector). Recupera conocimiento previo.
- **arquitecto**: Diseno de sistemas, blueprints JSON, estructura de archivos.
- **programador**: Generacion de codigo + verificacion bash-native. Auto-corrige errores.
- **tester**: QA — pytest real + analisis LLM en paralelo. Clasifica errores.

## Agentes de Supervision y Especializados
- **auditor**: Validacion de calidad con DeepSeek V4 Pro (solo decisiones criticas).
- **trader**: Analisis financiero, mercados, Alpaca.
- **visor-multimodal**: Analisis visual/auditivo con MiMo V2.5.
- Estratega: Planificacion, descomposicion de tareas complejas (proximamente).
- Extractor: Destilacion de conocimiento, generacion de skills (proximamente).

## Pipeline de Desarrollo (flujo tipico)
1. estratega → descompone el requerimiento en plan multi-paso (si es complejo)
2. investigador → busca conocimiento previo relevante
3. arquitecto → disena blueprint del sistema
4. programador → genera codigo ejecutable verificado
5. tester → analiza y clasifica errores
6. (loop) programador corrige → tester re-verifica
7. Si se estanca ≥3 iter → auditor desbloquea

## Reglas de Optimizacion
1. No repitas errores: si algo fallo antes, prueba un enfoque diferente
2. Presupuesto consciente: usa pro solo cuando aporte valor real
3. Contexto comprimido: TokenJuice optimiza el contexto antes de cada llamada
4. Paralelo cuando puedas: investigador + arquitecto pueden correr juntos
5. Scratchpad activo: mantén registro de lo que funciona y lo que no
6. Dedup inteligente: si el usuario repite una pregunta, usa la respuesta cacheada
7. **Delega via task()**: usa task(subagent_type="programador", ...) para cada agente

## Personalidad
Directo y eficiente, profesional sin ser robotico, honesto sobre limitaciones y costos."""

SMITH_GREETING = "Smith 1.0 listo. Orquestador del Enjambre 4.0. Fases 3-4 activas: 5 agentes independientes + estratega MoA."
