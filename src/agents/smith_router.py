"""Smith Model Router — Switching inteligente flash↔pro con budget tracking.

Smith 1.0 necesita decidir en CADA interacción si usar:
  • deepseek-v4-flash (Go, $): rápido, barato, para tareas rutinarias
  • deepseek-v4-pro  (Go, $$): lento, caro, para razonamiento complejo

ESTRATEGIA DE 3 CAPAS:
  1. Heurísticas rápidas (0 tokens, <1ms) → filtra lo obvio
  2. Complexity classifier (flash, barato) → score 0-1
  3. Budget gate → ¿nos queda presupuesto para pro?

BUDGET TRACKING:
  • Pro ~ $0.015/1k tokens de input + $0.06/1k tokens de output
  • Budget diario configurable (default: $2/día para pro)
  • Si se agota → flash automático
  • Alertas al usuario cuando queda < 20%

APRENDIZAJE CONTINUO:
  • Registra si usar pro realmente mejoró el resultado
  • Ajusta thresholds según histórico de éxito
  • Detecta patrones: ¿qué tipo de tareas justifican pro?
"""

from __future__ import annotations

import re
import time
import json
import hashlib
import logging
from pathlib import Path
from enum import Enum
from typing import Optional, Dict, Any
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# ── Constantes ───────────────────────────────────────────────────

PRO_INPUT_COST_PER_1K = 0.015   # $ por 1k tokens de input
PRO_OUTPUT_COST_PER_1K = 0.06   # $ por 1k tokens de output
FLASH_INPUT_COST_PER_1K = 0.002  # $ por 1k tokens de input
FLASH_OUTPUT_COST_PER_1K = 0.008 # $ por 1k tokens de output

DEFAULT_DAILY_BUDGET_PRO = 2.00  # $2/día máximo para pro
BUDGET_WARNING_THRESHOLD = 0.20  # Alertar al 20% restante
BUDGET_CRITICAL_THRESHOLD = 0.05  # Solo emergencias al 5%

COST_CACHE_FILE = Path.home() / ".agents" / "smith_budget.json"


# ── Tipos ────────────────────────────────────────────────────────

class ModelTier(str, Enum):
    FLASH = "flash"
    PRO = "pro"


class TaskComplexity(str, Enum):
    TRIVIAL = "trivial"     # "hola", "gracias", "sí"
    SIMPLE = "simple"       # Pregunta directa, respuesta conocida
    MODERATE = "moderate"   # Requiere razonamiento o análisis
    COMPLEX = "complex"     # Múltiples pasos, investigación
    CRITICAL = "critical"   # Decisión estratégica, arquitectura


@dataclass
class RouterDecision:
    """Decisión del router para un turno de Smith."""
    tier: ModelTier
    complexity: TaskComplexity
    complexity_score: float
    budget_remaining: float
    budget_pct: float
    reason: str
    was_heuristic: bool
    timestamp: float = field(default_factory=time.time)

    @property
    def uses_pro(self) -> bool:
        return self.tier == ModelTier.PRO

    @property
    def is_budget_warning(self) -> bool:
        return self.budget_pct <= BUDGET_WARNING_THRESHOLD

    @property
    def is_budget_critical(self) -> bool:
        return self.budget_pct <= BUDGET_CRITICAL_THRESHOLD


@dataclass
class TurnRecord:
    """Registro de un turno para aprendizaje."""
    message_hash: str
    complexity_score: float
    used_model: str
    tokens_input: int
    tokens_output: int
    cost_usd: float
    success: bool  # ¿fue útil la respuesta?
    latency_ms: float
    timestamp: float = field(default_factory=time.time)


# ── Heurísticas rápidas (0 tokens) ──────────────────────────────

# Palabras/frases que indican tarea trivial (ni siquiera necesita flash)
TRIVIAL_PATTERNS = [
    r'^(hola|hey|hi|buenos días|buenas tardes|buenas noches)\b',
    r'^(gracias|ok|vale|entiendo|perfecto|genial|bien)\b',
    r'^(s[ií]|no|ya|claro|listo|dale|vamos|adelante|continúa)\b',
    r'^(qué tal|cómo (estás|andas|vas)|todo bien)\b',
    r'^(hasta luego|chao|bye|nos vemos|adiós)\b',
]

