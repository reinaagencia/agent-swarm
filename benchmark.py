#!/usr/bin/env python3
"""Benchmark runner del Enjambre — Fase 4: Aprendizaje Autónomo.

Ejecuta un conjunto estándar de tareas y registra métricas para
detectar regresiones o mejoras en el rendimiento del pipeline.

Uso:
    python3 benchmark.py                    # Ejecuta suite completa
    python3 benchmark.py --quick            # Solo tareas rápidas
    python3 benchmark.py --report           # Solo mostrar reporte semanal
    python3 benchmark.py --generate-skills  # Solo generar skills desde patrones
"""

import asyncio
import sys
import time
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

from src.config import (
    reset_fallback, precheck_free_model, set_complexity, get_current_complexity
)
from src.state import TeamState
from src.graph import get_graph
from src.metrics import record_run, generate_report, get_summary
from src.skill_generator import check_and_generate as auto_generate_skills

# ── Suite de benchmark ──
BENCHMARK_TASKS = {
    "simple": [
        "Crea una funcion filter_valid(dicts, keys) que filtre diccionarios con claves faltantes. Incluye tests pytest.",
        "Crea una funcion en Python que calcule el factorial de un numero. Incluye tests pytest.",
    ],
    "medium": [
        "Crea un script CLI que procese un archivo CSV de transacciones y genere un reporte. Incluye tests pytest.",
        "Crea una API REST con Flask para gestionar una lista de tareas (CRUD). Incluye tests pytest.",
    ],
    "high": [
        "Crea un pipeline de datos que lea JSON y CSV, los fusione por ID, calcule agregados y exporte a Excel. Incluye tests pytest.",
    ],
}


async def run_benchmark_task(requirement: str) -> dict:
    """Ejecuta una tarea de benchmark y devuelve métricas."""
    reset_fallback()
    await precheck_free_model()

    state = TeamState(
        user_requirement=requirement,
        business_rules=[],
        retrieved_memory="",
        injected_skills={"matched": [], "rules": [], "blueprint": "", "code": "", "checks": ""},
        architecture_blueprint={},
        source_code={},
        test_report={},
        scratchpad=[],
        iteration_count=0,
        audit_trail=[],
        messages=[],
    )

    t0 = time.time()
    graph = get_graph()
    result = await graph.ainvoke(state)
    elapsed = time.time() - t0

    source_code = result.get("source_code", {})
    test_report = result.get("test_report", {})
    iterations = result.get("iteration_count", 0)
    audit = result.get("audit_trail", [])

    # Contar llamadas LLM del audit trail
    llm_nodes = {"Orquestador", "Arquitecto", "Programador", "Tester",
                 "Auditor Gate 1", "Auditor Gate 2", "Auditor Gate 3",
                 "Extractor de Conocimiento", "Tester (paralelo)"}
    num_calls = sum(1 for step in audit if step.get("nodo", "") in llm_nodes)

    metrics = {
        "task_type": "benchmark",
        "complexity": get_current_complexity(),
        "status": test_report.get("status", "FAIL"),
        "iterations": iterations,
        "time_seconds": elapsed,
        "num_files": len(source_code),
        "num_llm_calls": num_calls,
        "total_input_tokens": 0,
        "total_output_tokens": 0,
        "estimated_cost": 0,
        "skills_activated": [],
        "error_summary": "; ".join(test_report.get("errors", []))[:200],
        "requirement_summary": requirement[:100],
    }
    record_run(metrics)

    return metrics


async def run_full_suite(quick: bool = False):
    """Ejecuta la suite completa de benchmark."""
    print("=" * 70)
    print("  🏋️  BENCHMARK DEL ENJAMBRE DE DESARROLLO")
    print("=" * 70)
    print(f"  Fecha: {__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print()

    tasks_to_run = []

    if quick:
        tasks_to_run.extend(BENCHMARK_TASKS["simple"][:1])
        tasks_to_run.extend(BENCHMARK_TASKS["medium"][:1])
    else:
        for complexity in ["simple", "medium", "high"]:
            tasks_to_run.extend(BENCHMARK_TASKS[complexity])

    results = {"passed": 0, "failed": 0, "total_time": 0, "tasks": []}

    for i, req in enumerate(tasks_to_run, 1):
        print(f"  [{i}/{len(tasks_to_run)}] {req[:60]}...")
        t0 = time.time()
        try:
            metric = await run_benchmark_task(req)
            elapsed = time.time() - t0
            ok = "✅" if metric["status"] == "PASS" else "❌"
            print(f"    {ok} {metric['status']} | {metric['iterations']} iter | "
                  f"{metric['num_files']} archivos | {metric['time_seconds']:.0f}s")
            
            if metric["status"] == "PASS":
                results["passed"] += 1
            else:
                results["failed"] += 1
            results["total_time"] += metric["time_seconds"]
            results["tasks"].append(metric)

        except Exception as e:
            print(f"    ❌ ERROR: {str(e)[:100]}")
            results["failed"] += 1

    print()
    print("=" * 70)
    print("  📊 RESULTADOS DEL BENCHMARK")
    print("=" * 70)
    print(f"  Pasaron: {results['passed']}/{len(tasks_to_run)}")
    print(f"  Fallaron: {results['failed']}/{len(tasks_to_run)}")
    print(f"  Tiempo total: {results['total_time']:.0f}s")
    if results["passed"] > 0:
        avg = results["total_time"] / results["passed"]
        print(f"  Tiempo promedio (éxitos): {avg:.0f}s")
    
    # Intentar auto-generar skills
    print()
    print("  🔍 Buscando patrones para auto-skills...")
    nuevas = auto_generate_skills()
    if nuevas:
        print(f"  🆕 Skills generadas: {', '.join(nuevas)}")
    else:
        print("  (no hay suficientes datos para nuevas skills aún)")

    return results


async def main():
    """Punto de entrada."""
    import argparse
    parser = argparse.ArgumentParser(description="Benchmark del Enjambre")
    parser.add_argument("--quick", action="store_true", help="Solo tareas rápidas")
    parser.add_argument("--report", action="store_true", help="Mostrar reporte")
    parser.add_argument("--generate-skills", action="store_true",
                       help="Solo generar skills desde patrones")
    args = parser.parse_args()

    if args.report:
        print(generate_report())
        return

    if args.generate_skills:
        print("🔍 Generando skills desde patrones...")
        nuevas = auto_generate_skills()
        if nuevas:
            print(f"🆕 Skills generadas: {', '.join(nuevas)}")
        else:
            print("(no hay suficientes datos para nuevas skills aún)")
        # Mostrar resumen actual
        print()
        print(generate_report())
        return

    await run_full_suite(quick=args.quick)


if __name__ == "__main__":
    asyncio.run(main())
