#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════════╗
║  🧪 BENCHMARK A/B v5.0 — Enjambre 4.0 vs Builder Estándar OpenCode    ║
║                                                                        ║
║  Path A: Enjambre 4.0  → Pipeline real multi-agente (10 agentes)      ║
║  Path B: Builder Std   → deepseek-v4-pro delegando a subagentes       ║
║                                                                        ║
║  Mide: calidad, velocidad, costo, eficiencia en 5 niveles              ║
╚══════════════════════════════════════════════════════════════════════════╝
"""
import asyncio
import time
import sys
import os
import json
import re
import datetime
import io

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dotenv import load_dotenv
load_dotenv()

from bench_evaluator import evaluate_result, estimate_cost, extract_features_from_requirement

# ── Config ─────────────────────────────────────────────────────────
OUTPUT_DIR = "/Users/isabeldiaz/Dev/agent-swarm/test_results/ab_v5"
MAX_TIMEOUT_PER_TEST = 600  # 10 minutos máximo por ejecución

# ─────────────────────────────────────────────────────────────────────
# TEST SUITE: 5 niveles de complejidad
# ─────────────────────────────────────────────────────────────────────
TEST_SUITE = [
    {
        "id": "T1",
        "name": "Función utilitaria con validación",
        "level": "SIMPLE",
        "expected_files": 1,
        "requirement": (
            "Crea una función en Python `validate_email(email: str) -> bool` que valide emails "
            "usando expresiones regulares según RFC 5322 simplificado. Incluye type hints, "
            "docstring con ejemplos, manejo de errores (email None/vacío). "
            "Incluye 3 tests pytest (email válido, inválido, None) en bloque "
            "`if __name__ == '__main__'`. Un solo archivo .py."
        ),
    },
    {
        "id": "T2",
        "name": "Script CLI de procesamiento CSV",
        "level": "MEDIO",
        "expected_files": 3,
        "requirement": (
            "Crea un script CLI en Python que procese un archivo CSV de ventas con columnas: "
            "fecha (YYYY-MM-DD), producto (str), cantidad (int > 0), precio_unitario (float > 0). "
            "Calcula: totales por producto, totales por mes, producto más vendido. "
            "Exporta resultados a Excel (.xlsx) con formato (encabezados en negrita, columnas auto-ajustadas). "
            "Usa argparse, pandas, openpyxl. Manejo de errores: archivo no encontrado, datos inválidos "
            "(cantidad negativa), CSV mal formado. Incluye logging a archivo. "
            "Archivos: `main.py`, `processor.py`, `tests/test_processor.py`. Incluye 5 tests pytest."
        ),
    },
    {
        "id": "T3",
        "name": "API REST con autenticación JWT",
        "level": "COMPLEJO",
        "expected_files": 6,
        "requirement": (
            "Crea una API REST en FastAPI para un sistema de tareas (Todo App) con: "
            "1) Autenticación JWT (registro POST /auth/register, login POST /auth/login, token expires in 24h). "
            "2) CRUD de tareas (GET/POST/PUT/DELETE /tasks) con campos: id (UUID), title (str, requerido, 3-100 chars), "
            "description (str, opcional), completed (bool, default False), created_at (datetime), owner_id (UUID del usuario autenticado). "
            "3) Las tareas son privadas por usuario (solo el dueño las ve/modifica). "
            "4) Almacenamiento SQLite con SQLAlchemy. "
            "5) Rate limiting: 100 requests/minuto por IP. "
            "6) Documentación automática con OpenAPI. "
            "7) Tests pytest con httpx TestClient: 8 tests mínimo. "
            "Archivos: `main.py`, `models.py`, `schemas.py`, `auth.py`, `database.py`, `tests/test_api.py`, `requirements.txt`."
        ),
    },
    {
        "id": "T4",
        "name": "Pipeline ETL asíncrono",
        "level": "MUY COMPLEJO",
        "expected_files": 8,
        "requirement": (
            "Crea un sistema ETL asíncrono en Python para procesar logs de servidor. "
            "Componentes: 1) Extractor (extractor.py): lee archivos .log.gz de un directorio de entrada "
            "(watchdog para detectar nuevos archivos). "
            "2) Parser (parser.py): parsea logs en formato: [TIMESTAMP] [LEVEL] [MODULE] Mensaje. "
            "Clasifica por nivel (ERROR, WARN, INFO, DEBUG). "
            "3) Transformer (transformer.py): normaliza IPs, anonimiza datos sensibles, "
            "enriquece con geolocalización (ciudad desde IP). "
            "4) Loader (loader.py): exporta a SQLite (tablas: logs, metrics_hourly, errors_summary). "
            "5) Orchestrator (orchestrator.py): pipeline asyncio con colas asyncio.Queue, "
            "3 workers en paralelo, backpressure cuando cola > 1000 items. "
            "6) Monitor (monitor.py): muestra métricas en tiempo real. "
            "Tests con pytest-asyncio (mínimo 10 tests). "
            "Archivos: extractor.py, parser.py, transformer.py, loader.py, orchestrator.py, "
            "monitor.py, models.py, config.py, tests/, requirements.txt."
        ),
    },
    {
        "id": "T5",
        "name": "Sistema de contabilidad PYME colombiana",
        "level": "EMPRESARIAL",
        "expected_files": 10,
        "requirement": (
            "Crea un sistema de contabilidad para una PYME colombiana. Módulos: "
            "1) Clientes (clients.py): CRUD de empresas con datos fiscales (NIT, régimen, contacto). "
            "2) Facturación (invoices.py): recepción y validación de facturas (ingreso/gasto), "
            "contabilización automática, PUC (Plan Único de Cuentas colombiano). "
            "3) Contabilidad (accounting.py): catálogo de cuentas, pólizas contables, "
            "balanza de comprobación, libro diario y mayor. "
            "4) Impuestos (taxes.py): cálculo de IVA (19%), Retefuente (2.5%, 3.5%, 11%), "
            "ICA (0.5-1%), formato 1001 DIAN. "
            "5) Reportes (reports.py): Balance General, Estado de Resultados, Flujo de Caja, Reporte DIAN. "
            "6) CLI (main.py): argparse con comandos: process-invoices, generate-report, tax-calc. "
            "Almacenamiento SQLite con 15+ tablas normalizadas. "
            "Tests pytest mínimo 15 tests. Logging completo. "
            "Archivos separados por módulo + tests/ + requirements.txt + schema.sql."
        ),
    },
]


# ═══════════════════════════════════════════════════════════════════════
# PATH A: Enjambre 4.0 (Pipeline Real)
# ═══════════════════════════════════════════════════════════════════════

async def run_enjambre(requirement: str, test_id: str) -> dict:
    """Ejecuta el pipeline real del Enjambre 4.0 vía graph.ainvoke()."""
    from src.config import reset_fallback, precheck_free_model
    from src.graph import get_graph
    from src.state import TeamState

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
        debug_history=[],
        loop_detected=False,
        code_fingerprint="",
        router_stats={},
        error_history=[],
        last_error_set="",
    )

    t0 = time.time()
    try:
        graph = get_graph()
        result = await asyncio.wait_for(
            graph.ainvoke(state),
            timeout=MAX_TIMEOUT_PER_TEST
        )
        elapsed = time.time() - t0

        source_code = result.get("source_code", {})
        test_report = result.get("test_report", {})
        audit = result.get("audit_trail", [])
        iterations = result.get("iteration_count", 0)
        router_stats = result.get("router_stats", {})

        # Contar calls
        llm_nodes = {"Orquestador", "Arquitecto", "Programador", "Tester",
                     "Auditor Gate 1", "Auditor Gate 2", "Auditor Gate 3",
                     "Extractor de Conocimiento", "Meta-Planner",
                     "Investigador", "Skill Resolver"}
        num_calls = sum(1 for step in audit if step.get("nodo", "") in llm_nodes)
        pro_calls = sum(1 for step in audit
                       if "Gate" in step.get("nodo", "")
                       or "Pro" in str(step.get("modelo", "")))

        return {
            "system": "enjambre_4.0",
            "test_id": test_id,
            "status": test_report.get("status", "FAIL"),
            "files": source_code,
            "time_seconds": round(elapsed, 2),
            "llm_calls": max(num_calls, 1),
            "pro_calls": pro_calls,
            "iterations": iterations,
            "router_stats": router_stats,
            "total_chars": sum(len(c) for c in source_code.values()),
            "num_files": len(source_code),
            "audit_summary": [
                {"nodo": s.get("nodo", "?"), "resultado": s.get("resultado", "?")}
                for s in audit[-20:]
            ],
        }
    except asyncio.TimeoutError:
        return {
            "system": "enjambre_4.0",
            "test_id": test_id,
            "status": "TIMEOUT",
            "files": {},
            "time_seconds": MAX_TIMEOUT_PER_TEST,
            "llm_calls": 0,
            "pro_calls": 0,
            "error": f"Timeout after {MAX_TIMEOUT_PER_TEST}s",
            "total_chars": 0,
            "num_files": 0,
        }
    except Exception as e:
        elapsed = time.time() - t0
        return {
            "system": "enjambre_4.0",
            "test_id": test_id,
            "status": "ERROR",
            "files": {},
            "time_seconds": round(elapsed, 2),
            "llm_calls": 0,
            "pro_calls": 0,
            "error": str(e)[:500],
            "total_chars": 0,
            "num_files": 0,
        }


# ═══════════════════════════════════════════════════════════════════════
# PATH B: Builder Estándar OpenCode (deepseek-v4-pro delegando)
# ═══════════════════════════════════════════════════════════════════════

async def run_builder(requirement: str, test_id: str) -> dict:
    """
    Simula el Builder estándar de OpenCode:
    - Modelo principal: deepseek-v4-pro (el builder)
    - Subagentes disponible: general y explore (deepseek-v4-flash)
    - El builder analiza, decide si delegar, y sintetiza
    """
    from src.config import get_pro_llm, get_llm, safe_invoke
    from langchain_core.messages import HumanMessage, SystemMessage

    BUILDER_SYSTEM = """Eres el **Builder estándar de OpenCode**, un ingeniero de software senior que produce código funcional completo.

