#!/usr/bin/env python3
"""Punto de entrada principal — Enjambre de Agentes Superinteligente v3.0 (INTELIGENCIA x4).

Uso:
    python main.py
    python main.py "Crea una API REST en Flask"
    python main.py --verify           # Solo verifica config
    python main.py --report           # Muestra reporte de benchmark
    python main.py --episodic         # Muestra estado de memoria episódica
    python main.py --selfplay         # Muestra estadísticas de self-play
    python main.py --catalog          # Muestra catálogo de agentes replicados
    python main.py --compare          # Compara con estándares de la industria
"""

import asyncio
import sys
import json
import time
import os
from dotenv import load_dotenv

load_dotenv()

from src.state import TeamState
from src.graph import get_graph, reset_router

# ── QueenChat Bridge ─────────────────────────────────────────────────
ENJAMBRE_MODE = os.environ.get("ENJAMBRE_MODE", "").lower() == "true"
if ENJAMBRE_MODE:
    try:
        from queenchat_communicator import queenchat, is_queenchat_mode
        print(f"\n🔗 [QueenChat Bridge] Activado — sesión {os.environ.get('ENJAMBRE_SESSION_ID', '?')}\n")
    except ImportError as e:
        print(f"\n⚠️ [QueenChat Bridge] No disponible: {e}")
        ENJAMBRE_MODE = False
        queenchat = None
        def is_queenchat_mode(): return False
else:
    queenchat = None
    def is_queenchat_mode(): return False


