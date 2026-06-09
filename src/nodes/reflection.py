"""🧠 Nodo de Reflexión — Ciclo de Aprendizaje por Refuerzo + Memoria Episódica.

MEJORA SUPERINTELIGENCIA v2.0:
  - Episodic Memory Buffer: archiva episodios completos con auto-crítica
  - Reflexión Verbal (Reflexion-style): genera heurísticas de cada ejecución
  - Análisis de tendencias: detecta mejora/empeoramiento
  - Inyección inteligente: heurísticas aprendidas → prompts de futuras tareas

ARQUITECTURA:
```
Tester → [PASS] → KnowledgeExtractor → REFLECTION → END
Tester → [FAIL] → FailDiagnosis → REFLECTION → END
                                    ↓
                           LessonsEngine.process_execution()
                           EpisodicMemory.process_episode() ← NUEVO
                                    ↓
                           ModelRouter.aprender()
                           PromptEvolution.evolve()
                                    ↓
                           Heuristics context ready for next run
```
"""

import json
from src.state import TeamState
from src.lessons_engine import process_execution, get_lessons_context, get_scoreboard_text
from src.prompt_evolution import PromptEvolution  # 🧬 v3.0
from src.model_router import get_router, update_router_learning
from src.config import safe_invoke, get_llm
from src.episodic_memory import process_episode, show_status as episodic_status


# Prompt de reflexión para el LLM
REFLECTION_ANALYSIS_PROMPT = """Eres el Analista de Reflexión del Enjambre de Desarrollo.

Tu tarea es analizar la ejecución completa de una tarea y extraer:

1. ¿Qué salió bien? (patterns a repetir)
2. ¿Qué salió mal? (anti-patterns a evitar)
3. ¿Qué errores específicos aparecieron? (pitfalls con solución)
4. ¿Qué se puede optimizar? (optimizaciones de eficiencia)
5. ¿Qué heurística puedes extraer? (regla "si → entonces" generalizable)

IMPORTANTE - REFLEXIÓN VERBAL:
  Escribe una auto-crítica honesta. No culpes a factores externos.
  Si falló, fue porque el código tenía errores. Identifícalos.
  Si funcionó, identifica QUÉ hiciste diferente que funcionó.

Sé conciso, específico y accionable. Máximo 400 tokens.

Responde en este formato:
```
ANÁLISIS: [tu análisis aquí]
HEURÍSTICA: [regla si→entonces generalizable]
```"""


async def reflection_node(state: TeamState) -> dict:
    """Reflection Node OPTIMIZADO — solo para episodios significativos.
    
    OPTIMIZACIÓN x10:
    - Skip si la ejecución es trivial (1 iter, sin errores, PASS)
    - Deep reflection eliminado (beneficio marginal)
    - PromptEvolution eliminado (overhead innecesario)
    - SelfPlay eliminado (no usado)
    """
    test_report = state.get("test_report", {})
    status = test_report.get("status", "UNKNOWN")
    iterations = state.get("iteration_count", 0)
    success = status == "PASS"
    errors_count = len(test_report.get("errors", []))
    
    # Skip si es trivial
    if success and iterations <= 1 and errors_count == 0:
        print(f"[Reflection] ⏭️ Skip: ejecución trivial ({iterations} iter, PASS)")
        return {
            "scratchpad": [f"[Reflection] Skip: ejecución trivial en {iterations} iter"],
            "audit_trail": [{"nodo": "Reflection (skip)", "accion": "Skip por trivial", "resultado": "OK"}],
        }
    
    print(f"\n{'='*60}")
    print(f"  🧠 REFLECTION (Optimizado)")
    print(f"{'='*60}")
    print(f"  Estado: {'✅ ÉXITO' if success else '❌ FALLO'}, {iterations} iter, {errors_count} errors")
    
    # ── 1. LessonsEngine ──
    lessons_result = process_execution(state)
    print(f"  [LessonsEngine] {lessons_result['new_lessons']} nuevas, "
          f"{lessons_result['rules_generated']} reglas")
    
    # ── 2. EpisodicMemory ──
    print(f"\n  ── Memoria Episódica ──")
    try:
        episodic_result = process_episode(state)
        print(f"  [Episodic] Episodio {episodic_result.get('episode_id', '?')}")
    except Exception as e:
        print(f"  ⚠️ Error en EpisodicMemory: {e}")
        episodic_result = {"heuristics_extracted": 0, "episode_id": "error"}
    
    # ── 3. Model Router (señal de refuerzo) ──
    try:
        router = get_router()
        update_router_learning(success, 1.0 if success else 0.0, iterations, 0, "medium")
        print(f"  [Router] Aprendizaje: {'✅' if success else '❌'}")
    except Exception as e:
        print(f"  ⚠️ Error en Router: {e}")
    
    # PromptEvolution y SelfPlay eliminados (P0: simplificación x10)
    
    signal = lessons_result.get("reinforcement_signal", {"signal": 1.0 if success else 0.0})
    print(f"{'='*60}\n")
    
    return {
        "scratchpad": [
            f"[Reflection] {'✅ Éxito' if success else '❌ Fallo'} — "
            f"{iterations} iter, {lessons_result.get('new_lessons', 0)} lecciones",
        ],
        "audit_trail": [{
            "nodo": "Reflection (Optimizado)",
            "accion": "Post-ejecución",
            "resultado": f"{'Éxito' if success else 'Fallo'} | {lessons_result.get('new_lessons', 0)} lecciones",
        }],
    }
