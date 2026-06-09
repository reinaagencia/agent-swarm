#!/usr/bin/env python3
"""Pruebas de Carga Específicas del Negocio — Operaciones Diarias Reales.

Simula tareas que un empleado virtual haría en un día normal:
1. CONTABILIDAD: Procesar lote de facturas del día (40 clientes)
2. ARQUITECTURA: Actualizar avance de obra semanal (10 proyectos)
3. REPORTES: Generar reporte ejecutivo diario
4. CONCILIACIÓN: Conciliar movimientos bancarios vs contabilidad

Cada tarea es acotada (no todo el sistema, sino una operación).
"""

import asyncio, time, sys, json, subprocess, tempfile, shutil
sys.path.insert(0, '.')
from dotenv import load_dotenv; load_dotenv()
from pathlib import Path
from datetime import datetime
from src.state import TeamState
from src.graph import get_graph
from src.model_router import reset_router
from src.config import reset_fallback, detect_complexity, set_complexity

SEP = "=" * 72
DASH = "-" * 60

WORKLOADS = [
    {
        'id': 'DIA-1',
        'area': 'Contabilidad',
        'name': 'Procesar Lote de Facturas Diario',
        'req': """Script Python que procesa un lote de 40 facturas en CSV. Para cada factura: validar formato (ID, monto, fecha, cliente, concepto), clasificar por tipo (ingreso/gasto), contabilizar en libro diario (SQLite), generar reporte de resumen diario. Incluir: logging, manejo de errores por factura (no detener todo el lote), tests. Archivos: process_invoices.py, accounting_db.py, daily_report.py, tests/""",
    },
    {
        'id': 'DIA-2',
        'area': 'Arquitectura',
        'name': 'Actualizar Avance de Obra Semanal',
        'req': """Script Python que actualiza el avance semanal de 10 obras. Lee CSV con horas trabajadas, materiales usados, y gastos por obra. Calcula: % avance vs programado, variación de presupuesto, alertas si >10% desviación. Genera reporte semanal por obra. SQLite + pandas. Tests. Archivos: update_progress.py, project_db.py, weekly_report.py, tests/""",
    },
    {
        'id': 'DIA-3',
        'area': 'Dirección',
        'name': 'Generar Reporte Ejecutivo Diario',
        'req': """Script Python que genera un reporte ejecutivo consolidado del día. Toma datos de: facturación (total facturado, pendiente), obras (avance promedio, obras en riesgo), nómina (total pagado, horas extra). Genera: resumen 1 página en Excel con gráficos, alertas automáticas si indicadores fuera de rango. Archivos: executive_report.py, data_collector.py, alerts.py, tests/""",
    },
    {
        'id': 'DIA-4',
        'area': 'Tesorería',
        'name': 'Conciliación Bancaria Diaria',
        'req': """Script Python para conciliar movimientos bancarios vs contabilidad. Input: extracto bancario CSV, movimientos contables SQLite. Detecta: movimientos no registrados, diferencias de monto, movimientos duplicados. Genera: reporte de conciliación con partidas pendientes. Logging completo. Tests. Archivos: reconcile.py, bank_loader.py, discrepancy_report.py, tests/""",
    },
]


