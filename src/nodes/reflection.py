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
    """Nodo de reflexión post-ejecución con memoria episódica.
    
    Procesa el estado final y extrae aprendizaje usando:
    1. LessonsEngine (lecciones genéricas)
    2. EpisodicMemory (episodios + auto-crítica + heurísticas)
    3. ModelRouter (señal de refuerzo)
    4. PromptEvolution (evolución de prompts)
    
    Returns:
        state actualizado con aprendizajes
    """
    print(f"\n{'='*60}")
    print(f"  🧠 REFLECTION NODE v2.0 — Superinteligencia Continua")
    print(f"{'='*60}")
    
    requirement = state.get("user_requirement", "")
    test_report = state.get("test_report", {})
    status = test_report.get("status", "UNKNOWN")
    iterations = state.get("iteration_count", 0)
    success = status == "PASS"
    
    print(f"  Estado: {'✅ ÉXITO' if success else '❌ FALLO'}")
    print(f"  Iteraciones: {iterations}")
    
    # ── 1. LessonsEngine (lecciones tradicionales) ──
    lessons_result = process_execution(state)
    print(f"  [LessonsEngine] {lessons_result['new_lessons']} nuevas, "
          f"{lessons_result['rules_generated']} reglas")
    
    # ── 2. EpisodicMemory (NUEVO: reflexión verbal) ──
    print(f"\n  ── Memoria Episódica (Reflexión Verbal) ──")
    try:
        episodic_result = process_episode(state)
        print(f"  [Episodic] Episodio {episodic_result['episode_id']}")
        print(f"  [Episodic] {episodic_result['heuristics_extracted']} heurísticas extraídas")
        
        # Análisis de tendencias
        trends = episodic_result.get("trends", {})
        if trends.get("trend") and trends.get("trend") != "insuficientes_datos":
            emoji = "📈" if trends["trend"] == "mejorando" else "📉" if trends["trend"] == "empeorando" else "📊"
            print(f"  [Tendencias] {emoji} {trends['trend'].upper()} | "
                  f"tasa: {trends.get('success_rate', 0)*100:.0f}% | "
                  f"iter avg: {trends.get('avg_iterations', 0):.1f}")
        
        # Guardar auto-crítica en scratchpad
        self_reflection = episodic_result.get("self_reflection", "")
        if self_reflection:
            print(f"  [Reflexión Verbal] Auto-crítica generada ({len(self_reflection)} chars)")
    except Exception as e:
        print(f"  ⚠️ Error en EpisodicMemory: {e}")
        self_reflection = ""
        episodic_result = {"heuristics_extracted": 0, "episode_id": "error"}
    
    # ── 3. Señal de refuerzo al Model Router ──
    signal = lessons_result["reinforcement_signal"]
    try:
        router = get_router()
        update_router_learning(
            signal["success"],
            signal["quality"],
            signal["iterations"],
            signal["errors"],
            signal["complexity"],
        )
        router_stats = router.get_stats()
        print(f"  [Router] {router_stats['escalado_label']} | "
              f"Pro: {router_stats['pro_calls_used']}/{router_stats['max_pro']}")
    except Exception as e:
        print(f"  ⚠️ Error en Router: {e}")
    
    # ── 4. Prompt Evolution v3.0 ──
    try:
        evo_result = PromptEvolution.evolve(
            success=success,
            iterations=iterations,
            signal=signal["signal"],
            test_report=test_report,
            scratchpad=state.get("scratchpad", []),
        )
        if evo_result.get("cambios_aplicados", 0) > 0:
            print(f"  [PromptEvolution v3] 🧬 {evo_result['razon']}")
            if evo_result.get("weak_node"):
                print(f"  [PromptEvolution v3] Nodo mejorado: {evo_result['weak_node']}")
    except Exception as e:
        print(f"  ⚠️ Error en PromptEvolution: {e}")
    
    # ── 5. Self-Play (guardar ejemplo) ──
    try:
        PromptEvolution.save_selfplay_example(
            requirement=requirement,
            blueprint=state.get("architecture_blueprint", {}),
            source_code=state.get("source_code", {}),
            test_report=test_report,
            success=success,
            iterations=iterations,
        )
        print(f"  [SelfPlay] Ejemplo guardado ({'PASS' if success else 'FAIL'})")
    except Exception as e:
        print(f"  ⚠️ Error en SelfPlay: {e}")
    
    # ── 6. Contexto de lecciones + heurísticas ──
    lessons_context = lessons_result["lessons_context"]
    heuristics_context = episodic_result.get("heuristics_context", "")
    
    # ── 7. Scoreboard ──
    try:
        scoreboard_text = get_scoreboard_text()
        if "vacío" not in scoreboard_text:
            for line in scoreboard_text.split("\n")[:5]:
                print(f"  {line}")
    except Exception as e:
        print(f"  ⚠️ Error en scoreboard: {e}")
    
    # ── 8. Reflexión profunda con LLM (solo si falló) ──
    deep_reflection = ""
    if not success and iterations >= 3:
        try:
            llm = get_llm(temperature=0.3, max_tokens=400)
            prompt = f"""Analiza esta ejecución fallida y da una recomendación:

        Requerimiento: {requirement[:200]}
        Iteraciones: {iterations}
        Errores: {test_report.get('errors', [])[:3]}
        Scratchpad: {state.get('scratchpad', [])[-3:]}

        ¿Qué recomiendas para la próxima vez?
        Extrae UNA heurística concreta."""
            
            response = await safe_invoke(llm, [
                {"role": "system", "content": REFLECTION_ANALYSIS_PROMPT},
                {"role": "user", "content": prompt},
            ])
            deep_reflection = response.content if hasattr(response, 'content') else str(response)
            print(f"  [DeepReflection] {deep_reflection[:100]}...")
        except Exception as e:
            print(f"  ⚠️ Error en deep reflection: {e}")
    
    print(f"{'='*60}\n")
    
    # ── Construir resultado ──
    scratchpad_entries = [
        f"[Reflection v2] {'✅ Éxito' if success else '❌ Fallo'} — "
        f"{iterations} iter, "
        f"{lessons_result['new_lessons']} lecciones, "
        f"{episodic_result['heuristics_extracted']} heurísticas, "
        f"señal RL: {signal['signal']:.3f}",
    ]
    
    if episodic_result.get("episode_id") and episodic_result["episode_id"] != "error":
        scratchpad_entries.append(
            f"[Episodic Memory] Episodio {episodic_result['episode_id']} archivado"
        )
    
    if lessons_result['rules_generated'] > 0:
        scratchpad_entries.append(
            f"[Rules] {lessons_result['rules_generated']} nuevas reglas inyectables"
        )
    
    if deep_reflection:
        scratchpad_entries.append(f"[DeepReflection] {deep_reflection[:200]}")
    
    return {
        "scratchpad": scratchpad_entries,
        "audit_trail": [{
            "nodo": "Reflection v2 (Superinteligencia Continua)",
            "accion": "Post-ejecución con memoria episódica",
            "resultado": (
                f"{'Éxito' if success else 'Fallo'} | "
                f"{lessons_result['new_lessons']} lecciones | "
                f"{episodic_result['heuristics_extracted']} heurísticas | "
                f"episodio: {episodic_result.get('episode_id', 'N/A')}"
            ),
        }],
    }
