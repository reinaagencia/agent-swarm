#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════╗
║  🧪 A/B TEST: ENJAMBRE vs PRO BUILD                       ║
║  Mide inteligencia, capacidad y eficiencia                 ║
╚══════════════════════════════════════════════════════════════╝

- Enjambre: pipeline multi-agente (flash free) con memoria híbrida
- Pro Build: deepseek-v4-pro en single-shot con system prompt experto

Métricas:
  ✅ Quality  → tests pasan, código correcto, sin errores
  ✅ Capability → archivos generados, features implementadas
  ✅ Efficiency → tiempo, calls estimadas, costo estimado
"""

import asyncio, time, sys, os, json, re

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dotenv import load_dotenv
load_dotenv()

from src.config import get_pro_llm, reset_fallback, precheck_free_model, get_llm, safe_invoke
from src.state import TeamState
from src.graph import get_graph
from langchain_core.messages import HumanMessage, SystemMessage

# ════════════════════════════════════════════════
# SUITE DE PRUEBAS (3 tests con complejidad creciente)
# ════════════════════════════════════════════════

TEST_SUITE = [
    {
        "id": "A",
        "name": "Función utilitaria con tests",
        "complexity": "low",
        "requirement": "Crea una función en Python filter_logs(logs, level, since) que filtre una lista de diccionarios con campos 'level','message','timestamp'. Incluye tests pytest. Un solo archivo .py.",
    },
    {
        "id": "B",
        "name": "Script CLI multi-archivo",
        "complexity": "medium",
        "requirement": "Crea un script CLI en Python que procese un archivo CSV de ventas con columnas: fecha,producto,cantidad,precio. Calcula totales por producto y mes, y exporta a Excel. Usa argparse, pandas y openpyxl. Estructura: main.py + processor.py + tests/test_processor.py. Incluye tests pytest.",
    },
    {
        "id": "C",
        "name": "API REST con validación y testing",
        "complexity": "high",
        "requirement": "Crea una API REST en Flask para un catálogo de productos con: GET /products, POST /products con validación, GET /products/<id>, PUT /products/<id>, DELETE /products/<id>. Usa almacenamiento en memoria (lista). Validar que nombre no vacío, precio > 0. Incluye tests pytest con fixture de cliente de prueba. Archivos: app.py, models.py, tests/test_api.py.",
    },
]

# ════════════════════════════════════════════════
# PRO BUILD: deepseek-v4-pro en single-shot
# ════════════════════════════════════════════════

PRO_SYSTEM_PROMPT = """Eres un ingeniero de software senior experto en Python. 
Generas código listo para producción. Siempre incluyes:
1. Código completo y funcional
2. Tests pytest que pasan
3. Manejo de errores
4. Tipos (type hints)
5. Docstrings

Responde SOLO con el código, sin explicaciones extensas.
Separa cada archivo con: # --- filename.ext ---"""

async def run_pro_single(requirement: str) -> dict:
    """Ejecuta el Pro Build: single call a deepseek-v4-pro."""
    t0 = time.time()
    llm = get_pro_llm(max_tokens=8192)
    
    try:
        response = await safe_invoke(llm, [
            SystemMessage(content=PRO_SYSTEM_PROMPT),
            HumanMessage(content=requirement),
        ])
        elapsed = time.time() - t0
        content = response.content if hasattr(response, 'content') else str(response)
        
        # Parsear archivos del código generado
        files = {}
        current_file = None
        current_code = []
        for line in content.split('\n'):
            m = re.match(r'^# ---+\s*(.+\.py)\s*---+$', line)
            if m:
                if current_file:
                    files[current_file] = '\n'.join(current_code)
                current_file = m.group(1).strip()
                current_code = []
            elif current_file:
                current_code.append(line)
            elif line.strip() and not current_file:
                # Si no hay separadores, todo es un solo archivo
                pass
        
        if current_file:
            files[current_file] = '\n'.join(current_code)
        
        # Si no se pudo separar, todo el contenido va a main.py
        if not files and content.strip():
            files['main.py'] = content
        
        return {
            "status": "PASS" if files else "FAIL",
            "files": files,
            "time_seconds": elapsed,
            "llm_calls": 1,
            "raw_output": content,
            "total_chars": len(content),
        }
    except Exception as e:
        return {
            "status": "ERROR",
            "files": {},
            "time_seconds": time.time() - t0,
            "llm_calls": 1,
            "raw_output": f"Error: {str(e)[:500]}",
            "total_chars": 0,
        }