async def run_swarm(requirement: str) -> dict:
    """Ejecuta el enjambre completo para un requerimiento dado."""
    from src.config import (
        OPENCODE_ZEN_BASE_URL, OPENCODE_GO_BASE_URL, MAX_ITERATIONS,
        get_current_flash_model, OPENCODE_PRO_MODEL, reset_fallback, precheck_free_model,
        TOKEN_BUDGET_ORCHESTRATOR, TOKEN_BUDGET_ARCHITECT, TOKEN_BUDGET_PROGRAMMER,
        TOKEN_BUDGET_TESTER, TOKEN_BUDGET_EXTRACTOR,
        detect_complexity, set_complexity,
        should_skip_gate, COMPLEXITY_BUDGETS,
    )
    from src.benchmark_suite import record_run, generate_report
    from src.selfplay_data import record_training_pair

    reset_fallback()

    complexity = detect_complexity(requirement)
    set_complexity(complexity)
    reset_router(complexity=complexity)

    flash_model = get_current_flash_model()

    print("=" * 70)
    print("  🧠 ENJAMBRE DE AGENTES — Superinteligencia Continua v3.0 (INTELIGENCIA x4)")
    print("=" * 70)
    from src.config import get_fallback_level, get_fallback_name
    
    fallback_lvl = get_fallback_level()
    fallback_name = get_fallback_name()
    
    print(f"  🔧 Flash model:   {flash_model}")
    print(f"  ⚖️  Auditor:      {OPENCODE_PRO_MODEL}")
    print(f"  🔁 Max iter:      {MAX_ITERATIONS}")
    print(f"  🔄 Fallback:      {fallback_name} (nivel {fallback_lvl})")
    print(f"  🧠 Memoria:       Episódica + Verbal RL + Heurísticas")
    print(f"  ⚡ Bash-Native:   Auto-ejecución y corrección local")
    print(f"  📊 Benchmarks:    Tracking temporal + tendencias")
    print(f"  🎯 Self-Play:     Generación de datos de entrenamiento")
    print(f"  📈 Complejidad:   {complexity}")
    print("=" * 70)
    print(f"\n📋 Requerimiento: {requirement[:100]}...\n")

    # Pre-check del modelo
    await precheck_free_model()
    flash_model = get_current_flash_model()

    # Estado inicial
    start_time = time.time()

    # ── Inyectar contexto QueenChat si aplica ──
    queenchat_context = ""
    if ENJAMBRE_MODE and queenchat is not None:
        queenchat_context = queenchat.get_system_prompt()
        print(f"[QueenChat] Contexto inyectado en el pipeline")
    
    initial_state: TeamState = {
        "user_requirement": requirement + queenchat_context,
        "business_rules": [],
        "retrieved_memory": "",
        "injected_skills": {"matched": [], "rules": [], "blueprint": "", "code": "", "checks": ""},
        "architecture_blueprint": {},
        "source_code": {},
        "test_report": {},
        "scratchpad": [],
        "iteration_count": 0,
        "audit_trail": [],
        "messages": [],
        "debug_history": [],
        "loop_detected": False,
        "code_fingerprint": "",
        "router_stats": {},
        "error_history": [],
        "last_error_set": "",
    }

    graph = get_graph()
    print("🚀 Iniciando pipeline...\n")

    try:
        final_state = await graph.ainvoke(initial_state)

        # 🧃 TokenJuice: Log de estadísticas de compresión
        from src.token_juice import get_stats as get_juice_stats
        juice_stats = get_juice_stats()
        if juice_stats.total_calls > 0:
            print(f"\n🧃 [TokenJuice] Ahorro total: "
                  f"{juice_stats.total_tokens_before}→{juice_stats.total_tokens_after} tokens "
                  f"({juice_stats.overall_savings_pct}% ahorro) | "
                  f"{juice_stats.total_calls} compresiones")

        # Registrar en benchmark
        record_run(final_state, start_time)
        
        # Registrar en self-play
        success = final_state.get("test_report", {}).get("status") == "PASS"
        record_training_pair(final_state, success)

        print("\n" + "=" * 70)
        print("  RESULTADO FINAL")
        print("=" * 70)

        test_report = final_state.get("test_report", {})
        source_code = final_state.get("source_code", {})
        iterations = final_state.get("iteration_count", 0)
        audit = final_state.get("audit_trail", [])
        router_stats = final_state.get("router_stats", {})

        print(f"\n📊 Iteraciones: {iterations}")
        print(f"📋 Estado QA: {test_report.get('status', 'N/A')}")
        print(f"🔧 Modelo: {router_stats.get('escalado_label', '?')} | "
              f"Pro: {router_stats.get('pro_calls_used', 0)}/{router_stats.get('max_pro', 0)}")

        if test_report.get("errors"):
            print(f"\n⚠️  Errores ({len(test_report['errors'])}):")
            for err in test_report["errors"]:
                print(f"  - {err}")

        print(f"\n📁 Archivos ({len(source_code)}):")
        for filename in source_code:
            code_len = len(source_code[filename])
            print(f"  - {filename} ({code_len} chars)")

        print(f"\n📝 Trazabilidad ({len(audit)} pasos):")
        for step in audit:
            print(f"  [{step.get('nodo', '?')}] {step.get('accion', '?')} → {step.get('resultado', '?')}")

        scratchpad_final = final_state.get("scratchpad", [])
        if scratchpad_final:
            print(f"\n📓 Scratchpad ({len(scratchpad_final)}):")
            for note in scratchpad_final[-10:]:
                print(f"  {note}")

        print("\n" + "=" * 70)

        # ── QueenChat: notificar resultados ──
        if ENJAMBRE_MODE and queenchat is not None:
            try:
                result_status = test_report.get("status", "FAIL")
                source_code_files = list(source_code.keys())
                file_count = len(source_code_files)
                
                summary_parts = [
                    f"Estado QA: {result_status}",
                    f"Iteraciones: {iterations}",
                ]
                if file_count > 0:
                    summary_parts.append(f"Archivos generados: {file_count}")
                if test_report.get("errors"):
                    summary_parts.append(f"Errores: {len(test_report['errors'])}")
                
                summary = " | ".join(summary_parts)
                
                if result_status == "PASS":
                    queenchat.send_message(
                        f"✅ Tarea completada exitosamente.\n{summary}\n\n"
                        f"Archivos: {', '.join(source_code_files[:5])}"
                    )
                else:
                    queenchat.send_message(
                        f"⚠️ Tarea completada con observaciones.\n{summary}"
                    )
                    
                print(f"[QueenChat] Notificación enviada a Rodrigo")
            except Exception as qe:
                print(f"[QueenChat] Error notificando: {qe}")

        return {
            "status": test_report.get("status", "FAIL"),
            "files": list(source_code.keys()),
            "iterations": iterations,
            "source_code": source_code,
        }

    except Exception as e:
        print(f"\n❌ Error: {e}")
        
        # ── QueenChat: notificar error ──
        if ENJAMBRE_MODE and queenchat is not None:
            try:
                queenchat.send_message(f"❌ Error en el enjambre: {str(e)[:500]}")
            except:
                pass
        
        raise