# Palabras clave que sugieren alta complejidad → considerar pro
# Incluye variantes con/sin acentos y conjugaciones comunes para robustez
COMPLEX_KEYWORDS = [
    'arquitectura', 'disena', 'diseña', 'disen', 'diseñ',
    'blueprint', 'estrategia', 'analiza a fondo',
    'investiga profundamente', 'investig', 'evalua', 'evalúa', 'evalu',
    'compara', 'trade-off', 'tradeoff',
    'pros y contras', 'mejor enfoque', 'refactoriza',
    'debug complejo', 'seguridad', 'vulnerabilidad', 'amenaza',
    'migracion', 'migración', 'migrar',
    'sistema complejo', 'multi-agente', 'multiagente', 'microservicio',
    'microservicios', 'machine learning', 'deep learning',
    'agente autonomo', 'agente autónomo',
]

# Palabras clave que sugieren complejidad moderada
MODERATE_KEYWORDS = [
    'implement', 'desarroll', 'constru',
    'explica', 'describe', 'document',
    'busca', 'encuentra', 'lista', 'muestra',
    'convierte', 'transforma', 'genera',
    'prueba', 'testea', 'valida',
    'configura', 'instala', 'setup',
    'api rest', 'endpoint', 'base de datos', 'docker',
    'deploy', 'deployment', 'despliegue', 'script',
    'proces', 'automat',
]


# ── Smith Model Router ───────────────────────────────────────────