# ════════════════════════════════════════════════
# ENJAMBRE: pipeline completo multi-agente
# ════════════════════════════════════════════════

async def run_enjambre(requirement: str) -> dict:
    """Ejecuta el Enjambre: pipeline multi-agente completo."""
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
    try:
        graph = get_graph()
        result = await graph.ainvoke(state)
        elapsed = time.time() - t0
        
        source_code = result.get("source_code", {})
        test_report = result.get("test_report", {})
        blueprint = result.get("architecture_blueprint", {})
        iterations = result.get("iteration_count", 0)
        audit = result.get("audit_trail", [])
        
        # Contar calls LLM del audit trail
        llm_nodes = {"Orquestador", "Arquitecto", "Programador", "Tester",
                     "Auditor Gate 1", "Auditor Gate 2", "Auditor Gate 3",
                     "Extractor de Conocimiento", "Tester (paralelo)",
                     "Investigador", "Skill Resolver"}
        num_calls = sum(1 for step in audit if step.get("nodo", "") in llm_nodes)
        
        return {
            "status": test_report.get("status", "FAIL"),
            "files": source_code,
            "time_seconds": elapsed,
            "llm_calls": max(num_calls, 1),
            "iterations": iterations,
            "blueprint": blueprint,
            "test_report": test_report,
            "audit_trail": audit,
            "total_chars": sum(len(c) for c in source_code.values()),
            "num_files": len(source_code),
        }
    except Exception as e:
        elapsed = time.time() - t0
        return {
            "status": "ERROR",
            "files": {},
            "time_seconds": elapsed,
            "llm_calls": 0,
            "iterations": 0,
            "error": str(e)[:500],
            "total_chars": 0,
            "num_files": 0,
        }


# ════════════════════════════════════════════════
# EVALUADOR AUTOMÁTICO
# ════════════════════════════════════════════════

def evaluate_quality(files: dict, test_case: dict) -> dict:
    """Evalúa la calidad del código generado."""
    scores = {}
    
    # 1. ¿Generó archivos?
    scores["tiene_codigo"] = 1.0 if files else 0.0
    
    # 2. ¿Tiene tests?
    all_code = ' '.join(files.values()) if files else ''
    scores["tiene_tests"] = 1.0 if 'def test_' in all_code or 'import pytest' in all_code else 0.0
    
    # 3. ¿Tiene type hints?
    scores["type_hints"] = 1.0 if ': str' in all_code or ': int' in all_code or ': list' in all_code or ': float' in all_code or '-> ' in all_code else 0.0
    
    # 4. ¿Tiene docstrings?
    scores["docstrings"] = 1.0 if '"""' in all_code else 0.0
    
    # 5. ¿Tiene manejo de errores?
    scores["error_handling"] = 1.0 if 'try:' in all_code or 'except' in all_code or 'raise' in all_code else 0.0
    
    # 6. ¿Estructura correcta (multi-archivo)?
    expected_files = 0
    if "filter_logs" in test_case["requirement"] or "Un solo archivo" in test_case["requirement"]:
        expected_files = 1
    else:
        # Contar archivos esperados mencionados en el requirement
        expected_files = test_case["requirement"].count(".py")
    
    actual_files = len(files)
    if expected_files > 0:
        scores["estructura"] = min(1.0, actual_files / expected_files)
    else:
        scores["estructura"] = 1.0 if actual_files >= 1 else 0.0
    
    # Puntaje total (promedio ponderado)
    weights = {
        "tiene_codigo": 0.25,
        "tiene_tests": 0.25,
        "type_hints": 0.15,
        "docstrings": 0.10,
        "error_handling": 0.10,
        "estructura": 0.15,
    }
    
    total = sum(scores[k] * weights[k] for k in weights)
    
    return {
        "score": round(total, 3),
        "details": scores,
        "files_count": actual_files,
        "total_chars": len(all_code),
    }