def main():
    if len(sys.argv) > 1:
        first_arg = sys.argv[1]
        if first_arg in ("--verify", "-v"):
            verify_config()
            return
        elif first_arg == "--report":
            from src.benchmark_suite import get_report_text, compare_to_standards
            print(get_report_text())
            print(compare_to_standards())
            return
        elif first_arg == "--episodic":
            from src.episodic_memory import show_status
            print(show_status())
            return
        elif first_arg == "--selfplay":
            from src.selfplay_data import get_stats_text
            print(get_stats_text())
            return
        elif first_arg == "--catalog":
            from src.agent_replicator import get_catalog_text
            print(get_catalog_text())
            return
        elif first_arg == "--compare":
            from src.benchmark_suite import compare_to_standards
            print(compare_to_standards())
            return
        
        requirement = " ".join(sys.argv[1:])
    else:
        requirement = "Crea un script en Python para conciliar dos archivos CSV de facturas comparando ID, monto y fecha, y genera un reporte de diferencias en formato Excel."

    asyncio.run(run_swarm(requirement))


def verify_config():
    from src.config import (
        OPENCODE_MODEL_FREE, OPENCODE_MODEL_PAID, OPENCODE_PRO_MODEL,
        OPENCODE_ZEN_BASE_URL, OPENCODE_GO_BASE_URL, TEMPERATURE_DEFAULT, MAX_ITERATIONS,
        RZULUAM_API_KEY, FALLBACK_NAMES, _get_current_key,
    )
    from src.supabase_utils import is_schema_ready
    import os

    print("=" * 70)
    print("  🧠 VERIFICACIÓN — Enjambre Superinteligente v3.0")
    print("=" * 70)
    print(f"  🔧 Flash default: {OPENCODE_MODEL_FREE} (Zen)")
    print(f"  🔧 Flash fallback: {OPENCODE_MODEL_PAID} (Go)")
    print(f"  ⚖️  Auditor:       {OPENCODE_PRO_MODEL} (Go)")
    print(f"  🌡️  Temperatura:   {TEMPERATURE_DEFAULT}")
    print(f"  🔁 Max iter:      {MAX_ITERATIONS}")
    print(f"")
    print(f"  🔄 Fallback 3 niveles:")
    print(f"     Nivel 0: {FALLBACK_NAMES[0]}")
    print(f"     Nivel 1: {FALLBACK_NAMES[1]}")
    print(f"     Nivel 2: {FALLBACK_NAMES[2]}")
    api_key_reina = os.getenv("OPENCODE_API_KEY", "")
    api_key_rzu = RZULUAM_API_KEY
    print(f"     🔑 reina: {'✓' if api_key_reina else '✗'} ({api_key_reina[:15]}...)")
    print(f"     🔑 rzuluam: {'✓' if api_key_rzu else '✗'} ({api_key_rzu[:15]}...)")
    print(f"  📦 Supabase:      {'✓' if is_schema_ready() else '⚠'} Schema ready")
    
    # Verificar módulos nuevos
    modules = [
        ("episodic_memory", "🧠 Memoria Episódica"),
        ("bash_executor", "⚡ Bash Executor"),
        ("benchmark_suite", "📊 Benchmark Suite"),
        ("selfplay_data", "🎯 Self-Play Data"),
        ("agent_replicator", "🔬 Agent Replicator"),
    ]
    print(f"\n  📦 Módulos Superinteligencia:")
    for module, name in modules:
        try:
            __import__(f"src.{module}")
            print(f"     ✓ {name}")
        except ImportError as e:
            print(f"     ✗ {name} ({e})")
    
    # Verificar skills disponibles
    skills_dir = os.path.expanduser("~/.agents/skills/dev")
    if os.path.isdir(skills_dir):
        skills = [d for d in os.listdir(skills_dir)
                  if os.path.isdir(os.path.join(skills_dir, d)) and not d.startswith('.')]
        print(f"\n  📚 Skills ({len(skills)}):")
        for s in sorted(skills):
            print(f"     ✓ {s}")
    
    print("=" * 70)


if __name__ == "__main__":
    main()
