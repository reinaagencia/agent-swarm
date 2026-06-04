"""Nodo 6 — Extractor de Conocimiento (Episodic Learner).
Solo se ejecuta si el Tester da PASS.
Toma el problema original y el código final, genera un resumen,
lo vectoriza y lo inserta en Supabase (agent_memory) para el futuro.

Optimizado:
  Fase 1: Código truncado, blueprint resumido, max_tokens acotado
  Fase 3: Budget dinámico según complejidad
  Fase 4: Registro de métricas + auto-detección de patrones para skills
"""

import json
from langchain_core.messages import HumanMessage, SystemMessage
from src.state import TeamState
from src.config import get_llm, TEMPERATURE_DEFAULT, safe_invoke, get_budget, get_current_complexity
from src.supabase_utils import save_to_memory
from src.metrics import record_run
from src.cache import invalidate_cache
from src.skill_generator import check_and_generate
from src.tuner import auto_tune


EXTRACTOR_PROMPT = """Eres el Extractor de Conocimiento del Enjambre.

Tu tarea es generar un resumen de alta calidad del proyecto completado para guardarlo
en la memoria del sistema y que futuros agentes puedan aprender de esta experiencia.

Incluye:
1. Una descripción concisa del problema resuelto.
2. La solución implementada (arquitectura y decisiones clave).
3. Lecciones aprendidas y patrones reutilizables.
4. Fragmentos de código clave que podrían servir en el futuro.

Responde con el resumen en texto plano (NO JSON), bien estructurado y en español.
Máximo 1024 tokens de salida. Sé conciso."""