## Tu enfoque
1. **Analiza** el requerimiento completo para entender el alcance
2. **Decide** si delegas partes a subagentes o lo resuelves directamente
3. **Produce** el código final completo y funcional

## Reglas de delegación
- Tareas SIMPLES (1-2 archivos): resuélvelas tú mismo directamente
- Tareas MEDIAS (3-4 archivos): puedes delegar subtareas específicas a subagentes
- Tareas COMPLEJAS (5+ archivos): delega sistemáticamente partes independientes

## Tus subagentes (deepseek-v4-flash)
- `general`: para tareas genéricas, implementación de módulos específicos
- `explore`: para prototipado rápido, búsqueda de patrones de solución

## Formato de respuesta
Responde con el código COMPLETO. Separa cada archivo con:
# --- filename.ext ---

Incluye type hints, docstrings, manejo de errores, y tests.
Si usaste subagentes, incluye al final:
# --- DELEGATION LOG ---
(subagentes usados y qué hicieron)
"""

    builder_llm = get_pro_llm(max_tokens=16384)
    flash_llm = get_llm(max_tokens=8192)

    t0 = time.time()
    total_calls = 0
    pro_calls = 0
    flash_calls = 0
    delegation_log = []

    try:
        # ── Paso 1: Builder analiza y decide estrategia ──
        print(f"\n      [Builder] Analizando requerimiento...", end=" ")
        sys.stdout.flush()
        total_calls += 1
        pro_calls += 1

        response_plan = await safe_invoke(builder_llm, [
            SystemMessage(content=BUILDER_SYSTEM + "\n\nPrimero, analiza el requerimiento y define tu estrategia. ¿Vas a delegar? ¿Qué partes?"),
            HumanMessage(content=requirement),
        ])
        strategy = response_plan.content if hasattr(response_plan, 'content') else str(response_plan)
        print(f"OK (estrat. definida)")

        # ── Paso 2: Ejecutar subagentes si la estrategia lo requiere ──
        subagent_results = {}
        should_delegate = any(kw in strategy.lower() for kw in
                              ["delegar", "subagente", "delegate", "subtask", "paralelo",
                               "asigno", "reparto", "divido", "separo"])

        if should_delegate:
            # Extraer subtareas del plan
            sub_tasks = _parse_subtasks(strategy, requirement)
            print(f"      [Builder] Delegando {len(sub_tasks)} subtareas a subagentes...")

            async def run_subagent(task_name: str, task_desc: str, idx: int) -> tuple:
                nonlocal total_calls, flash_calls
                sub_prompt = (
                    f"Eres un subagente de desarrollo (`{task_name or 'general'}`).\n\n"
                    f"## Tu tarea específica (parte del proyecto más grande)\n{task_desc}\n\n"
                    f"Genera el código completo para tu parte. Responde SOLO con el código."
                )
                r = await safe_invoke(flash_llm, [HumanMessage(content=sub_prompt)])
                content = r.content if hasattr(r, 'content') else str(r)
                total_calls += 1
                flash_calls += 1
                return task_name or f"subtask_{idx}", content

            tasks = [run_subagent(name, desc, i) for i, (name, desc) in enumerate(sub_tasks)]
            results = await asyncio.gather(*tasks)
            for name, content in results:
                subagent_results[name] = content
                delegation_log.append({
                    "subagent": name,
                    "model": "flash",
                    "chars": len(content),
                })
            print(f"      [Builder] {len(subagent_results)} subagentes completados")
        else:
            print(f"      [Builder] Sin delegación — resuelve directamente")

        # ── Paso 3: Builder sintetiza resultado final ──
        print(f"      [Builder] Sintetizando resultado final...", end=" ")
        sys.stdout.flush()
        total_calls += 1
        pro_calls += 1

        # Preparar contexto para síntesis
        sub_context = ""
        if subagent_results:
            sub_context = "\n\nResultados de subagentes:\n"
            for name, content in subagent_results.items():
                sub_context += f"\n--- {name} ---\n{content[:3000]}\n"

        synthesis_prompt = f"""Requerimiento original:
{requirement}