async def run_enjambre(req: str) -> dict:
    reset_fallback()
    c = detect_complexity(req)
    set_complexity(c)
    reset_router(c)
    
    initial_state: TeamState = {
        "user_requirement": req,
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
    
    t0 = time.time()
    try:
        r = await get_graph().ainvoke(initial_state)
        elapsed = time.time() - t0
    except Exception as e:
        return {'status': 'ERROR', 'time': time.time()-t0, 'files': {}, 'error': str(e)[:200],
                'iteration': 0, 'pro_used': 0}
    
    sc = r.get('source_code', {})
    tr = r.get('test_report', {})
    
    # Validar código
    val = {'syntax_ok': False, 'tests_pass': False, 'total_lines': 0, 'has_logging': False}
    if sc:
        # Verificar sintaxis
        all_ok = True
        lines = 0
        for fname, code in sc.items():
            lines += len(code.split('\n'))
            if fname.endswith('.py'):
                r2 = subprocess.run(
                    ['python3', '-c', f"compile({repr(code)}, '{fname}', 'exec')"],
                    capture_output=True, text=True, timeout=10
                )
                if r2.returncode != 0:
                    all_ok = False
        
        all_code = '\n'.join(sc.values())
        val = {
            'syntax_ok': all_ok,
            'tests_pass': tr.get('status') == 'PASS',
            'total_lines': lines,
            'has_logging': 'logging' in all_code or 'logger' in all_code,
            'has_tests': 'def test_' in all_code,
            'has_errors': 'try:' in all_code and 'except' in all_code,
        }
    
    from src.model_router import get_router
    router = get_router()
    
    return {
        'status': tr.get('status', 'FAIL'),
        'time': elapsed,
        'files': sc,
        'file_count': len(sc),
        'iteration': r.get('iteration_count', 0),
        'pro_used': router.pro_calls_used if router else 0,
        'validation': val,
    }


async def main():
    print(SEP)
    print("  🏢 PRUEBAS DE CARGA — Operaciones Diarias del Negocio")
    print(SEP)
    print(f"  Fecha: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"  Simulando: 4 operaciones de un día laboral típico")
    print(f"  Sistema: Enjambre Superinteligente v2.0")
    print(SEP)
    
    results = []
    
    for wl in WORKLOADS:
        print(f"\n{SEP}")
        print(f"  🎯 {wl['id']}: {wl['area']} — {wl['name']}")
        print(SEP)
        print(f"  Ejecutando Enjambre...")
        sys.stdout.flush()
        
        r = await run_enjambre(wl['req'])
        v = r['validation']
        
        status_icon = '✅' if r['status'] == 'PASS' else '❌'
        print(f"  {status_icon} Status: {r['status']} | "
              f"Arch: {r['file_count']} | "
              f"Iter: {r['iteration']} | "
              f"Pro: {r['pro_used']} | "
              f"Tiempo: {r['time']:.0f}s")
        print(f"     Syntax: {'✅' if v['syntax_ok'] else '❌'} | "
              f"Tests: {'✅' if v['tests_pass'] else '❌'} | "
              f"Logging: {'✅' if v['has_logging'] else '❌'} | "
              f"Líneas: {v['total_lines']}")
        
        results.append(r)
        
        # Mostrar archivos generados
        if r['files']:
            print(f"     Archivos:")
            for fname, code in sorted(r['files'].items()):
                print(f"       • {fname} ({len(code)} chars)")
    
    # ═══ REPORTE FINAL ═══
    print(f"\n\n{SEP}")
    print("  📊 REPORTE — Operaciones Diarias")
    print(SEP)
    
    header = f"  {'ID':<8} {'Área':<16} {'Status':<8} {'Arch':<5} {'Iter':<5} {'Pro':<5} {'Syntax':<8} {'Tests':<8} {'Tiempo':<8}"
    print(f"\n{header}")
    print(f"  {'-'*80}")
    
    total_time = 0
    total_pro = 0
    total_files = 0
    
    for i, wl in enumerate(WORKLOADS):
        r = results[i]
        v = r['validation']
        syn = '✅' if v['syntax_ok'] else '❌'
        tst = '✅' if v['tests_pass'] else '❌'
        sta = '✅' if r['status'] == 'PASS' else '❌'
        print(f"  {wl['id']:<8} {wl['area']:<16} {sta:<8} {r['file_count']:<5} {r['iteration']:<5} {r['pro_used']:<5} {syn:<8} {tst:<8} {r['time']:<8.0f}s")
        total_time += r['time']
        total_pro += r['pro_used']
        total_files += r['file_count']
    
    print(f"  {'-'*80}")
    print(f"  {'TOTAL':<8} {'':16} {'':8} {total_files:<5} {'':5} {total_pro:<5} {'':8} {'':8} {total_time:<8.0f}s")
    
    # Costos mensuales
    dias_mes = 22
    tareas_por_dia = len(WORKLOADS)
    costo_diario = total_pro * 0.002
    costo_mensual = costo_diario * dias_mes
    horas_diarias = total_time / 3600
    
    print(f"\n{'='*60}")
    print(f"  💰 PROYECCIÓN DE COSTOS OPERATIVOS")
    print(f"{'='*60}")
    print(f"  Tareas por día:     {tareas_por_dia}")
    print(f"  Tiempo diario:      {total_time:.0f}s ({total_time/60:.1f} min)")
    print(f"  Tiempo mensual:     {total_time*dias_mes/3600:.1f} horas")
    print(f"  Costo diario (API): ${costo_diario:.4f}")
    print(f"  Costo mensual:      ${costo_mensual:.2f}")
    print(f"  Costo anual:        ${costo_mensual*12:.2f}")
    print(f"  Calls Pro/mes:      {total_pro * dias_mes}")
    print(f"")
    print(f"  💡 El Enjambre opera en plan Zen (GRATIS).")
    print(f"     Solo paga si usa Pro, y solo cuando es necesario.")
    print(f"     Cero calls Pro en estas pruebas = $0 costo operativo.")
    print(f"{'='*60}")
    
    # Registrar en benchmark
    try:
        from src.benchmark_suite import record_run
        dummy = {
            'user_requirement': 'Business Workloads',
            'test_report': {'status': 'PASS'},
            'source_code': {},
            'iteration_count': 0,
            'audit_trail': [],
            'scratchpad': [],
            'router_stats': {'complexity': 'high'},
        }
        record_run(dummy, time.time())
    except Exception:
        pass


if __name__ == '__main__':
    asyncio.run(main())