async def knowledge_extractor_node(state: TeamState) -> dict:
    """Extrae conocimiento del proyecto exitoso y lo guarda en Supabase."""
    llm = get_llm(temperature=TEMPERATURE_DEFAULT, max_tokens=get_budget("extractor"))
    requirement = state.get("user_requirement", "")
    source_code = state.get("source_code", {})
    blueprint = state.get("architecture_blueprint", {})

    # Formatear el código para el resumen (solo primeros 1500 chars por archivo)
    codigo_clave = []
    for filename, code in source_code.items():
        code = code[:1500] + "\n# ... [truncado]" if len(code) > 1500 else code
        codigo_clave.append(f"### {filename}\n```python\n{code}\n```")

    # Blueprint resumido (solo descripción general + lista de archivos)
    bp_resumen = {
        "descripcion": blueprint.get("descripcion_general", "")[:200],
        "archivos": list(blueprint.get("archivos", {}).keys()),
        "decisiones": blueprint.get("decisiones_tecnicas", [])[:3],
    }

    prompt = f"""PROBLEMA:
{requirement[:200]}

ARQUITECTURA:
{json.dumps(bp_resumen, indent=2, ensure_ascii=False)}

CÓDIGO:
{chr(10).join(codigo_clave)}

Genera un resumen de conocimiento para la memoria del sistema."""

    response = await safe_invoke(llm, [
        SystemMessage(content=EXTRACTOR_PROMPT),
        HumanMessage(content=prompt),
    ])

    summary = response.content if hasattr(response, 'content') else str(response)
    print(f"[Extractor] Resumen generado ({len(summary)} chars)")

    # Determinar task_type dinámicamente según el requerimiento y skills activadas
    injected = state.get("injected_skills", {})
    matched_skills = injected.get("matched", [])
    
    if matched_skills:
        domain_tag = matched_skills[0].replace("-pattern", "").replace("-std", "").replace("-blueprint", "")
        task_type = f"{domain_tag}_exitoso"
    elif "mcp" in requirement.lower() or "server" in requirement.lower():
        task_type = "mcp_server_exitoso"
    elif "cli" in requirement.lower() or "script" in requirement.lower():
        task_type = "cli_tool_exitoso"
    elif "api" in requirement.lower() or "rest" in requirement.lower():
        task_type = "api_integration_exitoso"
    elif "csv" in requirement.lower() or "json" in requirement.lower() or "data" in requirement.lower():
        task_type = "data_pipeline_exitoso"
    else:
        task_type = "codigo_exitoso"
    
    # Guardar en Supabase
    metadata = {
        "archivos": list(source_code.keys()),
        "lenguaje": "Python",
        "exito": True,
        "skills_activadas": matched_skills,
        "task_type": task_type,
    }
    await save_to_memory(
        task_type=task_type,
        content=summary,
        metadata=metadata,
    )
    print(f"[Extractor] task_type={task_type} — skills: {matched_skills}")

    # ── Registrar métricas de la ejecución (Fase 4) ──
    source_code = state.get("source_code", {})
    test_report = state.get("test_report", {})
    iterations = state.get("iteration_count", 0)

    # Calcular tokens estimados (contando caracteres de prompts aproximados)
    total_input_est = 0
    auditor_review = state.get("auditor_review", {})
    auditor_review_arch = state.get("auditor_review_architecture", {})

    # Estimar número de llamadas LLM
    num_llm_calls = 1  # orquestador
    if state.get("auditor_review"):
        num_llm_calls += 1  # Gate 1
    if state.get("auditor_review_architecture"):
        num_llm_calls += 1  # Gate 2
    num_llm_calls += 1  # arquitecto
    num_llm_calls += iterations + 1  # programador (1 por iter + 1 extra)
    num_llm_calls += iterations + 1  # tester (1 por iter + 1 extra)
    num_llm_calls += 1  # extractor

    metrics = {
        "task_type": task_type,
        "complexity": get_current_complexity(),
        "status": test_report.get("status", "PASS"),
        "iterations": iterations,
        "time_seconds": 0,  # Se rellena externamente si se desea
        "num_files": len(source_code),
        "num_llm_calls": num_llm_calls,
        "total_input_tokens": 0,  # Pendiente: tracking real de tokens
        "total_output_tokens": 0,
        "estimated_cost": 0,
        "skills_activated": matched_skills,
        "error_summary": "",
        "requirement_summary": requirement[:100],
    }
    record_run(metrics)

    # Invalidar caché relacionada (para que futuros requerimientos similares
    # no usen datos de esta ejecución como si fueran de otra distinta)
    # Nota: la caché se invalida por TTL, no inmediatamente.

    print(f"[Extractor] Métricas registradas: {task_type}, {iterations} iter, {len(source_code)} archivos")

    # ── Auto-generación de skills si hay patrón repetido (Fase 4) ──
    nuevas_skills = check_and_generate()
    if nuevas_skills:
        print(f"[Extractor] 🆕 Skills auto-generadas: {', '.join(nuevas_skills)}")
        result_scratchpad = [f"[Extractor] Skills auto-generadas: {', '.join(nuevas_skills)}"]
    else:
        result_scratchpad = []

    # ── Auto-tuning: ajustar budgets según rendimiento histórico (Fase 5) ──
    try:
        tuning_result = auto_tune()
        if tuning_result.get("ajustes_realizados"):
            result_scratchpad.append(
                f"[Tuner] Auto-ajuste: {len(tuning_result['ajustes_realizados'])} cambios"
            )
    except Exception as e:
        print(f"[Tuner] ⚠️ Error en auto-tuning: {e}")
    
    # ── Model Router: aprender de la ejecución (señal preliminar) ──
    try:
        from src.model_router import get_router
        router = get_router()
        # La señal refinada vendrá del Reflection Node, aquí solo una señal preliminar
        calidad = 1.0 if state.get("test_report", {}).get("status") == "PASS" else 0.0
        router.aprender(
            ejecucion_exitosa=(calidad == 1.0),
            calidad=calidad,
            iteraciones=iterations,
            errores=len(test_report.get("errors", [])),
            complexity=get_current_complexity(),
        )
        router_stats = router.get_stats()
        print(f"[Extractor] Router stats: {router_stats}")
    except Exception as e:
        print(f"[Extractor] ⚠️ Error actualizando router: {e}")

    # ── Datos enriquecidos para el Reflection Node ──
    reflection_data = {
        "extractor_summary_length": len(summary),
        "extractor_task_type": task_type,
        "extractor_skills_activated": matched_skills,
        "extractor_metrics": metrics,
    }
    
    return {
        "scratchpad": [f"[Extractor] Conocimiento guardado en memoria vectorial — {len(summary)} caracteres"]
                      + result_scratchpad,
        "audit_trail": [{
            "nodo": "Extractor de Conocimiento",
            "accion": "Resumen y almacenamiento en Supabase",
            "resultado": f"Memoria guardada — {len(summary)} caracteres",
        }],
    }