{sub_context}

Genera el código COMPLETO y FINAL del sistema.
Separa cada archivo con: # --- filename.ext ---
Incluye type hints, docstrings, manejo de errores, y tests."""

        response_final = await safe_invoke(builder_llm, [
            SystemMessage(content=BUILDER_SYSTEM + "\n\nAhora produce el código FINAL completo."),
            HumanMessage(content=synthesis_prompt),
        ])
        final_content = response_final.content if hasattr(response_final, 'content') else str(response_final)

        elapsed = time.time() - t0

        # Parsear archivos del código generado
        files = {}
        current_file = None
        current_code = []
        for line in final_content.split('\n'):
            m = re.match(r'^# ---+\s*(.+\.\w+)\s*---+$', line)
            if m:
                if current_file:
                    files[current_file] = '\n'.join(current_code)
                current_file = m.group(1).strip()
                current_code = []
            elif current_file:
                current_code.append(line)
        if current_file:
            files[current_file] = '\n'.join(current_code)
        if not files and final_content.strip():
            files['main.py'] = final_content

        print(f"OK ({len(files)} archivos)")

        return {
            "system": "builder_standard",
            "test_id": test_id,
            "status": "PASS" if files else "FAIL",
            "files": files,
            "time_seconds": round(elapsed, 2),
            "llm_calls": total_calls,
            "pro_calls": pro_calls,
            "flash_calls": flash_calls,
            "delegation_log": delegation_log,
            "total_chars": len(final_content),
            "num_files": len(files),
            "strategy": strategy[:500],
        }

    except asyncio.TimeoutError:
        return {
            "system": "builder_standard",
            "test_id": test_id,
            "status": "TIMEOUT",
            "files": {},
            "time_seconds": MAX_TIMEOUT_PER_TEST,
            "llm_calls": total_calls or 1,
            "pro_calls": pro_calls or 1,
            "flash_calls": flash_calls,
            "error": f"Timeout after {MAX_TIMEOUT_PER_TEST}s",
            "total_chars": 0,
            "num_files": 0,
        }
    except Exception as e:
        elapsed = time.time() - t0
        return {
            "system": "builder_standard",
            "test_id": test_id,
            "status": "ERROR",
            "files": {},
            "time_seconds": round(elapsed, 2),
            "llm_calls": total_calls or 1,
            "pro_calls": pro_calls or 1,
            "flash_calls": flash_calls,
            "error": str(e)[:500],
            "total_chars": 0,
            "num_files": 0,
        }


def _parse_subtasks(strategy: str, requirement: str) -> list:
    """Extrae subtareas de la estrategia del builder."""
    # Intentar extraer secciones con subtareas
    subtasks = []
    lines = strategy.split('\n')
    current_task = ""
    current_desc = ""

    for line in lines:
        line = line.strip()
        if re.match(r'^(##|###|\d+\.)\s*(subagente|subtask|task|tarea|delegar|asignar)', line, re.IGNORECASE):
            if current_task:
                subtasks.append((current_task, current_desc))
            current_task = line
            current_desc = ""
        elif current_task and line and len(line) > 20:
            current_desc += line + "\n"

    if current_task:
        subtasks.append((current_task, current_desc))

    # Si no se pudo parsear, crear subtareas basadas en palabras clave
    if not subtasks:
        # Dividir el requirement en partes lógicas
        parts = re.split(r'\d+\)', requirement)
        if len(parts) > 1:
            for i, part in enumerate(parts[1:], 1):
                if part.strip():
                    subtasks.append((f"modulo_{i}", part.strip()[:500]))

    # Máximo 4 subtareas
    return subtasks[:4]


# ═══════════════════════════════════════════════════════════════════════
# GENERADOR DE REPORTE
# ═══════════════════════════════════════════════════════════════════════

def generate_report(results: list, total_time: float):
    """Genera reporte terminal + HTML."""

    # ── Preparar datos ──
    rows = []
    for test, result_a, result_b, eval_a, eval_b, cost_a, cost_b in results:
        score_a = eval_a["score"]
        score_b = eval_b["score"]
        diff = score_a - score_b
        winner = "Enjambre" if diff > 0.02 else ("Builder" if diff < -0.02 else "Empate")

        rows.append({
            "test": test,
            "score_a": score_a,
            "score_b": score_b,
            "diff": diff,
            "winner": winner,
            "result_a": result_a,
            "result_b": result_b,
            "eval_a": eval_a,
            "eval_b": eval_b,
            "cost_a": cost_a,
            "cost_b": cost_b,
        })

    # Totales
    avg_a = sum(r["score_a"] for r in rows) / len(rows)
    avg_b = sum(r["score_b"] for r in rows) / len(rows)
    total_cost_a = sum(r["cost_a"]["total_usd"] for r in rows)
    total_cost_b = sum(r["cost_b"]["total_usd"] for r in rows)
    total_time_a = sum(r["result_a"]["time_seconds"] for r in rows)
    total_time_b = sum(r["result_b"]["time_seconds"] for r in rows)
    wins_a = sum(1 for r in rows if r["winner"] == "Enjambre")
    wins_b = sum(1 for r in rows if r["winner"] == "Builder")
    ties = sum(1 for r in rows if r["winner"] == "Empate")

    efficiency_a = avg_a / max(total_cost_a, 0.000001)
    efficiency_b = avg_b / max(total_cost_b, 0.000001)

    # ── REPORTE TERMINAL ──
    print("\n" + "=" * 80)
    print("  📊 REPORTE FINAL — Enjambre 4.0 vs Builder Estándar OpenCode")
    print("=" * 80)

    print(f"\n  {'Test':<5} {'Complejidad':<15} {'Enjambre':>10} {'Builder':>10} {'Dif':>8} {'Ganador':<12}")
    print(f"  {'─'*60}")
    for r in rows:
        emoji = "🏠" if r["winner"] == "Enjambre" else ("💎" if r["winner"] == "Builder" else "🤝")
        print(f"  {r['test']['id']:<5} {r['test']['level']:<15} {r['score_a']:>10.4f} {r['score_b']:>10.4f} {r['diff']:>+8.4f} {emoji} {r['winner']:<8}")
    print(f"  {'─'*60}")
    print(f"  {'PROMEDIO':<22} {avg_a:>10.4f} {avg_b:>10.4f} {avg_a-avg_b:>+8.4f} {'🏆' if avg_a > avg_b else '💎'} {'Enjambre' if avg_a > avg_b else 'Builder'}")

    # Desglose por dimensión
    print(f"\n  📈 DESGLOSE POR DIMENSIÓN (promedio):")
    dims = ["syntax", "tests", "type_hints", "docstrings", "error_handling", "logging", "estructura", "completitud"]
    dim_labels = {
        "syntax": "Sintaxis (15%)", "tests": "Tests (20%)", "type_hints": "Type Hints (5%)",
        "docstrings": "Docstrings (5%)", "error_handling": "Error Handl. (5%)",
        "logging": "Logging (5%)", "estructura": "Estructura (5%)", "completitud": "Completitud (20%)"
    }
    print(f"  {'Dimensión':<20} {'Enjambre':>10} {'Builder':>10} {'Dif':>8}")
    print(f"  {'─'*48}")
    for dim in dims:
        avg_dim_a = sum(r["eval_a"]["dimensions"].get(dim, {}).get("score", 0) for r in rows) / len(rows)
        avg_dim_b = sum(r["eval_b"]["dimensions"].get(dim, {}).get("score", 0) for r in rows) / len(rows)
        diff_dim = avg_dim_a - avg_dim_b
        print(f"  {dim_labels[dim]:<20} {avg_dim_a:>10.3f} {avg_dim_b:>10.3f} {diff_dim:>+8.3f}")

    # Métricas de eficiencia
    print(f"\n  ⏱️  TIEMPO TOTAL:     Enjambre: {total_time_a:.0f}s | Builder: {total_time_b:.0f}s | Ratio: {total_time_a/max(total_time_b,1):.1f}x")
    print(f"  💰 COSTO ESTIMADO:   Enjambre: ${total_cost_a:.6f} | Builder: ${total_cost_b:.6f} | Ahorro: {(1-total_cost_a/max(total_cost_b,0.000001))*100:.0f}%")
    print(f"  📈 EFICIENCIA (pts/$): Enjambre: {efficiency_a:,.0f} | Builder: {efficiency_b:,.0f} | x{efficiency_a/max(efficiency_b,0.001):.1f} más eficiente")
    print(f"  🏆 MARCador:         Enjambre {wins_a} - Builder {wins_b} - Empates {ties}")

    # Veredicto
    print(f"\n  {'═'*80}")
    if avg_a > avg_b:
        print(f"  🏆 VEREDICTO: El Enjambre 4.0 SUPERA al Builder Estándar")
        print(f"     Calidad: +{(avg_a-avg_b)*100:.1f}% | Costo: {(1-total_cost_a/max(total_cost_b,0.000001))*100:.0f}% más barato")
        print(f"     El Builder es {total_time_a/max(total_time_b,1):.1f}x más rápido pero usa Pro pago constantemente.")
    else:
        print(f"  💎 VEREDICTO: El Builder Estándar SUPERA al Enjambre 4.0")
        print(f"     Calidad: +{(avg_b-avg_a)*100:.1f}% | Costo: ${total_cost_b:.4f}")
    print(f"  {'═'*80}")

    # ── REPORTE HTML ──
    html = _generate_html(rows, avg_a, avg_b, total_cost_a, total_cost_b,
                          total_time_a, total_time_b, efficiency_a, efficiency_b,
                          wins_a, wins_b, ties, total_time, dims, dim_labels)

    html_path = os.path.join(OUTPUT_DIR, "report.html")
    with open(html_path, "w") as f:
        f.write(html)

    # ── Guardar JSON ──
    json_output = {
        "fecha": datetime.datetime.now().isoformat(),
        "total_tests": len(rows),
        "resumen": {
            "score_enjambre": round(avg_a, 4),
            "score_builder": round(avg_b, 4),
            "diferencia": round(avg_a - avg_b, 4),
            "ganador": "Enjambre 4.0" if avg_a > avg_b else "Builder Estándar",
            "costo_enjambre": round(total_cost_a, 6),
            "costo_builder": round(total_cost_b, 6),
            "tiempo_enjambre": round(total_time_a),
            "tiempo_builder": round(total_time_b),
            "eficiencia_enjambre": round(efficiency_a, 2),
            "eficiencia_builder": round(efficiency_b, 2),
            "wins_enjambre": wins_a,
            "wins_builder": wins_b,
            "empates": ties,
        },
        "detalles": []
    }

    for r in rows:
        json_output["detalles"].append({
            "test_id": r["test"]["id"],
            "test_name": r["test"]["name"],
            "level": r["test"]["level"],
            "score_enjambre": r["score_a"],
            "score_builder": r["score_b"],
            "diferencia": round(r["diff"], 4),
            "ganador": r["winner"],
            "enjambre": {
                "status": r["result_a"]["status"],
                "tiempo": r["result_a"]["time_seconds"],
                "llm_calls": r["result_a"]["llm_calls"],
                "pro_calls": r["result_a"]["pro_calls"],
                "archivos": r["result_a"]["num_files"],
                "costo": r["cost_a"]["total_usd"],
            },
            "builder": {
                "status": r["result_b"]["status"],
                "tiempo": r["result_b"]["time_seconds"],
                "llm_calls": r["result_b"]["llm_calls"],
                "pro_calls": r["result_b"]["pro_calls"],
                "flash_calls": r["result_b"]["flash_calls"],
                "archivos": r["result_b"]["num_files"],
                "costo": r["cost_b"]["total_usd"],
            },
        })

    json_path = os.path.join(OUTPUT_DIR, "results.json")
    with open(json_path, "w") as f:
        json.dump(json_output, f, indent=2, ensure_ascii=False)

    print(f"\n  📁 Reportes guardados en: {OUTPUT_DIR}/")
    return html_path


def _generate_html(rows, avg_a, avg_b, total_cost_a, total_cost_b,
                   total_time_a, total_time_b, efficiency_a, efficiency_b,
                   wins_a, wins_b, ties, total_time, dims, dim_labels):
    """Genera reporte HTML con gráficas Chart.js."""

    # Preparar datos para gráficas
    test_ids_json = json.dumps([r["test"]["id"] for r in rows])
    scores_a_json = json.dumps([round(r["score_a"] * 100, 1) for r in rows])
    scores_b_json = json.dumps([round(r["score_b"] * 100, 1) for r in rows])

    dim_data_a = json.dumps([round(sum(r["eval_a"]["dimensions"].get(d, {}).get("score", 0) for r in rows) / len(rows) * 100, 1) for d in dims])
    dim_data_b = json.dumps([round(sum(r["eval_b"]["dimensions"].get(d, {}).get("score", 0) for r in rows) / len(rows) * 100, 1) for d in dims])
    dim_labels_json = json.dumps([dim_labels[d] for d in dims])

    # Tabla de resultados
    table_rows = ""
    for r in rows:
        emoji = "🏠" if r["winner"] == "Enjambre" else ("💎" if r["winner"] == "Builder" else "🤝")
        color = "#00BFA5" if r["winner"] == "Enjambre" else ( "#7C4DFF" if r["winner"] == "Builder" else "#FFC107")
        table_rows += f"""
        <tr>
            <td><strong>{r['test']['id']}</strong></td>
            <td>{r['test']['level']}</td>
            <td style="color:{'#00BFA5' if r['result_a']['status']=='PASS' else '#FF5252'}">{r['result_a']['status']}</td>
            <td>{r['score_a']:.4f}</td>
            <td style="color:{'#7C4DFF' if r['result_b']['status']=='PASS' else '#FF5252'}">{r['result_b']['status']}</td>
            <td>{r['score_b']:.4f}</td>
            <td style="color:{color};font-weight:bold">{emoji} {r['winner']}</td>
        </tr>"""

    # Detalle por test
    test_details = ""
    for r in rows:
        test_details += f"""
        <div class="test-detail" onclick="toggleDetail('detail_{r['test']['id']}')">
            <h3>{r['test']['id']}: {r['test']['name']} <span style="float:right">{'🏠' if r['winner']=='Enjambre' else '💎'} {r['winner']}</span></h3>
            <div id="detail_{r['test']['id']}" style="display:none">
                <table>
                    <tr><th>Métrica</th><th>Enjambre 4.0</th><th>Builder Std</th></tr>
                    <tr><td>Status</td><td class="{'ok' if r['result_a']['status']=='PASS' else 'fail'}">{r['result_a']['status']}</td><td class="{'ok' if r['result_b']['status']=='PASS' else 'fail'}">{r['result_b']['status']}</td></tr>
                    <tr><td>Tiempo</td><td>{r['result_a']['time_seconds']:.0f}s</td><td>{r['result_b']['time_seconds']:.0f}s</td></tr>
                    <tr><td>LLM Calls</td><td>{r['result_a']['llm_calls']} ({r['result_a']['pro_calls']} Pro)</td><td>{r['result_b']['llm_calls']} ({r['result_b']['pro_calls']} Pro + {r['result_b'].get('flash_calls',0)} Flash)</td></tr>
                    <tr><td>Archivos</td><td>{r['result_a']['num_files']}</td><td>{r['result_b']['num_files']}</td></tr>
                    <tr><td>Costo</td><td>${r['cost_a']['total_usd']:.6f}</td><td>${r['cost_b']['total_usd']:.6f}</td></tr>
                    <tr><td>Score</td><td class="{'ok' if r['score_a']>=0.5 else 'fail'}">{r['score_a']:.4f}</td><td class="{'ok' if r['score_b']>=0.5 else 'fail'}">{r['score_b']:.4f}</td></tr>
                    <tr><td>Diferencia</td><td colspan="2" style="text-align:center;font-weight:bold">{r['diff']:+.4f}</td></tr>
                </table>
            </div>
        </div>"""

    winner_text = "🏆 Enjambre 4.0" if avg_a > avg_b else "💎 Builder Estándar"
    winner_color = "#00BFA5" if avg_a > avg_b else "#7C4DFF"

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Benchmark A/B: Enjambre 4.0 vs Builder Estándar</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0d1117; color: #c9d1d9; padding: 20px; }}
        h1 {{ text-align: center; padding: 30px; font-size: 2em; }}
        .veredicto {{ text-align: center; padding: 20px; margin: 20px auto; max-width: 600px; border-radius: 12px; font-size: 1.5em; font-weight: bold; background: {winner_color}; color: white; }}
        .container {{ max-width: 1200px; margin: 0 auto; }}
        table {{ width: 100%; border-collapse: collapse; margin: 20px 0; background: #161b22; border-radius: 8px; overflow: hidden; }}
        th, td {{ padding: 12px 16px; text-align: left; border-bottom: 1px solid #30363d; }}
        th {{ background: #21262d; color: #8b949e; text-transform: uppercase; font-size: 0.85em; }}
        .ok {{ color: #3fb950 !important; }}
        .fail {{ color: #f85149 !important; }}
        .charts {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin: 30px 0; }}
        .chart-box {{ background: #161b22; border-radius: 8px; padding: 20px; }}
        .chart-box.full {{ grid-column: 1 / -1; }}
        .stats {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 16px; margin: 20px 0; }}
        .stat-card {{ background: #161b22; border-radius: 8px; padding: 20px; text-align: center; }}
        .stat-card .value {{ font-size: 2em; font-weight: bold; color: #00BFA5; }}
        .stat-card .label {{ color: #8b949e; font-size: 0.85em; margin-top: 5px; }}
        .stat-card.purple .value {{ color: #7C4DFF; }}
        .stat-card.gold .value {{ color: #FFC107; }}
        .test-detail {{ background: #161b22; border-radius: 8px; padding: 15px; margin: 10px 0; cursor: pointer; }}
        .test-detail:hover {{ background: #1c2333; }}
        footer {{ text-align: center; padding: 30px; color: #484f58; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>🧪 Benchmark A/B: Enjambre 4.0 vs Builder Estándar OpenCode</h1>
        <p style="text-align:center;color:#8b949e">{datetime.datetime.now().strftime('%Y-%m-%d %H:%M')} — {len(rows)} tests ({', '.join(r['test']['level'] for r in rows)})</p>

        <div class="veredicto">{winner_text}</div>

        <div class="stats">
            <div class="stat-card">
                <div class="value">{avg_a*100:.1f}%</div>
                <div class="label">🏠 Enjambre 4.0 — Calidad Promedio</div>
            </div>
            <div class="stat-card purple">
                <div class="value">{avg_b*100:.1f}%</div>
                <div class="label">💎 Builder Estándar — Calidad Promedio</div>
            </div>
            <div class="stat-card gold">
                <div class="value">{wins_a} - {wins_b} - {ties}</div>
                <div class="label">🏆 Marcador (G-P-E)</div>
            </div>
            <div class="stat-card">
                <div class="value">{efficiency_a/max(efficiency_b,0.001):.1f}x</div>
                <div class="label">📈 Eficiencia (pts/$) — Enjambre vs Builder</div>
            </div>
        </div>

        <h2>📊 Tabla Comparativa</h2>
        <table>
            <tr><th>Test</th><th>Nivel</th><th>Enjambre</th><th>Score A</th><th>Builder</th><th>Score B</th><th>Ganador</th></tr>
            {table_rows}
            <tr style="font-weight:bold;background:#1c2333">
                <td colspan="2">PROMEDIO</td>
                <td></td><td>{avg_a:.4f}</td>
                <td></td><td>{avg_b:.4f}</td>
                <td style="color:{winner_color}">{winner_text}</td>
            </tr>
        </table>

        <div class="charts">
            <div class="chart-box">
                <h3>Score por Test</h3>
                <canvas id="scoreChart"></canvas>
            </div>
            <div class="chart-box">
                <h3>Dimensiones de Calidad (promedio)</h3>
                <canvas id="radarChart"></canvas>
            </div>
            <div class="chart-box full">
                <h3>Costo por Test</h3>
                <canvas id="costChart"></canvas>
            </div>
        </div>

        <div class="stats">
            <div class="stat-card">
                <div class="value">{total_time_a:.0f}s</div>
                <div class="label">⏱️ Enjambre — Tiempo Total</div>
            </div>
            <div class="stat-card purple">
                <div class="value">{total_time_b:.0f}s</div>
                <div class="label">⏱️ Builder — Tiempo Total</div>
            </div>
            <div class="stat-card gold">
                <div class="value">${total_cost_a:.6f}</div>
                <div class="label">💰 Enjambre — Costo Total</div>
            </div>
            <div class="stat-card purple">
                <div class="value">${total_cost_b:.6f}</div>
                <div class="label">💰 Builder — Costo Total</div>
            </div>
        </div>

        <h2>🔍 Detalle por Test</h2>
        {test_details}

        <footer>
            Generado por el Sistema de Benchmark del Enjambre 4.0 — {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}<br>
            Tiempo total de ejecución: {total_time:.0f}s
        </footer>
    </div>

    <script>
        // Gráfica de scores por test
        new Chart(document.getElementById('scoreChart'), {{
            type: 'bar',
            data: {{
                labels: {test_ids_json},
                datasets: [
                    {{ label: 'Enjambre 4.0', data: {scores_a_json}, backgroundColor: '#00BFA580', borderColor: '#00BFA5', borderWidth: 2 }},
                    {{ label: 'Builder Std', data: {scores_b_json}, backgroundColor: '#7C4DFF80', borderColor: '#7C4DFF', borderWidth: 2 }}
                ]
            }},
            options: {{ responsive: true, scales: {{ y: {{ beginAtZero: true, max: 100, title: {{ display: true, text: 'Score (%)' }} }} }} }}
        }});

        // Gráfica radar de dimensiones
        new Chart(document.getElementById('radarChart'), {{
            type: 'radar',
            data: {{
                labels: {dim_labels_json},
                datasets: [
                    {{ label: 'Enjambre 4.0', data: {dim_data_a}, backgroundColor: '#00BFA520', borderColor: '#00BFA5', borderWidth: 2, pointBackgroundColor: '#00BFA5' }},
                    {{ label: 'Builder Std', data: {dim_data_b}, backgroundColor: '#7C4DFF20', borderColor: '#7C4DFF', borderWidth: 2, pointBackgroundColor: '#7C4DFF' }}
                ]
            }},
            options: {{ responsive: true, scales: {{ r: {{ beginAtZero: true, max: 100, ticks: {{ stepSize: 20 }} }} }} }}
        }});

        // Gráfica de costo
        const costCtx = document.getElementById('costChart');
        if (costCtx) {{
            new Chart(costCtx, {{
                type: 'bar',
                data: {{
                    labels: {test_ids_json},
                    datasets: [
                        {{ label: 'Enjambre 4.0 ($)', data: {json.dumps([round(r['cost_a']['total_usd']*1e6, 2) for r in rows])}, backgroundColor: '#00BFA580', borderColor: '#00BFA5', borderWidth: 2 }},
                        {{ label: 'Builder Std ($)', data: {json.dumps([round(r['cost_b']['total_usd']*1e6, 2) for r in rows])}, backgroundColor: '#7C4DFF80', borderColor: '#7C4DFF', borderWidth: 2 }}
                    ]
                }},
                options: {{ responsive: true, scales: {{ y: {{ beginAtZero: true, title: {{ display: true, text: 'Costo x 1e6 ($)' }} }} }} }}
            }});
        }}

        function toggleDetail(id) {{
            const el = document.getElementById(id);
            el.style.display = el.style.display === 'none' ? 'block' : 'none';
        }}
    </script>
</body>
</html>"""