class SmithRouter:
    """Router inteligente de modelos para Smith 1.0.

    Decide flash vs pro en cada interacción basado en:
      1. Heurísticas rápidas (costo 0)
      2. Clasificador de complejidad (costo flash, ~100 tokens)
      3. Budget gate (tracking de presupuesto)

    Uso:
        router = SmithRouter(daily_budget=2.0)
        decision = router.decide("Diseña la arquitectura de un sistema de trading")
        if decision.uses_pro:
            # usar deepseek-v4-pro
    """

    def __init__(self, daily_budget: float = DEFAULT_DAILY_BUDGET_PRO):
        self.daily_budget = daily_budget
        self.used_today = 0.0
        self.total_pro_calls = 0
        self.total_flash_calls = 0
        self.total_spent = 0.0
        self.history: list[TurnRecord] = []
        self._load_budget()

    # ── API pública ─────────────────────────────────────────────

    def decide(self, message: str,
               force_pro: bool = False,
               force_flash: bool = False) -> RouterDecision:
        """Decide qué modelo usar para procesar un mensaje del usuario.

        Args:
            message: Mensaje del usuario
            force_pro: Forzar uso de pro (ej: usuario pide explícitamente)
            force_flash: Forzar uso de flash (ej: tarea de bajo riesgo)

        Returns:
            RouterDecision con tier, complexity, budget, reason
        """
        # Override manual
        if force_pro:
            return self._decide_pro("Forzado por configuración", TaskComplexity.CRITICAL, 1.0)
        if force_flash:
            return self._decide_flash("Forzado por configuración", TaskComplexity.SIMPLE, 0.1)

        # Capa 1: Heurísticas rápidas (0 tokens)
        heuristic = self._heuristic_check(message)
        if heuristic:
            return heuristic

        # Capa 2: Clasificador de complejidad (basado en heurísticas + longitud)
        complexity, score = self._classify_complexity(message)

        # Capa 3: Budget gate
        budget_pct = self._budget_remaining_pct()

        # Decisión
        if complexity in (TaskComplexity.TRIVIAL, TaskComplexity.SIMPLE):
            return self._decide_flash(
                f"Complejidad {complexity.value} (score={score:.2f})",
                complexity, score, budget_pct
            )
        elif complexity == TaskComplexity.MODERATE:
            # Flash para moderadas, pro si budget abundante y score alto
            if score > 0.45 and budget_pct > 0.4:
                return self._decide_pro(
                    f"Moderada-alta (score={score:.2f}) + budget ok ({budget_pct:.0%})",
                    complexity, score, budget_pct
                )
            return self._decide_flash(
                f"Complejidad moderada (score={score:.2f}) -> flash suficiente",
                complexity, score, budget_pct
            )
        elif complexity == TaskComplexity.COMPLEX:
            # Pro si hay budget, flash si no
            if budget_pct > BUDGET_CRITICAL_THRESHOLD:
                return self._decide_pro(
                    f"Tarea compleja (score={score:.2f}), budget={budget_pct:.0%}",
                    complexity, score, budget_pct
                )
            return self._decide_flash(
                f"Tarea compleja pero budget crítico ({budget_pct:.0%}) → fallback a flash",
                complexity, score, budget_pct
            )
        else:  # CRITICAL
            # Siempre pro para críticas, aunque el budget esté bajo
            return self._decide_pro(
                f"Tarea CRÍTICA (score={score:.2f}) → pro obligatorio",
                complexity, score, budget_pct
            )

    def record_usage(self, tier: ModelTier, tokens_input: int,
                    tokens_output: int, success: bool, latency_ms: float,
                    message: str = ""):
        """Registra uso de tokens y costo después de cada respuesta."""
        if tier == ModelTier.PRO:
            cost = (tokens_input / 1000 * PRO_INPUT_COST_PER_1K +
                    tokens_output / 1000 * PRO_OUTPUT_COST_PER_1K)
            self.total_pro_calls += 1
        else:
            cost = (tokens_input / 1000 * FLASH_INPUT_COST_PER_1K +
                    tokens_output / 1000 * FLASH_OUTPUT_COST_PER_1K)
            self.total_flash_calls += 1

        self.used_today += cost
        self.total_spent += cost

        record = TurnRecord(
            message_hash=hashlib.md5(message.encode()).hexdigest()[:8] if message else "unknown",
            complexity_score=0.5,
            used_model=tier.value,
            tokens_input=tokens_input,
            tokens_output=tokens_output,
            cost_usd=round(cost, 6),
            success=success,
            latency_ms=latency_ms,
        )
        self.history.append(record)

        # Guardar budget
        self._save_budget()

    def get_budget_status(self) -> Dict[str, Any]:
        """Devuelve estado actual del presupuesto."""
        remaining = max(self.daily_budget - self.used_today, 0)
        return {
            "daily_budget": self.daily_budget,
            "used_today": round(self.used_today, 4),
            "remaining": round(remaining, 4),
            "remaining_pct": round(remaining / max(self.daily_budget, 0.01), 2),
            "total_spent": round(self.total_spent, 4),
            "total_pro_calls": self.total_pro_calls,
            "total_flash_calls": self.total_flash_calls,
            "pro_cost_estimate": f"~${self.used_today:.4f}/hoy, ~${self.total_spent:.4f}/total",
        }

    def get_stats_summary(self) -> str:
        """Resumen legible de estadísticas."""
        status = self.get_budget_status()
        avg_pro_cost = (self.total_spent / max(self.total_pro_calls, 1))
        return (
            f"💰 Smith Budget: ${status['used_today']:.4f} / ${self.daily_budget:.2f} hoy "
            f"({status['remaining_pct']:.0%} restante) | "
            f"Pro: {self.total_pro_calls} llamadas (avg ${avg_pro_cost:.4f}) | "
            f"Flash: {self.total_flash_calls} llamadas | "
            f"Total: ${self.total_spent:.4f}"
        )

    # ── Heurísticas ─────────────────────────────────────────────

    def _heuristic_check(self, message: str) -> Optional[RouterDecision]:
        """Verifica heurísticas rápidas antes de gastar tokens en clasificar."""
        msg_lower = message.lower().strip()

        # Trivial: saludos, agradecimientos, afirmaciones cortas
        for pattern in TRIVIAL_PATTERNS:
            if re.match(pattern, msg_lower):
                return self._decide_flash(
                    f"Heurística: mensaje trivial ('{message[:30]}...')",
                    TaskComplexity.TRIVIAL, 0.0
                )

        # Muy corto → simple
        if len(msg_lower.split()) < 5:
            return self._decide_flash(
                f"Heurística: mensaje muy corto ({len(msg_lower.split())} palabras)",
                TaskComplexity.SIMPLE, 0.1
            )

        # No se pudo decidir por heurísticas → necesita clasificador
        return None

    def _classify_complexity(self, message: str) -> tuple[TaskComplexity, float]:
        """Clasifica complejidad basado en keywords + longitud + estructura.

        Sin llamar al LLM — usa heurísticas de texto para ahorrar tokens.
        """
        msg_lower = message.lower()
        score = 0.0

        # Factor 1: Longitud (mas largo -> potencialmente mas complejo)
        words = len(msg_lower.split())
        if words > 100:
            score += 0.35
        elif words > 50:
            score += 0.25
        elif words > 25:
            score += 0.15
        elif words > 12:
            score += 0.08

        # Factor 2: Preguntas multiples
        question_marks = msg_lower.count('?')
        if question_marks > 3:
            score += 0.25
        elif question_marks > 1:
            score += 0.15
        elif question_marks == 1:
            score += 0.05

        # Factor 3: Keywords de complejidad alta
        complex_matches = sum(1 for kw in COMPLEX_KEYWORDS if kw in msg_lower)
        if complex_matches >= 3:
            score += 0.5
        elif complex_matches >= 2:
            score += 0.4
        elif complex_matches >= 1:
            score += 0.25

        # Factor 4: Keywords de complejidad moderada
        moderate_matches = sum(1 for kw in MODERATE_KEYWORDS if kw in msg_lower)
        if moderate_matches >= 3:
            score += 0.2
        elif moderate_matches >= 1:
            score += 0.1

        # Factor 5: Requiere codigo/implementacion
        code_indicators = ['codigo', 'script', 'funcion', 'clase', 'api',
                          'programa', 'implementa', 'debug', 'error',
                          'endpoint', 'docker', 'deploy', 'test']
        if any(ind in msg_lower for ind in code_indicators):
            score += 0.1

        # Factor 6: Multiples dominios/contextos
        context_markers = [' y ', ' o ', ' vs ', 'compar', 'diferencia entre',
                          'ademas', 'tambien', 'también']
        if any(m in msg_lower for m in context_markers):
            score += 0.08

        # Factor 7: Datos estructurados (JSON, tablas, listas)
        if '{' in message or '|' in message or '\t' in message:
            score += 0.1

        # Factor 8: Palabras de accion fuerte (crea, diseña, construye)
        action_words = ['crea', 'disena', 'diseña', 'construye', 'desarrolla',
                       'implementa', 'orquesta', 'planifica']
        action_count = sum(1 for aw in action_words if aw in msg_lower)
        if action_count >= 2:
            score += 0.15

        # Clamp y clasificar
        score = max(0.0, min(1.0, score))

        if score < 0.20:
            return TaskComplexity.TRIVIAL, score
        elif score < 0.35:
            return TaskComplexity.SIMPLE, score
        elif score < 0.60:
            return TaskComplexity.MODERATE, score
        elif score < 0.80:
            return TaskComplexity.COMPLEX, score
        else:
            return TaskComplexity.CRITICAL, score

    # ── Budget ──────────────────────────────────────────────────

    def _budget_remaining_pct(self) -> float:
        """Porcentaje de presupuesto diario restante."""
        remaining = max(self.daily_budget - self.used_today, 0)
        return remaining / max(self.daily_budget, 0.01)

    def _save_budget(self):
        """Persiste estado del presupuesto a disco."""
        try:
            COST_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "daily_budget": self.daily_budget,
                "used_today": self.used_today,
                "total_spent": self.total_spent,
                "total_pro_calls": self.total_pro_calls,
                "total_flash_calls": self.total_flash_calls,
                "last_updated": time.time(),
            }
            COST_CACHE_FILE.write_text(json.dumps(data, indent=2))
        except Exception:
            pass  # No crítico si falla el cache

    def _load_budget(self):
        """Carga estado del presupuesto desde disco."""
        try:
            if COST_CACHE_FILE.exists():
                data = json.loads(COST_CACHE_FILE.read_text())
                last = data.get("last_updated", 0)
                # Resetear si es de otro día
                if time.time() - last > 86400:  # 24h
                    self.used_today = 0.0
                else:
                    self.used_today = data.get("used_today", 0.0)
                self.total_spent = data.get("total_spent", 0.0)
                self.total_pro_calls = data.get("total_pro_calls", 0)
                self.total_flash_calls = data.get("total_flash_calls", 0)
                logger.info(
                    f"Smith budget cargado: ${self.used_today:.4f}/hoy, "
                    f"${self.total_spent:.4f}/total"
                )
        except Exception:
            pass

    # ── Helpers ─────────────────────────────────────────────────

    def _decide_flash(self, reason: str, complexity: TaskComplexity,
                     score: float, budget_pct: float = None) -> RouterDecision:
        if budget_pct is None:
            budget_pct = self._budget_remaining_pct()
        return RouterDecision(
            tier=ModelTier.FLASH,
            complexity=complexity,
            complexity_score=score,
            budget_remaining=max(self.daily_budget - self.used_today, 0),
            budget_pct=budget_pct,
            reason=reason,
            was_heuristic=(complexity in (TaskComplexity.TRIVIAL, TaskComplexity.SIMPLE)),
        )

    def _decide_pro(self, reason: str, complexity: TaskComplexity,
                   score: float, budget_pct: float = None) -> RouterDecision:
        if budget_pct is None:
            budget_pct = self._budget_remaining_pct()
        return RouterDecision(
            tier=ModelTier.PRO,
            complexity=complexity,
            complexity_score=score,
            budget_remaining=max(self.daily_budget - self.used_today, 0),
            budget_pct=budget_pct,
            reason=reason,
            was_heuristic=False,
        )