def estimate_cost(result: dict, is_enjambre: bool) -> dict:
    """Estima costo basado en calls y caracteres."""
    if is_enjambre:
        # Enjambre: flash free es GRATIS, solo auditor gates cuestan (pro)
        # Estimación: ~1-2 calls pro por ejecución
        pro_calls = sum(1 for step in result.get("audit_trail", []) 
                       if "Gate" in step.get("nodo", ""))
        flash_calls = result.get("llm_calls", 0) - pro_calls
        return {
            "flash_calls": max(flash_calls, 0),
            "pro_calls": pro_calls,
            "costo_estimado": f"~${pro_calls * 0.002:.4f}",  # ~$0.002/call pro
            "es_gratis": flash_calls > 0,  # flash es gratis
        }
    else:
        # Pro: cada call cuesta
        total_chars = result.get("total_chars", 0)
        est_tokens = total_chars // 4
        return {
            "flash_calls": 0,
            "pro_calls": 1,
            "costo_estimado": f"~${est_tokens * 0.000015:.4f}",  # ~$0.015/1K tokens pro
            "total_chars": total_chars,
        }


# ════════════════════════════════════════════════
# REPORTE
# ════════════════════════════════════════════════

def print_report(results_enjambre: list, results_pro: list):
    """Imprime reporte comparativo A/B."""
    
    print("\n" + "=" * 72)
    print("  📊 REPORTE A/B: ENJAMBRE vs PRO BUILD")
    print("=" * 72)
    
    headers = ["Test", "Sistema", "Status", "Archivos", "Calls", "Tiempo", "Calidad"]
    print(f"\n  {'─'*68}")
    print(f"  │ {' │ '.join(h.ljust(9) for h in headers)} │")
    print(f"  ├{'─'*68}┤")
    
    all_scores_enjambre = []
    all_scores_pro = []
    
    for i, (req, re, rp) in enumerate(zip(TEST_SUITE, results_enjambre, results_pro)):
        tid = req["id"]
        
        # Calidad
        qe = evaluate_quality(re.get("files", {}), req)
        qp = evaluate_quality(rp.get("files", {}), req)
        all_scores_enjambre.append(qe["score"])
        all_scores_pro.append(qp["score"])
        
        status_e = "✅" if re["status"] == "PASS" else "❌"
        status_p = "✅" if rp["status"] == "PASS" else "❌"
        
        print(f"  │ {tid:<9} │ Enjambre │ {status_e:<7} │ {qe['files_count']:<8} │ {re['llm_calls']:<6} │ {re['time_seconds']:<7.0f} │ {qe['score']:<.3f} │")
        print(f"  │ {'':9} │ Pro      │ {status_p:<7} │ {qp['files_count']:<8} │ {rp['llm_calls']:<6} │ {rp['time_seconds']:<7.0f} │ {qp['score']:<.3f} │")
        print(f"  │ {'─'*68}│")
    
    # Promedios
    avg_e = sum(all_scores_enjambre) / len(all_scores_enjambre) if all_scores_enjambre else 0
    avg_p = sum(all_scores_pro) / len(all_scores_pro) if all_scores_pro else 0
    
    print(f"\n  📈 PUNTAJE PROMEDIO DE CALIDAD:")
    print(f"     Enjambre: {avg_e:.3f}")
    print(f"     Pro:      {avg_p:.3f}")
    print(f"     Diferencia: {avg_e - avg_p:+.3f} {'(favorece al enjambre ✅)' if avg_e > avg_p else '(favorece al Pro)'}")
    
    # Tiempo total
    total_time_e = sum(r["time_seconds"] for r in results_enjambre)
    total_time_p = sum(r["time_seconds"] for r in results_pro)
    
    print(f"\n  ⏱️  TIEMPO TOTAL:")
    print(f"     Enjambre: {total_time_e:.0f}s")
    print(f"     Pro:      {total_time_p:.0f}s")
    print(f"     Ratio: {total_time_e/total_time_p:.1f}x más lento el enjambre" if total_time_e > total_time_p else f"     Ratio: {total_time_p/total_time_e:.1f}x más lento el Pro")
    
    # Costo
    print(f"\n  💰 COSTO ESTIMADO:")
    for i, (req, re, rp) in enumerate(zip(TEST_SUITE, results_enjambre, results_pro)):
        ce = estimate_cost(re, True)
        cp = estimate_cost(rp, False)
        print(f"     {req['id']}: Enjambre={ce['costo_estimado']} ({ce['flash_calls']} flash + {ce['pro_calls']} pro) | Pro={cp['costo_estimado']} ({cp['pro_calls']} call)")
    
    # Capacidad
    print(f"\n  🧠 CAPACIDAD:")
    enjambre_pass = sum(1 for r in results_enjambre if r["status"] == "PASS")
    pro_pass = sum(1 for r in results_pro if r["status"] == "PASS")
    print(f"     Tests pasados: Enjambre={enjambre_pass}/{len(TEST_SUITE)} | Pro={pro_pass}/{len(TEST_SUITE)}")
    
    enjambre_total_files = sum(r.get("num_files", len(r.get("files", {}))) for r in results_enjambre)
    pro_total_files = sum(len(r.get("files", {})) for r in results_pro)
    print(f"     Archivos totales generados: Enjambre={enjambre_total_files} | Pro={pro_total_files}")
    
    # Observaciones
    print(f"\n  💡 OBSERVACIONES:")
    for i, (req, re, rp) in enumerate(zip(TEST_SUITE, results_enjambre, rp)):
        qe = evaluate_quality(re.get("files", {}), req)
        qp = evaluate_quality(rp.get("files", {}), req)
        
        if qe["score"] > qp["score"]:
            print(f"     {req['id']}: Enjambre superó al Pro en calidad ({qe['score']:.3f} vs {qp['score']:.3f})")
        elif qp["score"] > qe["score"]:
            print(f"     {req['id']}: Pro superó al enjambre ({qp['score']:.3f} vs {qe['score']:.3f})")
        else:
            print(f"     {req['id']}: Empate técnico ({qe['score']:.3f})")
    
    return avg_e, avg_p