# ═══════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════

async def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    print("=" * 80)
    print("  🧪 BENCHMARK A/B v5.0 — Enjambre 4.0 vs Builder Estándar OpenCode")
    print("  " + datetime.datetime.now().strftime('%Y-%m-%d %H:%M'))
    print("=" * 80)
    print(f"\n  Tests: {len(TEST_SUITE)}")
    for t in TEST_SUITE:
        print(f"    {t['id']}: {t['name']} ({t['level']})")
    print(f"\n  Path A: 🏠 Enjambre 4.0 — Pipeline real multi-agente")
    print(f"  Path B: 💎 Builder Estándar — deepseek-v4-pro delegando a subagentes")
    print(f"  Output: {OUTPUT_DIR}/\n")

    results = []

    for i, test in enumerate(TEST_SUITE):
        print(f"\n{'─'*80}")
        print(f"  🔬 TEST {test['id']}: {test['name']} ({test['level']})")
        print(f"{'─'*80}")

        # ── PATH A: Enjambre ──
        print(f"\n  🏠 PATH A: Enjambre 4.0 corriendo...")
        sys.stdout.flush()
        t0_a = time.time()
        result_a = await run_enjambre(test["requirement"], test["id"])
        t_a = time.time() - t0_a

        # Evaluar calidad
        eval_a = evaluate_result(result_a, test["requirement"])
        cost_a = estimate_cost(result_a)

        status_emoji = "✅" if result_a["status"] == "PASS" else ("⏱️" if result_a["status"] == "TIMEOUT" else "❌")
        print(f"    {status_emoji} Status: {result_a['status']} | Archivos: {result_a['num_files']} | "
              f"Calls: {result_a['llm_calls']} ({result_a['pro_calls']} Pro) | "
              f"Tiempo: {t_a:.0f}s | Score: {eval_a['score']:.4f} | Costo: ${cost_a['total_usd']:.6f}")

        # Mostrar dimensiones clave
        dims_show = ["syntax", "tests", "completitud"]
        dim_parts = [f"{d}: {eval_a['dimensions'].get(d, {}).get('score', 0):.2f}" for d in dims_show]
        print(f"    📊 {' | '.join(dim_parts)}")

        # ── PATH B: Builder ──
        print(f"\n  💎 PATH B: Builder Estándar corriendo...")
        sys.stdout.flush()
        t0_b = time.time()
        result_b = await run_builder(test["requirement"], test["id"])
        t_b = time.time() - t0_b

        # Evaluar calidad
        eval_b = evaluate_result(result_b, test["requirement"])
        cost_b = estimate_cost(result_b)

        status_emoji_b = "✅" if result_b["status"] == "PASS" else ("⏱️" if result_b["status"] == "TIMEOUT" else "❌")
        print(f"    {status_emoji_b} Status: {result_b['status']} | Archivos: {result_b['num_files']} | "
              f"Calls: {result_b['llm_calls']} ({result_b['pro_calls']} Pro + {result_b.get('flash_calls', 0)} Flash) | "
              f"Tiempo: {t_b:.0f}s | Score: {eval_b['score']:.4f} | Costo: ${cost_b['total_usd']:.6f}")

        dim_parts_b = [f"{d}: {eval_b['dimensions'].get(d, {}).get('score', 0):.2f}" for d in dims_show]
        print(f"    📊 {' | '.join(dim_parts_b)}")

        # ── Comparación ──
        diff = eval_a["score"] - eval_b["score"]
        if diff > 0.02:
            winner = "🏠 Enjambre 4.0"
        elif diff < -0.02:
            winner = "💎 Builder Estándar"
        else:
            winner = "🤝 Empate técnico"

        print(f"\n    🆚 Comparación: Enjambre {eval_a['score']:.4f} vs Builder {eval_b['score']:.4f} (dif: {diff:+.4f})")
        print(f"    🏆 {winner}")

        results.append((test, result_a, result_b, eval_a, eval_b, cost_a, cost_b))

        # Pequeña pausa entre tests
        if i < len(TEST_SUITE) - 1:
            print(f"\n  ⏳ Pausa de 3s antes del siguiente test...")
            await asyncio.sleep(3)

    # ── Reporte Final ──
    total_time = sum(r[1]["time_seconds"] for r in results) + sum(r[2]["time_seconds"] for r in results)
    html_path = generate_report(results, total_time)
    print(f"\n  🌐 Reporte HTML: {html_path}")

    # Veredicto final
    avg_a = sum(r[3]["score"] for r in results) / len(results)
    avg_b = sum(r[4]["score"] for r in results) / len(results)
    print(f"\n{'='*80}")
    print(f"  🎯 CONCLUSIÓN FINAL")
    print(f"{'='*80}")
    print(f"  Calidad:    Enjambre {avg_a*100:.1f}% vs Builder {avg_b*100:.1f}%")
    print(f"  Ganador:    {'🏠 Enjambre 4.0' if avg_a > avg_b else '💎 Builder Estándar'}")
    print(f"  {'='*80}")
    print()


if __name__ == "__main__":
    asyncio.run(main())