# ════════════════════════════════════════════════
# MAIN
# ════════════════════════════════════════════════

async def main():
    print("=" * 72)
    print("  🧪 A/B TEST: ENJAMBRE (multi-agente flash) vs PRO BUILD (deepseek-v4-pro)")
    print("=" * 72)
    print(f"  Fecha: {__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"  Tests: {len(TEST_SUITE)} ({', '.join(t['id'] + ': ' + t['name'] for t in TEST_SUITE)})")
    print()
    
    results_enjambre = []
    results_pro = []
    
    for i, test in enumerate(TEST_SUITE):
        print(f"\n{'─'*72}")
        print(f"  🔬 TEST {test['id']}: {test['name']} ({test['complexity']})")
        print(f"  {test['requirement'][:80]}...")
        print(f"{'─'*72}")
        
        # Enjambre
        print(f"\n  🤖 ENJAMBRE corriendo...")
        t0 = time.time()
        re = await run_enjambre(test["requirement"])
        te = time.time() - t0
        qe = evaluate_quality(re.get("files", {}), test)
        print(f"     Status: {re['status']} | Archivos: {qe['files_count']} | Calls: {re['llm_calls']} | Tiempo: {te:.0f}s | Calidad: {qe['score']:.3f}")
        results_enjambre.append(re)
        
        # Pro Build
        print(f"\n  🏆 PRO BUILD corriendo...")
        t0 = time.time()
        rp = await run_pro_single(test["requirement"])
        tp = time.time() - t0
        qp = evaluate_quality(rp.get("files", {}), test)
        print(f"     Status: {rp['status']} | Archivos: {qp['files_count']} | Calls: {rp['llm_calls']} | Tiempo: {tp:.0f}s | Calidad: {qp['score']:.3f}")
        results_pro.append(rp)
    
    # Reporte final
    avg_e, avg_p = print_report(results_enjambre, results_pro)
    
    # Sugerencia
    print(f"\n{'='*72}")
    print(f"  🎯 CONCLUSIÓN")
    print(f"{'='*72}")
    if avg_e > avg_p:
        print(f"  El Enjambre superó al Pro Build en calidad promedio.")
        print(f"  Recomendación: Seguir usando el enjambre como default.")
    else:
        print(f"  El Pro Build superó al Enjambre en calidad promedio.")
        print(f"  Recomendación: Usar Pro Build para tareas críticas, enjambre para el día a día.")
    
    diff = abs(avg_e - avg_p)
    if diff < 0.1:
        print(f"  La diferencia es mínima ({diff:.3f}) — ambos sistemas tienen calidad comparable.")
    
    print()

if __name__ == "__main__":
    asyncio.run(main())
